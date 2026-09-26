#!/usr/bin/env python3
# igam3-screen: manager of the built-in 3.5" screen (Turing Smart Screen / TURZX rev. A, USB 1a86:5722) of the
# iGam3 M1. It wraps turing-smart-screen-python (app/), runs the main screen in the background ("run") and serves
# the web panel (tools/web_panel.py). Linux: systemd user service. Windows (experimental): tools/platform_support.py
# Messages are Vietnamese or English (tools/i18n.py).

import argparse
import getpass
import hashlib
import json
import os
import runpy
import secrets
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import i18n
from i18n import tr
from platform_support import (WINDOWS, SystemdUserService, WindowsBackgroundTask, background_kwargs,
                              create_shortcut, matching_processes, runtime_dir, start_menu_dir, stop_processes,
                              venv_python, watch_stop_file)

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
APP = ROOT / "app"
VENV_PYTHON = venv_python(ROOT)
VENV_PYTHONW = venv_python(ROOT, windowless=True)  # same as VENV_PYTHON on Linux
CONFIG = APP / "config.yaml"
THEMES = APP / "res" / "themes"
FONTS = APP / "res" / "fonts"
ICON = APP / "res" / "icons" / "monitor-icon-17865" / "icon.ico"
IGAM3_THEME = THEMES / "iGam3"
THEME_CUSTOM = IGAM3_THEME / "custom.yaml"
SETTINGS = ROOT / "settings.yaml"
WEB_CONFIG = ROOT / "web.yaml"
IMAGES = ROOT / "images"
RUNTIME = runtime_dir()
PREVIEW = RUNTIME / "screen.png"
SERVICE = "igam3-screen.service"
WEB_SERVICE = "igam3-screen-web.service"
WEB_PORT = 8686
UNIT_DIR = Path.home() / ".config" / "systemd" / "user"
BIN_LINK = Path.home() / ".local" / "bin" / "igam3-screen"
DESKTOP_FILE = Path.home() / ".local" / "share" / "applications" / "igam3-screen.desktop"
USB_VID, USB_PID = 0x1A86, 0x5722
MODES = {"stats": ("bảng thông số", "dashboard"), "image": ("ảnh cố định", "picture"),
         "console": ("dòng lệnh", "console"), "qr": ("mã QR", "QR code")}
SHORTCUT_SCHEMA = "org.gnome.settings-daemon.plugins.media-keys"
SHORTCUT_PATH = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/igam3-qr/"
SHORTCUT_KEYS = "<Control><Alt>q"
CONSOLE_VCS = Path("/dev/vcsa3")
SETUP_ROOT = ROOT / "setup-root.sh"

# The screen program and the web panel for the local network, as background services of this platform
if WINDOWS:
    SCREEN = WindowsBackgroundTask("screen", "iGam3 Screen", VENV_PYTHONW, TOOLS / "igam3_screen.py", ["run"], APP)
    WEB = WindowsBackgroundTask("web", "iGam3 Screen web", VENV_PYTHONW, TOOLS / "web_panel.py", ["--lan"], ROOT)
else:
    SCREEN = SystemdUserService(SERVICE)
    WEB = SystemdUserService(WEB_SERVICE)

sys.path.insert(0, str(APP))  # library.* of turing-smart-screen-python


def die(msg):
    print(tr("Lỗi: ", "Error: ") + msg, file=sys.stderr)
    sys.exit(1)


def mode_name(mode):
    return tr(*MODES.get(mode, (mode, mode)))


def on_off(value):
    return tr("bật", "on") if value else tr("tắt", "off")


def yes_no(value):
    return tr("có", "yes") if value else tr("không", "no")


def orientation_name(orientation):
    return {"landscape": tr("ngang", "landscape"), "portrait": tr("dọc", "portrait")}.get(orientation, "?")


def primary_ipv4():
    from library.sensors.sensors_custom import primary_ipv4 as ip
    return ip()


# ---------------------------------------------------------------- config.yaml / themes

def load_config():
    from ruamel.yaml import YAML  # round-trip: keeps the comments of config.yaml
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.explicit_start = True  # config.yaml starts with '---'
    with open(CONFIG, encoding="utf8") as f:
        return yaml, yaml.load(f)


def save_config(yaml, data):
    with open(CONFIG, "w", encoding="utf8") as f:
        yaml.dump(data, f)


def load_yaml_dict(path, defaults):
    import yaml
    data = dict(defaults)
    if path.is_file():
        with open(path, encoding="utf8") as f:
            data.update(yaml.safe_load(f) or {})
    return data


def save_yaml_dict(path, data, header):
    import yaml
    with open(path, "w", encoding="utf8") as f:
        f.write(header)
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)


def theme_info(name):
    """(size, orientation) of a theme, or None if it does not exist"""
    import yaml
    path = THEMES / name / "theme.yaml"
    if not path.is_file():
        return None
    try:
        with open(path, encoding="utf8") as f:
            display = (yaml.safe_load(f) or {}).get("display") or {}
    except yaml.YAMLError:
        return None
    return str(display.get("DISPLAY_SIZE", '3.5"')), str(display.get("DISPLAY_ORIENTATION", "portrait"))


def themes_35():
    result = []
    for d in sorted(THEMES.iterdir(), key=lambda p: p.name.lower()):
        info = theme_info(d.name) if d.is_dir() else None
        if info and info[0] == '3.5"':
            result.append({"name": d.name, "orientation": info[1]})
    return result


# What the service shows (stats dashboard, fixed picture, text console or QR code) and the language
def load_settings():
    return load_yaml_dict(SETTINGS, {"mode": "stats", "image": "", "fill": False, "language": "auto"})


def save_settings(settings):
    save_yaml_dict(SETTINGS, settings, "# Main screen: stats, image, console or qr - language: auto, vi or en\n"
                                       "# Change with: igam3-screen mode ... / igam3-screen language ... (or the web panel)\n")


# Header text, background photo and blocks of the iGam3 theme: make_theme.py owns their format
def theme_generator():
    if str(IGAM3_THEME) not in sys.path:
        sys.path.insert(0, str(IGAM3_THEME))
    import make_theme
    return make_theme


def load_theme_custom():
    return theme_generator().load_custom()


def save_theme_custom(custom):
    save_yaml_dict(THEME_CUSTOM, custom, "# iGam3 theme settings. Change with: igam3-screen title / background / blocks\n")
    make_theme = theme_generator()
    layout = make_theme.compute_layout(custom["blocks"])
    make_theme.draw_background(custom, layout, i18n.LANG)
    make_theme.write_theme_yaml(custom, layout, i18n.LANG)


def apply_dashboard_change():
    _, cfg = load_config()
    if str(cfg["config"]["THEME"]) != IGAM3_THEME.name:
        print(tr(f"Lưu ý: đang dùng theme '{cfg['config']['THEME']}'. Thay đổi này chỉ áp dụng cho theme iGam3 "
                 f"(chọn lại: igam3-screen theme {IGAM3_THEME.name})",
                 f"Note: the current theme is '{cfg['config']['THEME']}'. This change only applies to the iGam3 theme "
                 f"(switch back: igam3-screen theme {IGAM3_THEME.name})"))
    elif load_settings()["mode"] != "stats":
        print(tr("Màn chính đang không phải bảng thông số. Xem bảng thông số: igam3-screen mode stats",
                 "The main screen is not the dashboard. Show the dashboard: igam3-screen mode stats"))
    else:
        restart_if_running()


# Password of the web panel: only a salted hash is stored
def set_web_password(password):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000).hex()
    WEB_CONFIG.touch(mode=0o600)
    save_yaml_dict(WEB_CONFIG, {"salt": salt, "hash": digest}, "# Web panel password (hashed). Change: igam3-screen web --password\n")
    os.chmod(WEB_CONFIG, 0o600)


# ---------------------------------------------------------------- background services

def systemctl_user(*args):
    return subprocess.run(["systemctl", "--user", *args]).returncode


def screen_running():
    return SCREEN.state() in ("active", "activating")


def restart_if_running():
    if screen_running():
        print(tr("Khởi động lại màn hình để áp dụng...", "Restarting the screen to apply..."))
        SCREEN.restart()
    else:
        print(tr("Màn hình đang tắt: thay đổi sẽ có hiệu lực khi chạy 'igam3-screen start'.",
                 "The screen is off: the change applies at the next 'igam3-screen start'."))


def take_over_screen():
    # Only one program can talk to the serial port: stop the service first
    if screen_running():
        print(tr("Tạm dừng màn hình chính (chạy 'igam3-screen start' để bật lại)...",
                 "Pausing the main screen ('igam3-screen start' brings it back)..."))
        SCREEN.stop()
        time.sleep(1)


# ---------------------------------------------------------------- direct access to the screen

def find_port():
    from serial.tools.list_ports import comports
    for port in comports():
        if port.vid == USB_VID and port.pid == USB_PID:
            return port.device
    return None


def require_port():
    port = find_port()
    if not port:
        where = "Device Manager > Ports (COM & LPT)" if WINDOWS else tr("lệnh: lsusb", "the command: lsusb")
        die(tr(f'không thấy màn hình USB 1a86:5722 (Turing/TURZX 3.5"). Kiểm tra bằng {where}',
               f'no USB screen 1a86:5722 found (Turing/TURZX 3.5"). Check with {where}'))
    if not WINDOWS and not os.access(port, os.R_OK | os.W_OK):
        die(tr(f"chưa có quyền mở {port}. Chạy một lần: sudo {SETUP_ROOT}",
               f"no permission to open {port}. Run once: sudo {SETUP_ROOT}"))
    return port


def open_lcd(orientation=None, init=True):
    port = require_port()
    if WINDOWS:
        import serial
        try:
            serial.Serial(port).close()
        except serial.SerialException:
            die(tr(f"{port} đang bị chương trình khác dùng. Tắt app TURZX (và bỏ nó khỏi Startup) rồi thử lại.",
                   f"{port} is used by another program. Close the TURZX app (and remove it from Startup), then retry."))
    os.chdir(APP)  # library/log.py writes log.log into the current directory
    from library.lcd.lcd_comm import Orientation
    from library.lcd.lcd_comm_rev_a import LcdCommRevA

    lcd = LcdCommRevA(com_port=port)
    lcd.InitializeComm()
    if init:
        _, cfg = load_config()
        info = theme_info(str(cfg["config"]["THEME"])) or ('3.5"', "landscape")
        base = orientation or info[1]
        reverse = bool(cfg["display"].get("DISPLAY_REVERSE", False))
        if base == "portrait":
            lcd_orientation = Orientation.REVERSE_PORTRAIT if reverse else Orientation.PORTRAIT
        else:
            lcd_orientation = Orientation.REVERSE_LANDSCAPE if reverse else Orientation.LANDSCAPE
        lcd.ScreenOn()
        lcd.SetBrightness(int(cfg["display"].get("BRIGHTNESS", 30)))
        lcd.SetOrientation(lcd_orientation)
    return lcd


class ScreenMirror:
    """Copy of what is on the screen, saved as PNG (at most once per second) for the live view of the web panel"""

    def __init__(self, path):
        self.path = path
        self.canvas = None
        self.dirty = False
        self.lock = threading.Lock()
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        threading.Thread(target=self._save_loop, daemon=True).start()

    def paste(self, image, x, y, size):
        with self.lock:
            if self.canvas is None or self.canvas.size != size:
                from PIL import Image
                self.canvas = Image.new("RGB", size)
            self.canvas.paste(image.convert("RGB"), (x, y))
            self.dirty = True

    def flush(self):
        with self.lock:
            if not self.dirty:
                return
            image, self.dirty = self.canvas.copy(), False
        tmp = self.path.with_name(self.path.name + ".tmp")
        image.save(tmp, "PNG")
        os.replace(tmp, self.path)

    def _save_loop(self):
        while True:
            time.sleep(1)
            self.flush()


def install_mirror():
    # Every drawing goes through DisplayPILImage: stats, pictures and console all update the live view
    from library.lcd.lcd_comm_rev_a import LcdCommRevA
    mirror = ScreenMirror(PREVIEW)
    original = LcdCommRevA.DisplayPILImage

    def display_and_mirror(self, image, x=0, y=0, image_width=0, image_height=0):
        mirror.paste(image, x, y, (self.get_width(), self.get_height()))
        return original(self, image, x, y, image_width, image_height)

    LcdCommRevA.DisplayPILImage = display_and_mirror
    return mirror


def fit_image(img, size, fill):
    from PIL import Image, ImageOps
    img = ImageOps.exif_transpose(img).convert("RGB")
    if fill:
        return ImageOps.fit(img, size, Image.LANCZOS)  # crop to fill the whole screen
    img = ImageOps.contain(img, size, Image.LANCZOS)  # keep the whole picture, black borders
    canvas = Image.new("RGB", size, (0, 0, 0))
    canvas.paste(img, ((size[0] - img.width) // 2, (size[1] - img.height) // 2))
    return canvas


def checked_image_path(file):
    from PIL import Image
    path = Path(file).expanduser().resolve()
    if not path.is_file():
        die(tr(f"không thấy file {path}", f"file not found: {path}"))
    try:
        with Image.open(path) as img:
            img.verify()
    except Exception as e:
        die(tr(f"không mở được ảnh {path.name}: {e}", f"cannot open the picture {path.name}: {e}"))
    return path


def load_frames(path, size, fill):
    """[(picture sized for the screen, duration in ms)]: one frame for a still picture, several for an animated GIF"""
    from PIL import Image, ImageSequence
    with Image.open(path) as src:
        return [(fit_image(frame, size, fill), frame.info.get("duration", 100) or 100)
                for frame in ImageSequence.Iterator(src)]


def stop_on_signals():
    # Ctrl+C / systemctl stop only raise a flag: a frame is never cut in the middle of its serial transfer,
    # otherwise the screen would read the next command as pixel data
    import signal
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    return stop


def service_stop_event():
    """Stop flag of the background screen program: signals on Linux, the stop file of 'igam3-screen stop' on Windows"""
    stop = stop_on_signals()
    if WINDOWS:
        watch_stop_file("screen", stop.set)
    return stop


def stop_stats_now():
    """What main.py does on SIGTERM (screen off, send what is queued, exit), for 'igam3-screen stop' on Windows"""
    import library.scheduler as scheduler
    from library.display import display
    display.turn_off()
    scheduler.STOPPING = True
    deadline = time.monotonic() + 5
    while not scheduler.is_queue_empty() and time.monotonic() < deadline:
        time.sleep(0.1)
    os._exit(0)


def play(lcd, frames, stop, loop=True, refresh_s=None):
    """Show a still picture (re-sent every refresh_s seconds if given) or loop an animation, until stop is set"""
    if len(frames) == 1:
        lcd.DisplayPILImage(frames[0][0])
        while refresh_s and not stop.wait(refresh_s):
            lcd.DisplayPILImage(frames[0][0])
        return
    while not stop.is_set():
        for frame, duration in frames:
            t0 = time.monotonic()
            lcd.DisplayPILImage(frame)
            if stop.wait(max(0.0, duration / 1000 - (time.monotonic() - t0))):
                return
        if not loop:
            return


def show_temporarily(path, fill, orientation=None, once=False):
    require_port()
    take_over_screen()
    stop = stop_on_signals()
    mirror = install_mirror()
    lcd = open_lcd(orientation)
    frames = load_frames(path, (lcd.get_width(), lcd.get_height()), fill)
    if len(frames) > 1:
        print(tr(f"Đang phát ảnh động {path.name}: {len(frames)} khung hình. Ctrl+C để dừng.",
                 f"Playing the animation {path.name}: {len(frames)} frames. Ctrl+C to stop."))
    play(lcd, frames, stop, loop=not once)
    mirror.flush()
    print(tr(f"Đã hiển thị {path.name}. Quay lại màn chính: igam3-screen start",
             f"Showing {path.name}. Back to the main screen: igam3-screen start"))


def keep_image(path, fill):
    """Make a picture the main screen. It is copied into images/, so moving or deleting the original is fine"""
    data = path.read_bytes()
    IMAGES.mkdir(exist_ok=True)
    for old in IMAGES.glob("main.*"):
        old.unlink()
    dest = IMAGES / f"main{path.suffix.lower()}"
    dest.write_bytes(data)
    settings = load_settings()
    settings.update({"mode": "image", "image": str(dest), "fill": fill})
    save_settings(settings)
    print(tr(f"Màn chính: ảnh {path.name}, giữ nguyên cả khi khởi động lại. Quay lại bảng thông số: igam3-screen mode stats",
             f"Main screen: picture {path.name}, kept after a restart. Back to the dashboard: igam3-screen mode stats"))
    SCREEN.restart()


def test_pattern(w, h):
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (w, h), (12, 16, 28))
    d = ImageDraw.Draw(img)
    big = ImageFont.truetype(str(FONTS / "jetbrains-mono/JetBrainsMono-Bold.ttf"), 26)
    small = ImageFont.truetype(str(FONTS / "roboto/Roboto-Bold.ttf"), 15)
    d.rectangle([0, 0, w - 1, h - 1], outline=(34, 211, 238), width=3)
    d.rectangle([3, 3, w - 4, 16], fill=(251, 191, 36))  # yellow strip = top edge
    d.polygon([(w // 2, 40), (w // 2 - 40, 100), (w // 2 + 40, 100)], fill=(52, 211, 153))
    d.rectangle([w // 2 - 14, 100, w // 2 + 14, 150], fill=(52, 211, 153))
    d.text((w // 2, 175), tr("TRÊN ↑", "TOP ↑"), font=big, fill=(255, 255, 255), anchor="mm")
    d.text((w // 2, 210), f"{w} x {h}", font=small, fill=(148, 163, 184), anchor="mm")
    for label, xy, anchor in (("1", (12, 24), "lt"), ("2", (w - 12, 24), "rt"),
                              ("3", (12, h - 12), "lb"), ("4", (w - 12, h - 12), "rb")):
        d.text(xy, label, font=big, fill=(251, 146, 60), anchor=anchor)
    return img


def status_dict():
    port = find_port()
    _, cfg = load_config()
    theme = str(cfg["config"]["THEME"])
    info = theme_info(theme)
    settings = load_settings()
    custom = load_theme_custom()
    blocks = theme_generator().block_labels(i18n.LANG)
    return {
        "platform": "windows" if WINDOWS else "linux",
        "language": i18n.LANG,
        "language_setting": i18n.language_setting(),
        "device": {"port": port, "access": bool(port and (WINDOWS or os.access(port, os.R_OK | os.W_OK)))},
        "service": {"state": SCREEN.state(), "autostart": SCREEN.autostart()},
        "mode": settings["mode"],
        "image": Path(str(settings["image"])).name if settings["image"] else "",
        "fill": bool(settings["fill"]),
        "theme": theme,
        "orientation": info[1] if info else "",
        "themes": themes_35(),
        "title": custom["title"],
        "tag": custom["tag"],
        "background": custom["background"],
        "blocks": [{"key": k, "label": label, "on": custom["blocks"][k]} for k, label in blocks.items()],
        "brightness": int(cfg["display"].get("BRIGHTNESS", 30)),
        "reverse": bool(cfg["display"].get("DISPLAY_REVERSE", False)),
        "console": {"allowed": not WINDOWS and os.access(CONSOLE_VCS, os.R_OK), "active_vt": _active_vt(),
                    "setup": str(SETUP_ROOT)},
        "ip": primary_ipv4(),
        "hostname": socket.gethostname(),
        "web": {"port": WEB_PORT, "password_set": WEB_CONFIG.is_file(), "lan": WEB.state() == "active"},
    }


def web_listening():
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", WEB_PORT)) == 0


def qr_screen_state():
    """What the QR screen shows: (ip, web panel open to the network, title); redraw when it changes"""
    return primary_ipv4(), WEB.state() == "active", load_theme_custom()["title"] or "iGam3 M1"


def qr_screen_image(state):
    from qr_screen import make_qr_screen
    ip, lan_on, title = state
    return make_qr_screen(ip, WEB_PORT, lan_on, title)


def web_qr_card():
    """Small QR code of the web panel for the console waiting screen, None if the panel is not open to the network"""
    ip = primary_ipv4()
    if not ip or WEB.state() != "active":
        return None
    from qr_screen import panel_url, qr_card
    url = panel_url(ip, WEB_PORT)
    return (*qr_card(url, 150), url)


LAN_UNIT = f"""[Unit]
Description=iGam3 M1 built-in screen - web control panel for the local network (port {WEB_PORT})
Documentation=file://{ROOT}/README.md

[Service]
Type=simple
WorkingDirectory={ROOT}
ExecStart={VENV_PYTHON} {TOOLS / "web_panel.py"} --lan
Environment=PYTHONUNBUFFERED=1
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
"""


def _active_vt():
    try:
        return Path("/sys/class/tty/tty0/active").read_text().strip()
    except OSError:
        return ""


# ---------------------------------------------------------------- commands

def cmd_status(args):
    st = status_dict()
    if args.json:
        print(json.dumps(st, ensure_ascii=False))
        return
    dev = st["device"]
    if not dev["port"]:
        screen = tr("KHÔNG THẤY (USB 1a86:5722)", "NOT FOUND (USB 1a86:5722)")
    elif dev["access"]:
        screen = tr(f"{dev['port']} (có quyền truy cập)", f"{dev['port']} (accessible)")
    else:
        screen = tr(f"{dev['port']} (CHƯA CÓ QUYỀN: sudo {SETUP_ROOT})", f"{dev['port']} (NO PERMISSION: sudo {SETUP_ROOT})")
    main = mode_name(st["mode"]) + (f" ({st['image']})" if st["mode"] == "image" else "")
    language = tr("Tiếng Việt", "English") + (tr(" (tự theo máy)", " (follows the system)")
                                              if st["language_setting"] == "auto" else "")
    lines = [
        (tr("Màn hình", "Screen"), screen),
        (tr("Dịch vụ", "Service"), f"{st['service']['state']} ({tr('tự chạy khi khởi động', 'start at boot')}: "
                                   f"{yes_no(st['service']['autostart'])})"),
        (tr("Màn chính", "Main screen"), main),
        ("Theme", f"{st['theme']} ({orientation_name(st['orientation'])})"),
    ]
    if st["theme"] == IGAM3_THEME.name:
        lines.append((tr("Tiêu đề", "Title"), f"\"{st['title']}\"  {tr('nhãn', 'tag')} \"{st['tag']}\"  "
                      f"{tr('ảnh nền', 'background')}: {st['background'] or tr('mặc định', 'default')}"))
        lines.append((tr("Các khối", "Blocks"), ", ".join(f"{b['label']} {on_off(b['on'])}" for b in st["blocks"])))
    lines.append((tr("Độ sáng", "Brightness"), f"{st['brightness']}%   {tr('Xoay 180°', 'Rotated 180°')}: "
                  f"{yes_no(st['reverse'])}"))
    lines.append((tr("Ngôn ngữ", "Language"), language))
    if st["web"]["lan"]:
        web = tr(f"http://{st['ip']}:{WEB_PORT} (mở cho mạng LAN, có mật khẩu)",
                 f"http://{st['ip']}:{WEB_PORT} (open to the local network, with a password)")
    else:
        web = tr("igam3-screen panel (chỉ trên máy này; mở cho mạng LAN: igam3-screen web --lan on)",
                 "igam3-screen panel (this computer only; open to the local network: igam3-screen web --lan on)")
    lines.append((tr("Giao diện", "Web panel"), web))
    width = max(len(name) for name, _ in lines)
    for name, value in lines:
        print(f"{name:<{width}} : {value}")


def cmd_start(_):
    sys.exit(SCREEN.start())


def cmd_stop(_):
    sys.exit(SCREEN.stop())


def cmd_restart(_):
    sys.exit(SCREEN.restart())


def cmd_enable(_):
    sys.exit(SCREEN.set_autostart(True, now=True))


def cmd_disable(_):
    sys.exit(SCREEN.set_autostart(False, now=True))


def cmd_autostart(args):
    code = SCREEN.set_autostart(args.state == "on")
    print(tr("Tự bật màn hình khi khởi động máy: ", "Start the screen at boot: ") + yes_no(args.state == "on"))
    sys.exit(code)


def cmd_mode(args):
    if args.mode == "console" and WINDOWS:
        die(tr("chế độ Dòng lệnh chỉ có trên Linux", "the console mode is Linux only"))
    settings = load_settings()
    if args.mode == "image" and not Path(str(settings["image"])).is_file():
        die(tr("chưa có ảnh nào: dùng 'igam3-screen image <ảnh> --keep' hoặc 'igam3-screen splash ... --keep'",
               "no picture yet: use 'igam3-screen image <picture> --keep' or 'igam3-screen splash ... --keep'"))
    settings["mode"] = args.mode
    save_settings(settings)
    print(tr("Màn chính: ", "Main screen: ") + mode_name(args.mode))
    if args.mode == "console":
        if not os.access(CONSOLE_VCS, os.R_OK):
            print(tr(f"Lưu ý: chưa có quyền đọc dòng lệnh. Chạy một lần: sudo {SETUP_ROOT}",
                     f"Note: no permission to read the console yet. Run once: sudo {SETUP_ROOT}"))
        print(tr("Cắm bàn phím USB, bấm Ctrl+Alt+F3 để đăng nhập và gõ lệnh trên màn nhỏ.",
                 "Plug in a USB keyboard and press Ctrl+Alt+F3 to log in and type commands on the small screen."))
    if args.mode == "qr" and WEB.state() != "active":
        print(tr("Lưu ý: giao diện chưa mở cho mạng LAN nên chưa quét được. Mở: igam3-screen web --lan on",
                 "Note: the web panel is not open to the local network, so the code cannot be used yet. "
                 "Open it: igam3-screen web --lan on"))
    SCREEN.restart()


def cmd_language(args):
    settings = load_settings()
    settings["language"] = args.language
    save_settings(settings)
    os.environ.pop("IGAM3_LANG", None)
    i18n.refresh()
    print(tr("Ngôn ngữ: Tiếng Việt", "Language: English") +
          (tr(" (tự theo máy)", " (follows the system)") if args.language == "auto" else ""))
    save_theme_custom(load_theme_custom())  # dashboard labels and date format
    restart_if_running()


def cmd_title(args):
    custom = load_theme_custom()
    custom["title"] = args.title
    if args.tag is not None:
        custom["tag"] = args.tag
    save_theme_custom(custom)
    print(tr(f"Tiêu đề bảng thông số: \"{custom['title']}\"", f"Dashboard title: \"{custom['title']}\"") +
          (tr(f", nhãn \"{custom['tag']}\"", f", tag \"{custom['tag']}\"") if custom["tag"] else tr(", không có nhãn", ", no tag")))
    apply_dashboard_change()


def cmd_background(args):
    if args.none == bool(args.file):
        die(tr("cần đúng một trong hai: đường dẫn ảnh, hoặc --none để bỏ ảnh nền",
               "give either a picture, or --none to remove the background"))
    path = checked_image_path(args.file) if args.file else None
    data = path.read_bytes() if path else None
    custom = load_theme_custom()
    for old in IGAM3_THEME.glob("photo.*"):
        old.unlink()
    custom["background"] = ""
    if path:
        dest = IGAM3_THEME / f"photo{path.suffix.lower()}"
        dest.write_bytes(data)
        custom["background"] = dest.name
    save_theme_custom(custom)
    print(tr("Ảnh nền bảng thông số: ", "Dashboard background: ") +
          (path.name if path else tr("mặc định (nền tối)", "default (dark)")))
    apply_dashboard_change()


def cmd_blocks(args):
    blocks = theme_generator().block_labels(i18n.LANG)
    custom = load_theme_custom()
    if not args.changes:
        for key, label in blocks.items():
            print(f"  {key:<9} {label:<10} {on_off(custom['blocks'][key])}")
        print(tr("Đổi: igam3-screen blocks ssd=off network=on ...", "Change: igam3-screen blocks ssd=off network=on ..."))
        return
    for change in args.changes:
        key, _, value = change.partition("=")
        if key not in blocks or value not in ("on", "off"):
            die(tr(f"'{change}' không hợp lệ: dùng dạng cpu=on hoặc ssd=off. Các khối: {', '.join(blocks)}",
                   f"'{change}' is not valid: use cpu=on or ssd=off. Blocks: {', '.join(blocks)}"))
        custom["blocks"][key] = value == "on"
    save_theme_custom(custom)
    print(tr("Các khối: ", "Blocks: ") + ", ".join(f"{label} {on_off(custom['blocks'][k])}" for k, label in blocks.items()))
    apply_dashboard_change()


def cmd_splash(args):
    from make_splash import make_splash
    photo = checked_image_path(args.photo) if args.photo else None
    logo = checked_image_path(args.logo) if args.logo else None
    image = make_splash(args.title, args.subtitle, args.footer, photo, logo)
    if args.out:
        image.save(args.out)
        print(tr("Đã tạo ảnh ", "Picture created: ") + str(args.out))
        return
    IMAGES.mkdir(exist_ok=True)
    out = IMAGES / "splash.png"
    image.save(out)
    print(tr("Đã tạo ảnh ", "Picture created: ") + str(out))
    if args.keep:
        require_port()
        keep_image(out, fill=False)
    else:
        show_temporarily(out, fill=False)


def cmd_themes(_):
    _, cfg = load_config()
    current = str(cfg["config"]["THEME"])
    print(tr('Theme cho màn 3.5" (* = đang dùng):', 'Themes for the 3.5" screen (* = in use):'))
    for theme in themes_35():
        mark = "*" if theme["name"] == current else " "
        print(f" {mark} {theme['name']:<28} {orientation_name(theme['orientation'])}")


def cmd_theme(args):
    info = theme_info(args.name)
    if not info:
        die(tr(f"không có theme '{args.name}'. Xem danh sách: igam3-screen themes",
               f"no theme '{args.name}'. List: igam3-screen themes"))
    if info[0] != '3.5"':
        die(tr(f"theme '{args.name}' dành cho màn {info[0]}, không dùng được cho màn 3.5\"",
               f"theme '{args.name}' is made for a {info[0]} screen, not the 3.5\" one"))
    yaml, cfg = load_config()
    cfg["config"]["THEME"] = args.name
    save_config(yaml, cfg)
    print(f"Theme: {args.name}")
    restart_if_running()


def cmd_brightness(args):
    if not 0 <= args.level <= 100:
        die(tr("độ sáng phải từ 0 đến 100", "brightness must be between 0 and 100"))
    yaml, cfg = load_config()
    cfg["display"]["BRIGHTNESS"] = args.level
    save_config(yaml, cfg)
    print(tr(f"Độ sáng: {args.level}%", f"Brightness: {args.level}%") +
          (tr("  (lưu ý: màn này dễ nóng khi để sáng cao)", "  (note: this screen gets hot at high brightness)")
           if args.level > 60 else ""))
    restart_if_running()


def cmd_rotate(args):
    yaml, cfg = load_config()
    reverse = args.state == "on" if args.state else not bool(cfg["display"].get("DISPLAY_REVERSE", False))
    cfg["display"]["DISPLAY_REVERSE"] = reverse
    save_config(yaml, cfg)
    print(tr("Xoay 180°: ", "Rotated 180°: ") + on_off(reverse))
    restart_if_running()


def cmd_image(args):
    path = checked_image_path(args.file)
    if args.keep:
        require_port()
        keep_image(path, args.fill)
    else:
        show_temporarily(path, args.fill, args.orientation, args.once)


def lock_once(name):
    """Open file handle holding an exclusive lock, or None if another process holds it"""
    RUNTIME.mkdir(mode=0o700, parents=True, exist_ok=True)
    handle = open(RUNTIME / f"{name}.lock", "w")
    try:
        if WINDOWS:
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def cmd_qr(args):
    """Show the QR code of the web panel for a while (Ctrl+Alt+Q), then give the screen back to the main screen"""
    lock = lock_once("qr")
    if not lock:
        print(tr("Màn nhỏ đang hiện mã QR rồi.", "The small screen already shows the QR code."))
        return
    require_port()
    was_running = screen_running()
    take_over_screen()
    stop = stop_on_signals()
    mirror = install_mirror()
    lcd = open_lcd("landscape")
    lcd.DisplayPILImage(qr_screen_image(qr_screen_state()))
    mirror.flush()
    print(tr(f"Màn nhỏ đang hiện mã QR trong {args.seconds} giây, sau đó quay lại màn hình chính.",
             f"The small screen shows the QR code for {args.seconds} seconds, then goes back to the main screen."),
          flush=True)
    stop.wait(args.seconds)
    if was_running:
        lcd.closeSerial()  # Windows lets only one program open a COM port: free it for the main screen
        SCREEN.start()
    else:
        lcd.ScreenOff()


def gsettings(*args):
    return subprocess.run(["gsettings", *args], capture_output=True, text=True)


def cmd_shortcut(args):
    """Ctrl+Alt+Q -> igam3-screen qr: GNOME custom shortcut on Linux, Start menu shortcut with a hotkey on Windows"""
    done = tr("Phím tắt Ctrl+Alt+Q (hiện mã QR trên màn nhỏ 1 phút): ",
              "Shortcut Ctrl+Alt+Q (QR code on the small screen for 1 minute): ") + on_off(args.state == "on")
    if WINDOWS:
        link = start_menu_dir() / "iGam3 Screen - QR.lnk"
        if args.state == "on":
            create_shortcut(link, VENV_PYTHONW, f'"{TOOLS / "igam3_screen.py"}" qr', ROOT, ICON, "CTRL+ALT+Q")
        else:
            link.unlink(missing_ok=True)
        print(done)
        return
    import ast
    result = gsettings("get", SHORTCUT_SCHEMA, "custom-keybindings")
    if result.returncode != 0:
        die(tr("không đọc được phím tắt GNOME: hãy chạy lệnh này trong phiên desktop",
               "cannot read the GNOME shortcuts: run this command in the desktop session"))
    raw = result.stdout.strip()
    paths = ast.literal_eval(raw.replace("@as ", "", 1)) if raw else []
    entry = f"{SHORTCUT_SCHEMA}.custom-keybinding:{SHORTCUT_PATH}"
    quote = lambda text: "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"
    if args.state == "on":
        for key, value in (("name", tr("iGam3: hiện mã QR trên màn nhỏ", "iGam3: QR code on the small screen")),
                           ("command", f"{ROOT / 'igam3-screen'} qr"), ("binding", SHORTCUT_KEYS)):
            gsettings("set", entry, key, quote(value))
        if SHORTCUT_PATH not in paths:
            paths.append(SHORTCUT_PATH)
    else:
        paths = [p for p in paths if p != SHORTCUT_PATH]
        for key in ("name", "command", "binding"):
            gsettings("reset", entry, key)
    result = gsettings("set", SHORTCUT_SCHEMA, "custom-keybindings", str(paths) if paths else "@as []")
    if result.returncode != 0:
        die(tr("không lưu được phím tắt: ", "cannot save the shortcut: ") + result.stderr.strip())
    print(done)


def cmd_test(args):
    require_port()
    take_over_screen()
    mirror = install_mirror()
    lcd = open_lcd(args.orientation)
    lcd.DisplayPILImage(test_pattern(lcd.get_width(), lcd.get_height()))
    mirror.flush()
    print(tr("Đang hiện hình kiểm tra: mũi tên xanh phải chỉ lên trên, số 1 ở góc trên bên trái.",
             "Showing the test pattern: the green arrow must point up, with 1 in the top left corner."))
    print(tr("Nếu bị ngược: igam3-screen rotate   |   Quay lại màn chính: igam3-screen start",
             "Upside down: igam3-screen rotate   |   Back to the main screen: igam3-screen start"))


def cmd_off(_):
    if screen_running():
        SCREEN.stop()  # the running screen program turns the screen off when it stops
    else:
        open_lcd(init=False).ScreenOff()
    print(tr("Đã tắt màn hình. Bật lại: igam3-screen start", "Screen turned off. Turn it back on: igam3-screen start"))


def cmd_config(_):
    try:
        import tkinter  # noqa: F401
    except ImportError:
        die(tr("trình cấu hình cần tkinter: sudo apt install python3-tk",
               "the configuration window needs tkinter: sudo apt install python3-tk"))
    take_over_screen()
    # "Save and run" in the wizard starts main.py through '#!/usr/bin/env python': make that the venv python
    env = dict(os.environ, PATH=f"{VENV_PYTHON.parent}{os.pathsep}{os.environ.get('PATH', '')}")
    subprocess.run([str(VENV_PYTHON), str(APP / "configure.py")], cwd=APP, env=env)
    # Hand the screen back to the service instead of a main.py started by the wizard
    if stop_processes(matching_processes(APP / "main.py")):
        time.sleep(3)
    print(tr("Bật lại màn hình chính với cấu hình mới...", "Starting the main screen with the new settings..."))
    SCREEN.start()


def cmd_panel(args):
    if not web_listening():
        RUNTIME.mkdir(mode=0o700, parents=True, exist_ok=True)
        with open(RUNTIME / "web-panel.log", "ab") as log:
            subprocess.Popen([str(VENV_PYTHONW), str(TOOLS / "web_panel.py"), "--idle-exit", "30"], cwd=ROOT,
                             stdin=subprocess.DEVNULL, stdout=log, stderr=log, **background_kwargs())
        for _ in range(50):
            if web_listening():
                break
            time.sleep(0.1)
    url = f"http://localhost:{WEB_PORT}"
    print(tr("Giao diện quản lý: ", "Web panel: ") + url)
    if not args.no_open:
        if WINDOWS:
            os.startfile(url)
        else:
            subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def cmd_web(args):
    if args.password:
        first = getpass.getpass(tr("Mật khẩu mới cho giao diện web: ", "New password for the web panel: "))
        if len(first) < 6:
            die(tr("mật khẩu cần ít nhất 6 ký tự", "the password needs at least 6 characters"))
        if getpass.getpass(tr("Nhập lại: ", "Again: ")) != first:
            die(tr("hai lần nhập không khớp", "the two entries differ"))
        set_web_password(first)
        print(tr("Đã đặt mật khẩu. Tên đăng nhập bất kỳ (ví dụ: admin).",
                 "Password set. Any user name works (for example: admin)."))
    if args.lan == "on":
        if not WEB_CONFIG.is_file():
            die(tr("cần đặt mật khẩu trước: igam3-screen web --password",
                   "set a password first: igam3-screen web --password"))
        stop_processes(matching_processes(TOOLS / "web_panel.py"))  # the local-only panel frees the port
        if not WINDOWS:
            UNIT_DIR.mkdir(parents=True, exist_ok=True)
            (UNIT_DIR / WEB_SERVICE).write_text(LAN_UNIT, encoding="utf8")
            systemctl_user("daemon-reload")
        WEB.set_autostart(True, now=True)
        if WINDOWS:
            print(tr("Nếu Windows hỏi có cho Python dùng mạng không: chọn Allow cho mạng riêng (Private networks).",
                     "If Windows asks whether Python may use the network: allow it for Private networks."))
    elif args.lan == "off":
        WEB.set_autostart(False, now=True)
        if not WINDOWS:
            (UNIT_DIR / WEB_SERVICE).unlink(missing_ok=True)
            systemctl_user("daemon-reload")
    ip = primary_ipv4()
    print(tr("Trên máy này : ", "This computer : ") + f"igam3-screen panel  (http://localhost:{WEB_PORT})")
    if WEB.state() == "active":
        print(tr(f"Mạng LAN     : BẬT, tự chạy khi khởi động — http://{ip}:{WEB_PORT} (đăng nhập bằng mật khẩu)",
                 f"Local network : ON, starts at boot — http://{ip}:{WEB_PORT} (sign in with the password)"))
    else:
        print(tr("Mạng LAN     : tắt. Mở cho điện thoại: igam3-screen web --lan on",
                 "Local network : off. Open it to phones: igam3-screen web --lan on")
              + ("" if WEB_CONFIG.is_file() else tr(" (đặt mật khẩu trước: igam3-screen web --password)",
                                                    " (set a password first: igam3-screen web --password)")))


def cmd_logs(args):
    if WINDOWS:
        for log in (APP / "log.log", RUNTIME / "igam3-screen.log"):
            if log.is_file():
                print(f"--- {log} ---")
                print("".join(log.read_text(encoding="utf8", errors="replace").splitlines(True)[-args.lines:]))
        return
    cmd = ["journalctl", "--user", "-u", SERVICE, "-u", WEB_SERVICE, "-n", str(args.lines), "--no-pager"]
    if args.follow:
        cmd.append("-f")
    os.execvp(cmd[0], cmd)


def cmd_init(args):
    """Settings that depend on the machine, run by the installer after copying the files"""
    import psutil
    names = sorted(psutil.net_if_stats())
    is_lan = lambda n: n.lower().startswith(("en", "eth")) or "ethernet" in n.lower()
    is_wifi = lambda n: n.lower().startswith("wl") or any(k in n.lower() for k in ("wi-fi", "wifi", "wlan", "wireless"))
    yaml, cfg = load_config()
    for key, matches in (("ETH", is_lan), ("WLO", is_wifi)):
        if not str(cfg["config"].get(key) or ""):
            cfg["config"][key] = next((n for n in names if matches(n)), "")
    if WINDOWS:
        cfg["config"]["HW_SENSORS"] = "PYTHON"  # LibreHardwareMonitor needs admin rights and is not shipped
    save_config(yaml, cfg)
    if args.language:
        settings = load_settings()
        settings["language"] = args.language
        save_settings(settings)
        i18n.refresh()
    custom = load_theme_custom()
    if args.title is not None:
        custom["title"] = args.title
    if args.tag is not None:
        custom["tag"] = args.tag
    save_theme_custom(custom)
    labels = theme_generator().hardware_labels()
    print(tr("Card mạng: ", "Network  : ") + f"LAN {cfg['config']['ETH'] or '-'}, Wi-Fi {cfg['config']['WLO'] or '-'}")
    print(tr("Phần cứng: ", "Hardware : ") + f"{labels['cpu']}, RAM {labels['ram']}, " + tr("ổ ", "disk ") + labels["ssd"])
    print(tr("Tiêu đề  : ", "Title    : ") + f"\"{custom['title']}\"  " + tr("nhãn", "tag") + f" \"{custom['tag']}\"")
    print(tr("Ngôn ngữ : Tiếng Việt", "Language : English"))


def cmd_install(args):
    if WINDOWS:
        menu = start_menu_dir()
        for old in ("Gỡ cài đặt iGam3 Screen.lnk", "iGam3 - Mã QR.lnk"):  # names used by version 1.0
            (menu / old).unlink(missing_ok=True)
        create_shortcut(menu / "iGam3 Screen.lnk", VENV_PYTHONW, f'"{TOOLS / "igam3_screen.py"}" panel', ROOT, ICON)
        create_shortcut(menu / "iGam3 Screen - Uninstall.lnk", "powershell.exe",
                        f'-NoProfile -ExecutionPolicy Bypass -File "{ROOT / "uninstall-windows.ps1"}"', ROOT, ICON)
        print(tr("Đã tạo lối tắt \"iGam3 Screen\" trong menu Start", "Created the \"iGam3 Screen\" shortcut in the Start menu"))
        if args.enable:
            SCREEN.set_autostart(True, now=True)
        return
    UNIT_DIR.mkdir(parents=True, exist_ok=True)
    # The unit in systemd/ assumes ~/igam3-screen: point it at wherever this copy is installed
    unit = (ROOT / "systemd" / SERVICE).read_text(encoding="utf8").replace("%h/igam3-screen", str(ROOT))
    (UNIT_DIR / SERVICE).write_text(unit, encoding="utf8")
    systemctl_user("daemon-reload")
    BIN_LINK.parent.mkdir(parents=True, exist_ok=True)
    if BIN_LINK.is_symlink() or BIN_LINK.exists():
        BIN_LINK.unlink()
    BIN_LINK.symlink_to(ROOT / "igam3-screen")
    DESKTOP_FILE.parent.mkdir(parents=True, exist_ok=True)
    DESKTOP_FILE.write_text(
        "[Desktop Entry]\nType=Application\nName=iGam3 Screen\n"
        "Comment=Manage the 3.5\" screen of the iGam3\n"
        "Comment[vi]=Quản lý màn hình 3.5\" của máy iGam3\n"
        f"Exec={ROOT / 'igam3-screen'} panel\n"
        f"Icon={APP / 'res/icons/monitor-icon-17865/64.png'}\nCategories=Utility;\n", encoding="utf8")
    print(tr(f"Đã cài dịch vụ {SERVICE}, lệnh {BIN_LINK} và biểu tượng \"iGam3 Screen\" trong menu ứng dụng",
             f"Installed the {SERVICE} service, the {BIN_LINK} command and the \"iGam3 Screen\" application icon"))
    if args.enable:
        sys.exit(SCREEN.set_autostart(True, now=True))


def cmd_run(_):
    """Entry point of the background screen program: shows the main screen chosen in settings.yaml"""
    os.chdir(APP)
    # Language of the dashboard values (sensors_custom) and dates (babel), whatever the system locale says
    os.environ["IGAM3_LANG"] = i18n.LANG
    import babel.dates
    babel.dates.LC_TIME = "vi_VN" if i18n.LANG == "vi" else "en_US"
    install_mirror()
    settings = load_settings()
    if settings["mode"] == "image":
        path = Path(str(settings["image"]))
        if path.is_file():
            stop = service_stop_event()
            lcd = open_lcd()
            frames = load_frames(path, (lcd.get_width(), lcd.get_height()), bool(settings["fill"]))
            print(tr(f"Màn chính: ảnh {path}", f"Main screen: picture {path}"), flush=True)
            # A still picture stays on the screen by itself: re-send it every 10 min in case the screen was reset
            play(lcd, frames, stop, refresh_s=600)
            lcd.ScreenOff()
            return
        print(tr(f"Không thấy ảnh {path}: hiện bảng thông số", f"Picture {path} not found: showing the dashboard"),
              file=sys.stderr, flush=True)
    elif settings["mode"] == "console" and not WINDOWS:
        from console_mirror import run_console
        stop = service_stop_event()
        lcd = open_lcd("landscape")
        print(tr("Màn chính: dòng lệnh tty3", "Main screen: console tty3"), flush=True)
        run_console(lcd, stop, primary_ipv4, web_qr_card)
        lcd.ScreenOff()
        return
    elif settings["mode"] == "qr":
        stop = service_stop_event()
        lcd = open_lcd("landscape")
        print(tr("Màn chính: mã QR", "Main screen: QR code"), flush=True)
        shown, drawn_at = None, 0.0
        while not stop.is_set():
            # Follow IP / web panel changes; re-send every 10 min in case the screen was reset
            state = qr_screen_state()
            if state != shown or time.monotonic() - drawn_at > 600:
                lcd.DisplayPILImage(qr_screen_image(state))
                shown, drawn_at = state, time.monotonic()
            stop.wait(10)
        lcd.ScreenOff()
        return
    if WINDOWS:
        watch_stop_file("screen", stop_stats_now)
    sys.argv = [str(APP / "main.py")]
    runpy.run_path(str(APP / "main.py"), run_name="__main__")


def main():
    if sys.stdout is None:  # pythonw.exe on Windows has no console: keep the messages in a log file
        RUNTIME.mkdir(parents=True, exist_ok=True)
        sys.stdout = sys.stderr = open(RUNTIME / "igam3-screen.log", "a", encoding="utf8", buffering=1)

    parser = argparse.ArgumentParser(
        prog="igam3-screen",
        description=tr('Quản lý màn hình 3.5" gắn trên máy iGam3 M1 (Turing Smart Screen / TURZX)',
                       'Manage the built-in 3.5" screen of the iGam3 M1 (Turing Smart Screen / TURZX)'))
    sub = parser.add_subparsers(dest="command", metavar=tr("LỆNH", "COMMAND"))

    def add(name, func, vi, en):
        help_text = tr(vi, en)
        p = sub.add_parser(name, help=help_text, description=help_text)
        p.set_defaults(func=func)
        return p

    orientation_help = tr("hướng hiển thị (mặc định theo theme)", "orientation (default: the theme's)")
    keep_help = tr("dùng làm màn hình chính, giữ cả khi khởi động lại", "make it the main screen, kept after a restart")

    p = add("status", cmd_status, "xem tình trạng màn hình, dịch vụ và cấu hình", "show the screen, service and settings")
    p.add_argument("--json", action="store_true", help=tr("xuất dạng JSON", "JSON output"))
    add("start", cmd_start, "bật màn hình chính", "start the main screen")
    add("stop", cmd_stop, "dừng màn hình chính (màn hình tắt)", "stop the main screen (the screen turns off)")
    add("restart", cmd_restart, "khởi động lại màn hình chính", "restart the main screen")
    add("enable", cmd_enable, "tự bật màn hình chính khi khởi động máy (và bật ngay)",
        "start the main screen at boot (and now)")
    add("disable", cmd_disable, "không tự bật khi khởi động (và dừng ngay)", "do not start at boot (and stop now)")
    p = add("autostart", cmd_autostart, "bật/tắt việc tự bật màn hình khi khởi động máy",
            "turn starting the screen at boot on or off")
    p.add_argument("state", choices=["on", "off"])
    p = add("mode", cmd_mode, "chọn màn hình chính: stats (bảng thông số), image (ảnh), console (dòng lệnh), qr (mã QR)",
            "choose the main screen: stats (dashboard), image (picture), console, qr (QR code)")
    p.add_argument("mode", choices=list(MODES))
    p = add("language", cmd_language, "ngôn ngữ: vi (tiếng Việt), en (English), auto (theo máy)",
            "language: vi (Vietnamese), en (English), auto (follows the system)")
    p.add_argument("language", choices=["vi", "en", "auto"])
    p = add("qr", cmd_qr, "hiện mã QR để mở giao diện từ điện thoại (một lúc rồi quay lại màn hình chính)",
            "show the QR code of the web panel for a while, then the main screen again")
    p.add_argument("--seconds", type=int, default=60, help=tr("thời gian hiện, mặc định 60 giây", "duration, default 60 s"))
    p = add("shortcut", cmd_shortcut, "bật/tắt phím tắt Ctrl+Alt+Q hiện mã QR", "turn the Ctrl+Alt+Q QR shortcut on or off")
    p.add_argument("state", choices=["on", "off"])
    add("stats", lambda a: cmd_mode(argparse.Namespace(mode="stats")), "màn hình chính = bảng thông số",
        "main screen = dashboard")
    add("console", lambda a: cmd_mode(argparse.Namespace(mode="console")),
        "màn hình chính = dòng lệnh tty3 (Linux: dùng máy không cần HDMI, cần bàn phím USB)",
        "main screen = console tty3 (Linux: use the computer without HDMI, with a USB keyboard)")
    p = add("title", cmd_title, "đổi chữ tiêu đề trên bảng thông số (theme iGam3)",
            "change the dashboard title (iGam3 theme)")
    p.add_argument("title", help=tr('chữ lớn, ví dụ "iGam3 M1"', 'big text, for example "iGam3 M1"'))
    p.add_argument("tag", nargs="?", help=tr('nhãn bên cạnh, ví dụ "DePIN NODE" ("" để bỏ nhãn)',
                                             'tag next to it, for example "DePIN NODE" ("" for none)'))
    p = add("background", cmd_background, "đặt ảnh nền cho bảng thông số (theme iGam3)",
            "set the dashboard background picture (iGam3 theme)")
    p.add_argument("file", nargs="?", help=tr("ảnh nền (PNG/JPG)", "background picture (PNG/JPG)"))
    p.add_argument("--none", action="store_true", help=tr("bỏ ảnh nền, dùng nền tối mặc định", "back to the dark default"))
    p = add("blocks", cmd_blocks, "xem / bật / tắt các khối trên bảng thông số, ví dụ: blocks ssd=off",
            "show / turn on / turn off the dashboard blocks, for example: blocks ssd=off")
    p.add_argument("changes", nargs="*", metavar=tr("khối=on|off", "block=on|off"))
    p = add("splash", cmd_splash, "tạo ảnh giới thiệu với chữ của bạn và hiện lên màn hình",
            "make a splash picture with your own text and show it")
    p.add_argument("title", help=tr("chữ lớn", "big text"))
    p.add_argument("subtitle", nargs="?", default="", help=tr("dòng phụ", "subtitle"))
    p.add_argument("footer", nargs="?", default="", help=tr("dòng cuối", "bottom line"))
    p.add_argument("--photo", help=tr("ảnh làm nền (tuỳ chọn)", "background photo (optional)"))
    p.add_argument("--logo", help=tr("logo đặt ở góc phải (PNG nền trong suốt là đẹp nhất)",
                                     "logo in the right corner (best: PNG with a transparent background)"))
    p.add_argument("--keep", action="store_true", help=keep_help)
    p.add_argument("--out", help=tr("chỉ lưu ảnh ra file này, không hiện lên màn hình",
                                    "only save the picture to this file, do not show it"))
    add("themes", cmd_themes, 'liệt kê các theme cho màn 3.5"', 'list the themes for the 3.5" screen')
    p = add("theme", cmd_theme, "đổi theme", "change the theme")
    p.add_argument("name", help=tr("tên theme (xem: igam3-screen themes)", "theme name (see: igam3-screen themes)"))
    p = add("brightness", cmd_brightness, "đặt độ sáng 0-100", "set the brightness 0-100")
    p.add_argument("level", type=int)
    p = add("rotate", cmd_rotate, "xoay màn hình 180° (không ghi on/off thì đảo trạng thái)",
            "rotate the screen 180° (without on/off: toggle)")
    p.add_argument("state", nargs="?", choices=["on", "off"])
    p = add("image", cmd_image, "hiển thị một ảnh (PNG/JPG/GIF động...) lên màn hình",
            "show a picture (PNG/JPG/animated GIF...) on the screen")
    p.add_argument("file")
    p.add_argument("--keep", action="store_true", help=keep_help)
    p.add_argument("--fill", action="store_true", help=tr("phóng ảnh phủ kín màn hình (cắt bớt mép)",
                                                          "fill the whole screen (crops the edges)"))
    p.add_argument("--once", action="store_true", help=tr("GIF động: chỉ phát một lượt", "animated GIF: play once"))
    p.add_argument("--orientation", choices=["landscape", "portrait"], help=orientation_help)
    p = add("test", cmd_test, "hiện hình kiểm tra hướng màn hình", "show a test pattern to check the orientation")
    p.add_argument("--orientation", choices=["landscape", "portrait"], help=orientation_help)
    add("off", cmd_off, "tắt màn hình", "turn the screen off")
    add("config", cmd_config, "mở trình cấu hình gốc của turing-smart-screen-python (cần tkinter)",
        "open the configuration window of turing-smart-screen-python (needs tkinter)")
    p = add("panel", cmd_panel, "mở giao diện quản lý trên trình duyệt của máy này",
            "open the web panel in the browser of this computer")
    p.add_argument("--no-open", action="store_true", help=tr("chỉ bật giao diện, không mở trình duyệt",
                                                             "start the panel without opening the browser"))
    p = add("web", cmd_web, "mật khẩu và quyền truy cập giao diện web từ điện thoại (mạng LAN)",
            "web panel password and access from phones (local network)")
    p.add_argument("--password", action="store_true", help=tr("đặt mật khẩu (bắt buộc trước khi mở cho mạng LAN)",
                                                              "set the password (required before opening it)"))
    p.add_argument("--lan", choices=["on", "off"], help=tr("mở / đóng giao diện cho các máy khác trong mạng LAN",
                                                           "open / close the panel to the other devices of the network"))
    p = add("logs", cmd_logs, "xem nhật ký của dịch vụ", "show the service logs")
    p.add_argument("-n", "--lines", type=int, default=50, help=tr("số dòng (mặc định 50)", "number of lines (default 50)"))
    p.add_argument("-f", "--follow", action="store_true", help=tr("theo dõi liên tục (Linux)", "keep following (Linux)"))
    p = add("install", cmd_install, "cài dịch vụ, lệnh igam3-screen và lối tắt trong menu",
            "install the service, the igam3-screen command and the menu shortcuts")
    p.add_argument("--enable", action="store_true", help=tr("bật tự chạy và chạy ngay", "start at boot and now"))
    p = add("init", cmd_init, "(bộ cài dùng) dò card mạng, phần cứng và tạo theme iGam3 cho máy này",
            "(used by the installer) detect the network cards and hardware, build the iGam3 theme")
    p.add_argument("--title", help=tr("chữ tiêu đề", "title text"))
    p.add_argument("--tag", help=tr("nhãn bên cạnh tiêu đề", "tag next to the title"))
    p.add_argument("--language", choices=["vi", "en", "auto"], help=tr("ngôn ngữ", "language"))
    add("run", cmd_run, "(dùng nội bộ) chạy màn hình chính ở chế độ nền", "(internal) run the main screen in the background")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return
    args.func(args)


if __name__ == "__main__":
    main()
