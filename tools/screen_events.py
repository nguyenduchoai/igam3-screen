# What can interrupt or dim the main screen, whatever it shows ("igam3-screen run" starts the Monitor thread):
#   alerts:   high temperature, disk almost full, no network, stopped services -> red screen, brighter, Telegram message
#   night:    dim or turn off the screen during the night
#   shutdown: "shutting down / safe to unplug" screens when the whole system goes down (Linux, systemd)

import datetime
import json
import os
import re
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import psutil
from PIL import Image, ImageDraw, ImageFont

from i18n import tr

FONTS = Path(__file__).resolve().parent.parent / "app" / "res" / "fonts"
W, H = 480, 320
SERIAL = threading.RLock()  # one command at a time on the serial link: a picture is a command followed by its data
ALERT_BRIGHTNESS = 90
SHOW_S, PAUSE_S = 15, 45  # while a problem lasts: the red screen 15 s, then the main screen 45 s
CHECK_S = 15
START_DELAY_S = int(os.environ.get("IGAM3_MONITOR_DELAY", 30))  # let the main screen start first
NETWORK_FAILURES = 3  # checks in a row without Internet before the alert (~45 s)
SYSTEM_DISK = Path.home().anchor if os.name == "nt" else "/"
DEFAULTS = {
    "alerts": {"enabled": True, "temperature": 85, "disk": 90, "network": True, "services": []},
    "night": {"enabled": False, "start": "22:00", "end": "06:00", "action": "dim", "brightness": 10},
}
RUNNING_STATES = ("active", "activating", "reloading", "refreshing")


def merged(settings, key):
    value = dict(DEFAULTS[key])
    value.update((settings or {}).get(key) or {})
    return value


def font(name, size):
    return ImageFont.truetype(str(FONTS / name), size)


def fit(draw, text, name, size, width, smallest=10):
    while size > smallest and draw.textlength(text, font=font(name, size)) > width:
        size -= 1
    return font(name, size)


# ---------------------------------------------------------------- the display of the running main screen

class ScreenControl:
    """Brightness, on/off and the alert screen over whatever main screen runs"""

    def __init__(self, brightness):
        self.base = int(brightness)  # brightness of config.yaml
        self.lcd = None  # the lcd object, or a function returning it (dashboard of turing-smart-screen-python)
        self.redraw = None  # draws the main screen again after the alert screen
        self.draw_direct = None  # draws even while the main screen is held back (set by install_mirror)
        self.overlay = False  # the alert screen is shown: drawings of the main screen are dropped
        self.night = None  # None, "dim" or "off"
        self.night_level = 10
        self.screen_off = False
        self.level = self.base

    def attach(self, lcd, redraw=None):
        self.lcd = lcd
        if redraw:
            self.redraw = redraw

    def get_lcd(self):
        return self.lcd() if callable(self.lcd) else self.lcd

    def blocks_main(self):
        return self.overlay

    def light(self):
        """Apply brightness / on / off for the current state"""
        lcd = self.get_lcd()
        if lcd is None:
            return
        if self.overlay:
            off, level = False, max(self.base, ALERT_BRIGHTNESS)
        elif self.night == "off":
            off, level = True, None
        elif self.night == "dim":
            off, level = False, min(self.base, self.night_level)
        else:
            off, level = False, self.base
        with SERIAL:
            if off:
                if not self.screen_off:
                    lcd.ScreenOff()
                    self.screen_off = True
                return
            if self.screen_off:
                lcd.ScreenOn()
                self.screen_off = False
            if level != self.level:
                lcd.SetBrightness(level)
                self.level = level

    def show(self, image):
        self.overlay = True
        self.light()
        self.draw_direct(self.get_lcd(), image)

    def hide(self):
        self.overlay = False
        self.light()
        if self.redraw:
            self.redraw()

    def set_night(self, state, level):
        if (state, level) != (self.night, self.night_level):
            self.night, self.night_level = state, level
            self.light()


# ---------------------------------------------------------------- measures

def cpu_temperature():
    try:
        sensors = psutil.sensors_temperatures()
    except (AttributeError, OSError):
        return None  # Windows: not available
    for chip, prefix in (("coretemp", "package"), ("k10temp", "tctl")):
        values = [e.current for e in sensors.get(chip, []) if e.label.lower().startswith(prefix)]
        if values:
            return max(values)
    values = [e.current for entries in sensors.values() for e in entries if e.current]
    return max(values) if values else None


def internet_ok():
    for host, port in (("1.1.1.1", 443), ("8.8.8.8", 53)):
        try:
            with socket.create_connection((host, port), timeout=3):
                return True
        except OSError:
            pass
    return False


def unit_state(unit):
    """State of a systemd unit: "active", "failed", "inactive", "not-found"...; "user:name.service" for user units"""
    user = unit.startswith("user:")
    name = unit[5:] if user else unit
    try:
        out = subprocess.run(["systemctl", *(["--user"] if user else []), "show", "-p", "LoadState", "-p", "ActiveState",
                              name], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    fields = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    if fields.get("LoadState") == "not-found":
        return "not-found"
    return fields.get("ActiveState", "unknown")


def shutdown_kind():
    """"reboot" or "poweroff" while the whole system goes down, else None"""
    if os.name == "nt":
        return None
    try:
        jobs = subprocess.run(["systemctl", "list-jobs", "--no-legend"], capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    if re.search(r"\b(reboot|kexec)\.target\b", jobs):
        return "reboot"
    if re.search(r"\b(poweroff|halt|shutdown)\.target\b", jobs):
        return "poweroff"
    return None


# ---------------------------------------------------------------- Telegram

class Telegram:
    """Messages through a Telegram bot of the user (token and chat in telegram.yaml, readable by the user only)"""

    API = "https://api.telegram.org/bot{token}/{method}"

    def __init__(self, path):
        self.path = Path(path)
        self.pending = []
        self.lock = threading.Lock()

    def saved(self):
        """What telegram.yaml holds (a token alone while no chat is chosen yet)"""
        try:
            import yaml
            return yaml.safe_load(self.path.read_text(encoding="utf8")) or {}
        except (OSError, ValueError, ImportError):
            return {}

    def config(self):
        data = self.saved()
        return data if data.get("token") and data.get("chat_id") else None

    @classmethod
    def call(cls, token, method, **params):
        url = cls.API.format(token=token, method=method)
        data = urllib.parse.urlencode(params).encode() if params else None
        request = urllib.request.Request(url, data=data, headers={"User-Agent": "igam3-screen"})
        with urllib.request.urlopen(request, timeout=15) as response:
            answer = json.loads(response.read(1024 * 1024))
        if not answer.get("ok"):
            raise ValueError(answer.get("description", "Telegram error"))
        return answer["result"]

    def send(self, text):
        """Queue a message and send it in the background (kept until the network is back)"""
        if not self.config():
            return
        with self.lock:
            self.pending = (self.pending + [text])[-30:]
        threading.Thread(target=self.flush, daemon=True).start()

    def flush(self):
        config = self.config()
        with self.lock:
            while config and self.pending:
                try:
                    self.call(config["token"], "sendMessage", chat_id=config["chat_id"], text=self.pending[0])
                except (OSError, ValueError):
                    return
                self.pending.pop(0)


CHAT_SOURCES = ("message", "edited_message", "channel_post", "edited_channel_post", "my_chat_member", "chat_member")


def _chat_name(chat):
    return chat.get("title") or " ".join(x for x in (chat.get("first_name"), chat.get("last_name")) if x) or \
        chat.get("username") or str(chat.get("id"))


def telegram_link(token, chat_id=None):
    """(bot name, chat id, chat name) for the alerts; ValueError with what to do otherwise.
    Without chat_id the chat comes from the last update the bot received: a message to the bot, a command in a group
    (/start@bot), or the bot being added to a group or channel."""
    token = token.strip()
    if not re.fullmatch(r"\d+:[\w-]{30,}", token):
        raise ValueError(tr("mã bot không đúng dạng (ví dụ 123456789:AAE…)", "the bot token looks wrong (like 123456789:AAE…)"))
    try:
        bot = Telegram.call(token, "getMe")
    except urllib.error.HTTPError as e:
        if e.code in (401, 404):
            raise ValueError(tr("Telegram không nhận mã bot này: kiểm tra lại mã từ @BotFather",
                                "Telegram does not accept this bot token: check it again in @BotFather"))
        raise ValueError(tr(f"Telegram báo lỗi: {e}", f"Telegram error: {e}"))
    except OSError as e:
        raise ValueError(tr(f"không kết nối được Telegram: {e}", f"cannot reach Telegram: {e}"))
    name = bot["username"]
    if chat_id not in (None, ""):
        text = str(chat_id).strip()
        if not re.fullmatch(r"-?\d+|@\w{4,}", text):
            raise ValueError(tr("ID nhóm/chat là một số, ví dụ -1001234567890", "a group/chat ID is a number, like -1001234567890"))
        # Telegram Web shows supergroups as -123…, the Bot API wants -100123…
        candidates = [text] + ([f"-100{text[1:]}"] if text.startswith("-") and not text.startswith("-100") else [])
        for candidate in candidates:
            try:
                chat = Telegram.call(token, "getChat", chat_id=candidate)
                return name, chat["id"], _chat_name(chat)
            except urllib.error.HTTPError:
                continue
            except OSError as e:
                raise ValueError(tr(f"không kết nối được Telegram: {e}", f"cannot reach Telegram: {e}"))
        raise ValueError(tr(f"bot @{name} không vào được chat {text}: thêm bot vào nhóm đó (hoặc nhắn cho bot trước) rồi thử lại",
                            f"the bot @{name} cannot reach the chat {text}: add it to that group (or message it first), then retry"))
    try:
        updates = Telegram.call(token, "getUpdates", limit=100,
                                allowed_updates=json.dumps(list(CHAT_SOURCES)))
    except urllib.error.HTTPError as e:
        if e.code == 409:  # a webhook, or another program, reads this bot's messages
            raise ValueError(tr(f"bot @{name} đang được một hệ thống khác dùng (webhook): nhập ID nhóm/chat vào ô bên cạnh",
                                f"the bot @{name} is used by another system (webhook): type the group/chat ID in the field next to it"))
        raise ValueError(tr(f"Telegram báo lỗi: {e}", f"Telegram error: {e}"))
    except OSError as e:
        raise ValueError(tr(f"không kết nối được Telegram: {e}", f"cannot reach Telegram: {e}"))
    chats = [u[kind]["chat"] for u in updates for kind in CHAT_SOURCES if isinstance(u.get(kind), dict) and u[kind].get("chat")]
    if not chats:
        raise ValueError(tr(
            f"bot @{name} chưa nhận được tin nào. Chat riêng: nhắn cho bot một tin. Nhóm: thêm bot vào nhóm rồi gõ "
            f"/start@{name} trong nhóm, hoặc nhập ID nhóm (dạng -100…) vào ô ID. Sau đó bấm Kết nối lại.",
            f"the bot @{name} has not received anything. Private chat: send it a message. Group: add it to the group and "
            f"type /start@{name} there, or type the group ID (like -100…) in the ID field. Then press Connect again."))
    chat = chats[-1]
    return name, chat["id"], _chat_name(chat)


# ---------------------------------------------------------------- pictures

def _warning_icon(size, color):
    img = Image.new("RGBA", (size * 4, size * 4), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size * 4
    d.polygon([(s / 2, s * 0.06), (s * 0.97, s * 0.92), (s * 0.03, s * 0.92)], fill=color)
    d.rounded_rectangle([s * 0.455, s * 0.33, s * 0.545, s * 0.66], radius=s * 0.04, fill=(127, 29, 29))
    d.ellipse([s * 0.445, s * 0.72, s * 0.555, s * 0.83], fill=(127, 29, 29))
    return img.resize((size, size), Image.LANCZOS)


def alert_image(alerts, host, now=None):
    """Red screen listing the active alerts"""
    now = now or datetime.datetime.now()
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):  # dark red at the top, brighter at the bottom
        t = y / H
        d.line([(0, y), (W, y)], fill=(int(127 + 58 * t), int(29 - 1 * t), int(29 - 1 * t)))
    icon = _warning_icon(64, (254, 242, 242))
    img.paste(icon, (20, 20), icon)
    d.text((100, 38), tr("CẢNH BÁO", "WARNING"), font=font("roboto/Roboto-Bold.ttf", 34), fill=(255, 255, 255), anchor="lm")
    d.text((100, 72), host, font=fit(d, host, "roboto/Roboto-Medium.ttf", 16, W - 120), fill=(254, 202, 202), anchor="lm")
    y = 116
    for alert in alerts[:5]:
        d.ellipse([22, y - 5, 32, y + 5], fill=(254, 242, 242))
        d.text((42, y), alert, font=fit(d, alert, "roboto/Roboto-Medium.ttf", 19, W - 60, 12), fill=(255, 255, 255), anchor="lm")
        y += 36
    footer = tr(f"{now:%H:%M} · Chi tiết: igam3-screen alerts", f"{now:%H:%M} · Details: igam3-screen alerts")
    d.text((20, H - 20), footer, font=font("roboto/Roboto-Regular.ttf", 13), fill=(254, 202, 202), anchor="lm")
    return img


def shutdown_image(kind):
    """Screen shown while the system shuts down ("poweroff") or restarts ("reboot"). It stays until the computer cuts
    the power of its USB ports"""
    img = Image.new("RGB", (W, H), (12, 16, 28))
    d = ImageDraw.Draw(img)
    s = 4
    art = Image.new("RGBA", (96 * s, 96 * s), (0, 0, 0, 0))
    a = ImageDraw.Draw(art)
    if kind == "reboot":
        color = (34, 211, 238)
        a.arc([10 * s, 10 * s, 86 * s, 86 * s], start=40, end=320, fill=color, width=9 * s)
        a.polygon([(70 * s, 4 * s), (90 * s, 30 * s), (60 * s, 32 * s)], fill=color)
        title = tr("Đang khởi động lại…", "Restarting…")
        lines = [tr("Màn hình sẽ bật lại sau ít phút.", "The screen comes back in a minute or two.")]
    else:
        color = (251, 191, 36)
        a.arc([10 * s, 14 * s, 86 * s, 90 * s], start=-60, end=240, fill=color, width=9 * s)
        a.line([(48 * s, 4 * s), (48 * s, 48 * s)], fill=color, width=9 * s)
        title = tr("Đang tắt máy…", "Shutting down…")
        lines = [tr("Chưa rút điện nhé. Rút khi màn này tối hẳn", "Do not unplug yet. Unplug once this screen"),
                 tr("hoặc đèn nguồn trên máy đã tắt.", "goes dark or the power light is off.")]
    art = art.resize((96, 96), Image.LANCZOS)
    img.paste(art, (W // 2 - 48, 40), art)
    d.text((W // 2, 170), title, font=font("roboto/Roboto-Bold.ttf", 30), fill=(229, 231, 235), anchor="mm")
    for i, line in enumerate(lines):
        d.text((W // 2, 214 + i * 26), line, font=fit(d, line, "roboto/Roboto-Regular.ttf", 18, W - 40),
               fill=(148, 163, 184), anchor="mm")
    return img


def finish(lcd, control=None):
    """End of the main screen: the "shutting down" screen if the system goes down, else the screen turns off"""
    kind = shutdown_kind()
    if not kind:
        with SERIAL:
            lcd.ScreenOff()
        return
    if control:
        control.overlay = True  # nothing else may draw over it
        control.night = None
        control.light()
        control.draw_direct(lcd, shutdown_image(kind))
    else:
        lcd.DisplayPILImage(shutdown_image(kind))


# ---------------------------------------------------------------- monitor

def in_night(now, start, end):
    """now: datetime.time, start/end "HH:MM" (the night can go past midnight)"""
    def minutes(text):
        hours, _, mins = str(text).partition(":")
        return int(hours) * 60 + int(mins or 0)
    t, a, b = now.hour * 60 + now.minute, minutes(start), minutes(end)
    return a <= t < b if a < b else (t >= a or t < b) if a != b else False


class Monitor(threading.Thread):
    def __init__(self, control, load_settings, telegram, runtime_dir, host):
        super().__init__(daemon=True, name="igam3-monitor")
        self.control = control
        self.load_settings = load_settings
        self.telegram = telegram
        self.runtime = Path(runtime_dir)
        self.host = host
        self.found = {}  # problems of the last check
        self.active = {}  # key -> {"text", "since"}: what the red screen lists
        self.network_failures, self.network_down_since = 0, None
        self.shown_at, self.hidden_at, self.new_alert, self.changed = 0.0, -PAUSE_S, False, False
        self.test_until = 0.0

    def run(self):
        time.sleep(START_DELAY_S)
        last_check = -CHECK_S
        while True:
            try:
                settings = self.load_settings()
                self.night_step(merged(settings, "night"))
                now = time.monotonic()
                refresh = False
                test = self.runtime / "alert-test"
                if test.exists():  # "igam3-screen alerts --test" or the web panel
                    test.unlink(missing_ok=True)
                    self.test_until = now + SHOW_S
                    self.telegram.send(tr(f"🔔 {self.host}: cảnh báo thử của igam3-screen", f"🔔 {self.host}: igam3-screen test alert"))
                    refresh = True
                if self.test_until and now >= self.test_until:
                    self.test_until = 0.0
                    refresh = True
                if now - last_check >= CHECK_S:
                    self.found = self.check(merged(settings, "alerts"))
                    last_check = now
                    refresh = True
                if refresh:
                    found = dict(self.found)
                    if self.test_until:
                        found["test"] = tr("Cảnh báo thử: màn và Telegram hoạt động tốt", "Test alert: the screen and Telegram work")
                    self.update(found)
                self.cycle(now)
            except Exception as e:  # never stop watching because of one bad reading
                print(f"monitor: {type(e).__name__}: {e}", flush=True)
            time.sleep(1)

    def night_step(self, night):
        if self.control.get_lcd() is None:
            return
        state = None
        if night["enabled"] and in_night(datetime.datetime.now().time(), night["start"], night["end"]):
            state = "off" if night["action"] == "off" else "dim"
        self.control.set_night(state, int(night["brightness"]))

    def check(self, cfg):
        found = {}
        if not cfg["enabled"]:
            return found
        limit = int(cfg["temperature"] or 0)
        temperature = cpu_temperature() if limit else None
        if temperature is not None and (temperature >= limit or ("temperature" in self.active and temperature >= limit - 5)):
            found["temperature"] = tr(f"Nhiệt độ CPU {temperature:.0f}°C (ngưỡng {limit}°C)",
                                      f"CPU temperature {temperature:.0f}°C (limit {limit}°C)")
        limit = int(cfg["disk"] or 0)
        if limit:
            used = psutil.disk_usage(SYSTEM_DISK).percent
            if used >= limit or ("disk" in self.active and used >= limit - 2):
                found["disk"] = tr(f"Ổ đĩa đã dùng {used:.0f}% (ngưỡng {limit}%)", f"Disk {used:.0f}% full (limit {limit}%)")
        if cfg["network"]:
            if internet_ok():
                self.network_failures = 0
                if "network" not in self.active:
                    self.network_down_since = None
            else:
                self.network_failures += 1
                self.network_down_since = self.network_down_since or datetime.datetime.now()
            if self.network_failures >= NETWORK_FAILURES:
                found["network"] = tr(f"Mất mạng từ {self.network_down_since:%H:%M}",
                                      f"No network since {self.network_down_since:%H:%M}")
        for unit in cfg["services"] or []:
            state = unit_state(unit)
            if state not in RUNNING_STATES:
                found[f"service:{unit}"] = tr(f"Dịch vụ {unit} không chạy ({state})", f"Service {unit} is not running ({state})")
        return found

    def update(self, found):
        stamp = datetime.datetime.now()
        for key, text in found.items():
            if key not in self.active:
                self.active[key] = {"text": text, "since": stamp.isoformat(timespec="seconds")}
                self.new_alert = self.changed = True
                if key not in ("network", "test"):  # without network the message would wait for it anyway
                    self.telegram.send(f"⚠️ {self.host}: {text}")
            elif self.active[key]["text"] != text:
                self.active[key]["text"] = text
                self.changed = True
        for key in [k for k in self.active if k not in found]:
            alert = self.active.pop(key)
            self.changed = True
            if key == "network":
                since = self.network_down_since or stamp
                minutes = max(1, round((stamp - since).total_seconds() / 60))
                self.telegram.send(tr(f"✅ {self.host}: có mạng lại (mất {minutes} phút, từ {since:%H:%M})",
                                      f"✅ {self.host}: network back (down {minutes} min, since {since:%H:%M})"))
                self.network_down_since = None
            elif key != "test":
                self.telegram.send(tr(f"✅ {self.host}: hết cảnh báo — {alert['text']}", f"✅ {self.host}: alert over — {alert['text']}"))
        try:
            self.runtime.mkdir(parents=True, exist_ok=True)
            (self.runtime / "alerts.json").write_text(json.dumps({
                "checked": stamp.isoformat(timespec="seconds"),
                "active": [{"key": k, **v} for k, v in self.active.items()]}, ensure_ascii=False), encoding="utf8")
        except OSError:
            pass

    def cycle(self, now):
        """The red screen: at once for a new problem, then 15 s every minute while problems last"""
        control = self.control
        if control.get_lcd() is None or control.draw_direct is None:
            return
        if not self.active:
            if control.overlay:
                control.hide()
                self.hidden_at = now
            self.new_alert = self.changed = False
            return
        texts = [alert["text"] for alert in self.active.values()]
        if control.overlay:
            if self.changed:
                control.draw_direct(control.get_lcd(), alert_image(texts, self.host))
                if self.new_alert:
                    self.shown_at = now
            elif now - self.shown_at >= SHOW_S:
                control.hide()
                self.hidden_at = now
        elif self.new_alert or now - self.hidden_at >= PAUSE_S:
            control.show(alert_image(texts, self.host))
            self.shown_at = now
        self.new_alert = self.changed = False
