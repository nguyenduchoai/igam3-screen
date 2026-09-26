#!/usr/bin/env python3
# igam3-screen: quản lý màn hình 3.5" (Turing Smart Screen / TURZX rev. A, USB 1a86:5722) của máy iGam3 M1.
# Bọc chương trình turing-smart-screen-python (thư mục app/), chạy màn hình chính ở chế độ nền (lệnh "run") và giao
# diện quản lý web tools/web_panel.py. Linux: dịch vụ systemd user. Windows (thử nghiệm): xem tools/platform_support.py
#   igam3-screen panel         mở giao diện trên chính máy này (tự tắt khi không dùng)
#   igam3-screen web --lan on  người dùng tự quyết định mở giao diện cho mạng LAN

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
MODES = {"stats": "bảng thông số", "image": "ảnh cố định", "console": "dòng lệnh", "qr": "mã QR"}
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
    print(f"Lỗi: {msg}", file=sys.stderr)
    sys.exit(1)


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


# What the service shows: the stats dashboard, a fixed picture, the text console or the QR code
def load_settings():
    return load_yaml_dict(SETTINGS, {"mode": "stats", "image": "", "fill": False})


def save_settings(settings):
    save_yaml_dict(SETTINGS, settings, "# Màn hình chính: stats = bảng thông số, image = ảnh cố định, console = dòng lệnh,"
                                       " qr = mã QR.\n"
                                       "# Đổi bằng: igam3-screen mode stats|image|console|qr  (hoặc giao diện web)\n")


# Header text, background photo and blocks of the iGam3 theme: make_theme.py owns their format
def theme_generator():
    if str(IGAM3_THEME) not in sys.path:
        sys.path.insert(0, str(IGAM3_THEME))
    import make_theme
    return make_theme


def load_theme_custom():
    return theme_generator().load_custom()


def save_theme_custom(custom):
    save_yaml_dict(THEME_CUSTOM, custom, "# Tuỳ chỉnh theme iGam3. Đổi bằng: igam3-screen title / background / blocks\n")
    make_theme = theme_generator()
    layout = make_theme.compute_layout(custom["blocks"])
    make_theme.draw_background(custom, layout)
    make_theme.write_theme_yaml(custom, layout)


def apply_dashboard_change():
    _, cfg = load_config()
    if str(cfg["config"]["THEME"]) != IGAM3_THEME.name:
        print(f"Lưu ý: đang dùng theme '{cfg['config']['THEME']}'. Thay đổi này chỉ áp dụng cho theme iGam3 "
              f"(chọn lại: igam3-screen theme {IGAM3_THEME.name})")
    elif load_settings()["mode"] != "stats":
        print("Màn chính đang không phải bảng thông số. Xem bảng thông số: igam3-screen mode stats")
    else:
        restart_if_running()


# Password of the web panel: only a salted hash is stored
def set_web_password(password):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000).hex()
    WEB_CONFIG.touch(mode=0o600)
    save_yaml_dict(WEB_CONFIG, {"salt": salt, "hash": digest}, "# Mật khẩu giao diện web (đã băm). Đổi: igam3-screen web --password\n")
    os.chmod(WEB_CONFIG, 0o600)


# ---------------------------------------------------------------- background services

def systemctl_user(*args):
    return subprocess.run(["systemctl", "--user", *args]).returncode


def screen_running():
    return SCREEN.state() in ("active", "activating")


def restart_if_running():
    if screen_running():
        print("Khởi động lại màn hình để áp dụng...")
        SCREEN.restart()
    else:
        print("Màn hình đang tắt: thay đổi sẽ có hiệu lực khi chạy 'igam3-screen start'.")


def take_over_screen():
    # Only one program can talk to the serial port: stop the service first
    if screen_running():
        print("Tạm dừng màn hình chính (chạy 'igam3-screen start' để bật lại)...")
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
        die('không thấy màn hình USB 1a86:5722 (Turing/TURZX 3.5"). Kiểm tra bằng '
            + ("Device Manager > Ports (COM & LPT)" if WINDOWS else "lệnh: lsusb"))
    if not WINDOWS and not os.access(port, os.R_OK | os.W_OK):
        die(f"chưa có quyền mở {port}. Chạy một lần: sudo {SETUP_ROOT}")
    return port


def open_lcd(orientation=None, init=True):
    port = require_port()
    if WINDOWS:
        import serial
        try:
            serial.Serial(port).close()
        except serial.SerialException:
            die(f"{port} đang bị chương trình khác dùng. Tắt app TURZX (và bỏ nó khỏi Startup) rồi thử lại.")
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
        die(f"không thấy file {path}")
    try:
        with Image.open(path) as img:
            img.verify()
    except Exception as e:
        die(f"không mở được ảnh {path.name}: {e}")
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
        print(f"Đang phát ảnh động {path.name}: {len(frames)} khung hình. Ctrl+C để dừng.")
    play(lcd, frames, stop, loop=not once)
    mirror.flush()
    print(f"Đã hiển thị {path.name}. Quay lại màn chính: igam3-screen start")


def keep_image(path, fill):
    """Make a picture the main screen. It is copied into images/, so moving or deleting the original is fine"""
    data = path.read_bytes()
    IMAGES.mkdir(exist_ok=True)
    for old in IMAGES.glob("main.*"):
        old.unlink()
    dest = IMAGES / f"main{path.suffix.lower()}"
    dest.write_bytes(data)
    save_settings({"mode": "image", "image": str(dest), "fill": fill})
    print(f"Màn chính: ảnh {path.name}, giữ nguyên cả khi khởi động lại. Quay lại bảng thông số: igam3-screen mode stats")
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
    d.text((w // 2, 175), "TRÊN ↑", font=big, fill=(255, 255, 255), anchor="mm")
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
    blocks = theme_generator().BLOCKS
    return {
        "platform": "windows" if WINDOWS else "linux",
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
        "console": {"allowed": not WINDOWS and os.access(CONSOLE_VCS, os.R_OK), "active_vt": _active_vt()},
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
        screen = "KHÔNG THẤY (USB 1a86:5722)"
    elif dev["access"]:
        screen = f"{dev['port']} (có quyền truy cập)"
    else:
        screen = f"{dev['port']} (CHƯA CÓ QUYỀN: sudo {SETUP_ROOT})"
    main = MODES.get(st["mode"], st["mode"]) + (f" ({st['image']})" if st["mode"] == "image" else "")
    orientation = {"landscape": "ngang", "portrait": "dọc"}.get(st["orientation"], "?")
    print(f"Màn hình  : {screen}")
    print(f"Dịch vụ   : {st['service']['state']} (tự chạy khi khởi động: {'có' if st['service']['autostart'] else 'không'})")
    print(f"Màn chính : {main}")
    print(f"Theme     : {st['theme']} ({orientation})")
    if st["theme"] == IGAM3_THEME.name:
        print(f"Tiêu đề   : \"{st['title']}\"  nhãn \"{st['tag']}\"  ảnh nền: {st['background'] or 'mặc định'}")
        print("Các khối  : " + ", ".join(f"{b['label']} {'bật' if b['on'] else 'tắt'}" for b in st["blocks"]))
    print(f"Độ sáng   : {st['brightness']}%   Xoay 180°: {'có' if st['reverse'] else 'không'}")
    if st["web"]["lan"]:
        print(f"Giao diện : http://{st['ip']}:{WEB_PORT} (mở cho mạng LAN, có mật khẩu)")
    else:
        print(f"Giao diện : igam3-screen panel (chỉ trên máy này; mở cho mạng LAN: igam3-screen web --lan on)")


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
    print(f"Tự bật màn hình khi khởi động máy: {'có' if args.state == 'on' else 'không'}")
    sys.exit(code)


def cmd_mode(args):
    if args.mode == "console" and WINDOWS:
        die("chế độ Dòng lệnh chỉ có trên Linux")
    settings = load_settings()
    if args.mode == "image" and not Path(str(settings["image"])).is_file():
        die("chưa có ảnh nào: dùng 'igam3-screen image <ảnh> --keep' hoặc 'igam3-screen splash ... --keep'")
    settings["mode"] = args.mode
    save_settings(settings)
    print(f"Màn chính: {MODES[args.mode]}")
    if args.mode == "console":
        if not os.access(CONSOLE_VCS, os.R_OK):
            print(f"Lưu ý: chưa có quyền đọc dòng lệnh. Chạy một lần: sudo {SETUP_ROOT}")
        print("Cắm bàn phím USB, bấm Ctrl+Alt+F3 để đăng nhập và gõ lệnh trên màn nhỏ.")
    if args.mode == "qr" and WEB.state() != "active":
        print("Lưu ý: giao diện chưa mở cho mạng LAN nên chưa quét được. Mở: igam3-screen web --lan on")
    SCREEN.restart()


def cmd_title(args):
    custom = load_theme_custom()
    custom["title"] = args.title
    if args.tag is not None:
        custom["tag"] = args.tag
    save_theme_custom(custom)
    print(f"Tiêu đề bảng thông số: \"{custom['title']}\"" +
          (f", nhãn \"{custom['tag']}\"" if custom["tag"] else ", không có nhãn"))
    apply_dashboard_change()


def cmd_background(args):
    if args.none == bool(args.file):
        die("cần đúng một trong hai: đường dẫn ảnh, hoặc --none để bỏ ảnh nền")
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
    print("Ảnh nền bảng thông số: " + (path.name if path else "mặc định (nền tối)"))
    apply_dashboard_change()


def cmd_blocks(args):
    blocks = theme_generator().BLOCKS
    custom = load_theme_custom()
    if not args.changes:
        for key, label in blocks.items():
            print(f"  {key:<9} {label:<10} {'bật' if custom['blocks'][key] else 'tắt'}")
        print("Đổi: igam3-screen blocks ssd=off network=on ...")
        return
    for change in args.changes:
        key, _, value = change.partition("=")
        if key not in blocks or value not in ("on", "off"):
            die(f"'{change}' không hợp lệ: dùng dạng cpu=on hoặc ssd=off. Các khối: {', '.join(blocks)}")
        custom["blocks"][key] = value == "on"
    save_theme_custom(custom)
    print("Các khối: " + ", ".join(f"{label} {'bật' if custom['blocks'][k] else 'tắt'}" for k, label in blocks.items()))
    apply_dashboard_change()


def cmd_splash(args):
    from make_splash import make_splash
    photo = checked_image_path(args.photo) if args.photo else None
    logo = checked_image_path(args.logo) if args.logo else None
    image = make_splash(args.title, args.subtitle, args.footer, photo, logo)
    if args.out:
        image.save(args.out)
        print(f"Đã tạo ảnh {args.out}")
        return
    IMAGES.mkdir(exist_ok=True)
    out = IMAGES / "splash.png"
    image.save(out)
    print(f"Đã tạo ảnh {out}")
    if args.keep:
        require_port()
        keep_image(out, fill=False)
    else:
        show_temporarily(out, fill=False)


def cmd_themes(_):
    _, cfg = load_config()
    current = str(cfg["config"]["THEME"])
    print('Theme cho màn 3.5" (* = đang dùng):')
    for theme in themes_35():
        mark = "*" if theme["name"] == current else " "
        print(f" {mark} {theme['name']:<28} {'ngang' if theme['orientation'] == 'landscape' else 'dọc'}")


def cmd_theme(args):
    info = theme_info(args.name)
    if not info:
        die(f"không có theme '{args.name}'. Xem danh sách: igam3-screen themes")
    if info[0] != '3.5"':
        die(f"theme '{args.name}' dành cho màn {info[0]}, không dùng được cho màn 3.5\"")
    yaml, cfg = load_config()
    cfg["config"]["THEME"] = args.name
    save_config(yaml, cfg)
    print(f"Theme: {args.name}")
    restart_if_running()


def cmd_brightness(args):
    if not 0 <= args.level <= 100:
        die("độ sáng phải từ 0 đến 100")
    yaml, cfg = load_config()
    cfg["display"]["BRIGHTNESS"] = args.level
    save_config(yaml, cfg)
    print(f"Độ sáng: {args.level}%" + ("  (lưu ý: màn rev A dễ nóng khi để sáng cao)" if args.level > 60 else ""))
    restart_if_running()


def cmd_rotate(args):
    yaml, cfg = load_config()
    reverse = args.state == "on" if args.state else not bool(cfg["display"].get("DISPLAY_REVERSE", False))
    cfg["display"]["DISPLAY_REVERSE"] = reverse
    save_config(yaml, cfg)
    print(f"Xoay 180°: {'bật' if reverse else 'tắt'}")
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
        print("Màn nhỏ đang hiện mã QR rồi.")
        return
    require_port()
    was_running = screen_running()
    take_over_screen()
    stop = stop_on_signals()
    mirror = install_mirror()
    lcd = open_lcd("landscape")
    lcd.DisplayPILImage(qr_screen_image(qr_screen_state()))
    mirror.flush()
    print(f"Màn nhỏ đang hiện mã QR trong {args.seconds} giây, sau đó quay lại màn hình chính.", flush=True)
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
    if WINDOWS:
        link = start_menu_dir() / "iGam3 - Mã QR.lnk"
        if args.state == "on":
            create_shortcut(link, VENV_PYTHONW, f'"{TOOLS / "igam3_screen.py"}" qr', ROOT, ICON, "CTRL+ALT+Q")
        else:
            link.unlink(missing_ok=True)
        print("Phím tắt Ctrl+Alt+Q (hiện mã QR trên màn nhỏ 1 phút): " + ("bật" if args.state == "on" else "tắt"))
        return
    import ast
    result = gsettings("get", SHORTCUT_SCHEMA, "custom-keybindings")
    if result.returncode != 0:
        die("không đọc được phím tắt GNOME: hãy chạy lệnh này trong phiên desktop")
    raw = result.stdout.strip()
    paths = ast.literal_eval(raw.replace("@as ", "", 1)) if raw else []
    entry = f"{SHORTCUT_SCHEMA}.custom-keybinding:{SHORTCUT_PATH}"
    quote = lambda text: "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"
    if args.state == "on":
        for key, value in (("name", "iGam3: hiện mã QR trên màn nhỏ"), ("command", f"{ROOT / 'igam3-screen'} qr"),
                           ("binding", SHORTCUT_KEYS)):
            gsettings("set", entry, key, quote(value))
        if SHORTCUT_PATH not in paths:
            paths.append(SHORTCUT_PATH)
    else:
        paths = [p for p in paths if p != SHORTCUT_PATH]
        for key in ("name", "command", "binding"):
            gsettings("reset", entry, key)
    result = gsettings("set", SHORTCUT_SCHEMA, "custom-keybindings", str(paths) if paths else "@as []")
    if result.returncode != 0:
        die(f"không lưu được phím tắt: {result.stderr.strip()}")
    print("Phím tắt Ctrl+Alt+Q (hiện mã QR trên màn nhỏ 1 phút): " + ("bật" if args.state == "on" else "tắt"))


def cmd_test(args):
    require_port()
    take_over_screen()
    mirror = install_mirror()
    lcd = open_lcd(args.orientation)
    lcd.DisplayPILImage(test_pattern(lcd.get_width(), lcd.get_height()))
    mirror.flush()
    print("Đang hiện hình kiểm tra: mũi tên xanh phải chỉ lên trên, số 1 ở góc trên bên trái.")
    print("Nếu bị ngược: igam3-screen rotate   |   Quay lại màn chính: igam3-screen start")


def cmd_off(_):
    if screen_running():
        SCREEN.stop()  # the running screen program turns the screen off when it stops
    else:
        open_lcd(init=False).ScreenOff()
    print("Đã tắt màn hình. Bật lại: igam3-screen start")


def cmd_config(_):
    try:
        import tkinter  # noqa: F401
    except ImportError:
        die("giao diện cấu hình cần tkinter: sudo apt install python3-tk")
    take_over_screen()
    # "Save and run" in the wizard starts main.py through '#!/usr/bin/env python': make that the venv python
    env = dict(os.environ, PATH=f"{VENV_PYTHON.parent}{os.pathsep}{os.environ.get('PATH', '')}")
    subprocess.run([str(VENV_PYTHON), str(APP / "configure.py")], cwd=APP, env=env)
    # Hand the screen back to the service instead of a main.py started by the wizard
    if stop_processes(matching_processes(APP / "main.py")):
        time.sleep(3)
    print("Bật lại màn hình chính với cấu hình mới...")
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
    print(f"Giao diện quản lý: {url}")
    if not args.no_open:
        if WINDOWS:
            os.startfile(url)
        else:
            subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def cmd_web(args):
    if args.password:
        first = getpass.getpass("Mật khẩu mới cho giao diện web: ")
        if len(first) < 6:
            die("mật khẩu cần ít nhất 6 ký tự")
        if getpass.getpass("Nhập lại: ") != first:
            die("hai lần nhập không khớp")
        set_web_password(first)
        print("Đã đặt mật khẩu. Tên đăng nhập bất kỳ (ví dụ: admin).")
    if args.lan == "on":
        if not WEB_CONFIG.is_file():
            die("cần đặt mật khẩu trước: igam3-screen web --password")
        stop_processes(matching_processes(TOOLS / "web_panel.py"))  # the local-only panel frees the port
        if not WINDOWS:
            UNIT_DIR.mkdir(parents=True, exist_ok=True)
            (UNIT_DIR / WEB_SERVICE).write_text(LAN_UNIT, encoding="utf8")
            systemctl_user("daemon-reload")
        WEB.set_autostart(True, now=True)
        if WINDOWS:
            print("Nếu Windows hỏi có cho Python dùng mạng không: chọn Allow cho mạng riêng (Private networks).")
    elif args.lan == "off":
        WEB.set_autostart(False, now=True)
        if not WINDOWS:
            (UNIT_DIR / WEB_SERVICE).unlink(missing_ok=True)
            systemctl_user("daemon-reload")
    ip = primary_ipv4()
    print(f"Trên máy này : igam3-screen panel  (http://localhost:{WEB_PORT})")
    if WEB.state() == "active":
        print(f"Mạng LAN     : BẬT, tự chạy khi khởi động — http://{ip}:{WEB_PORT} (đăng nhập bằng mật khẩu)")
    else:
        print(f"Mạng LAN     : tắt. Mở cho điện thoại: igam3-screen web --lan on"
              + ("" if WEB_CONFIG.is_file() else " (đặt mật khẩu trước: igam3-screen web --password)"))


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
    custom = load_theme_custom()
    if args.title is not None:
        custom["title"] = args.title
    if args.tag is not None:
        custom["tag"] = args.tag
    save_theme_custom(custom)
    labels = theme_generator().hardware_labels()
    print(f"Card mạng: LAN {cfg['config']['ETH'] or '-'}, Wi-Fi {cfg['config']['WLO'] or '-'}")
    print(f"Phần cứng: {labels['cpu']}, RAM {labels['ram']}, ổ {labels['ssd']}")
    print(f"Tiêu đề  : \"{custom['title']}\"  nhãn \"{custom['tag']}\"")


def cmd_install(args):
    if WINDOWS:
        menu = start_menu_dir()
        create_shortcut(menu / "iGam3 Screen.lnk", VENV_PYTHONW, f'"{TOOLS / "igam3_screen.py"}" panel', ROOT, ICON)
        create_shortcut(menu / "Gỡ cài đặt iGam3 Screen.lnk", "powershell.exe",
                        f'-NoProfile -ExecutionPolicy Bypass -File "{ROOT / "uninstall-windows.ps1"}"', ROOT, ICON)
        print("Đã tạo lối tắt \"iGam3 Screen\" trong menu Start")
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
        "Comment=Quản lý màn hình 3.5\" của máy iGam3\n"
        f"Exec={ROOT / 'igam3-screen'} panel\n"
        f"Icon={APP / 'res/icons/monitor-icon-17865/64.png'}\nCategories=Utility;\n", encoding="utf8")
    print(f"Đã cài dịch vụ {SERVICE}, lệnh {BIN_LINK} và biểu tượng \"iGam3 Screen\" trong menu ứng dụng")
    if args.enable:
        sys.exit(SCREEN.set_autostart(True, now=True))


def cmd_run(_):
    """Entry point of the background screen program: shows the main screen chosen in settings.yaml"""
    os.chdir(APP)
    install_mirror()
    settings = load_settings()
    if settings["mode"] == "image":
        path = Path(str(settings["image"]))
        if path.is_file():
            stop = service_stop_event()
            lcd = open_lcd()
            frames = load_frames(path, (lcd.get_width(), lcd.get_height()), bool(settings["fill"]))
            print(f"Màn chính: ảnh {path}", flush=True)
            # A still picture stays on the screen by itself: re-send it every 10 min in case the screen was reset
            play(lcd, frames, stop, refresh_s=600)
            lcd.ScreenOff()
            return
        print(f"Không thấy ảnh {path}: hiện bảng thông số", file=sys.stderr, flush=True)
    elif settings["mode"] == "console" and not WINDOWS:
        from console_mirror import run_console
        stop = service_stop_event()
        lcd = open_lcd("landscape")
        print("Màn chính: dòng lệnh tty3", flush=True)
        run_console(lcd, stop, primary_ipv4, web_qr_card)
        lcd.ScreenOff()
        return
    elif settings["mode"] == "qr":
        stop = service_stop_event()
        lcd = open_lcd("landscape")
        print("Màn chính: mã QR", flush=True)
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
        description='Quản lý màn hình 3.5" gắn trên máy iGam3 M1 (Turing Smart Screen / TURZX)')
    sub = parser.add_subparsers(dest="command", metavar="LỆNH")

    def add(name, func, help_text):
        p = sub.add_parser(name, help=help_text, description=help_text)
        p.set_defaults(func=func)
        return p

    p = add("status", cmd_status, "xem tình trạng màn hình, dịch vụ và cấu hình")
    p.add_argument("--json", action="store_true", help="xuất dạng JSON")
    add("start", cmd_start, "bật màn hình chính")
    add("stop", cmd_stop, "dừng màn hình chính (màn hình tắt)")
    add("restart", cmd_restart, "khởi động lại màn hình chính")
    add("enable", cmd_enable, "tự bật màn hình chính khi khởi động máy (và bật ngay)")
    add("disable", cmd_disable, "không tự bật khi khởi động (và dừng ngay)")
    p = add("autostart", cmd_autostart, "bật/tắt việc tự bật màn hình khi khởi động máy")
    p.add_argument("state", choices=["on", "off"])
    p = add("mode", cmd_mode, "chọn màn hình chính: stats (bảng thông số), image (ảnh), console (dòng lệnh), qr (mã QR)")
    p.add_argument("mode", choices=list(MODES))
    p = add("qr", cmd_qr, "hiện mã QR để mở giao diện từ điện thoại (một lúc rồi quay lại màn hình chính)")
    p.add_argument("--seconds", type=int, default=60, help="thời gian hiện, mặc định 60 giây")
    p = add("shortcut", cmd_shortcut, "bật/tắt phím tắt Ctrl+Alt+Q hiện mã QR")
    p.add_argument("state", choices=["on", "off"])
    add("stats", lambda a: cmd_mode(argparse.Namespace(mode="stats")), "màn hình chính = bảng thông số")
    add("console", lambda a: cmd_mode(argparse.Namespace(mode="console")),
        "màn hình chính = dòng lệnh tty3 (Linux: dùng máy không cần HDMI, cần bàn phím USB)")
    p = add("title", cmd_title, "đổi chữ tiêu đề trên bảng thông số (theme iGam3)")
    p.add_argument("title", help='chữ lớn, ví dụ "iGam3 M1"')
    p.add_argument("tag", nargs="?", help='nhãn bên cạnh, ví dụ "DePIN NODE" ("" để bỏ nhãn)')
    p = add("background", cmd_background, "đặt ảnh nền cho bảng thông số (theme iGam3)")
    p.add_argument("file", nargs="?", help="ảnh nền (PNG/JPG)")
    p.add_argument("--none", action="store_true", help="bỏ ảnh nền, dùng nền tối mặc định")
    p = add("blocks", cmd_blocks, "xem / bật / tắt các khối trên bảng thông số, ví dụ: blocks ssd=off")
    p.add_argument("changes", nargs="*", metavar="khối=on|off")
    p = add("splash", cmd_splash, "tạo ảnh giới thiệu với chữ của anh (kiểu ảnh mẫu) và hiện lên màn hình")
    p.add_argument("title", help="chữ lớn")
    p.add_argument("subtitle", nargs="?", default="", help="dòng phụ")
    p.add_argument("footer", nargs="?", default="", help="dòng cuối")
    p.add_argument("--photo", help="ảnh làm nền (tuỳ chọn)")
    p.add_argument("--logo", help="logo đặt ở góc phải (PNG nền trong suốt là đẹp nhất)")
    p.add_argument("--keep", action="store_true", help="dùng làm màn hình chính, giữ cả khi khởi động lại")
    p.add_argument("--out", help="chỉ lưu ảnh ra file này, không hiện lên màn hình")
    add("themes", cmd_themes, 'liệt kê các theme cho màn 3.5"')
    p = add("theme", cmd_theme, "đổi theme")
    p.add_argument("name", help="tên theme (xem: igam3-screen themes)")
    p = add("brightness", cmd_brightness, "đặt độ sáng 0-100")
    p.add_argument("level", type=int)
    p = add("rotate", cmd_rotate, "xoay màn hình 180° (không ghi on/off thì đảo trạng thái)")
    p.add_argument("state", nargs="?", choices=["on", "off"])
    p = add("image", cmd_image, "hiển thị một ảnh (PNG/JPG/GIF động...) lên màn hình")
    p.add_argument("file")
    p.add_argument("--keep", action="store_true", help="dùng làm màn hình chính, giữ cả khi khởi động lại")
    p.add_argument("--fill", action="store_true", help="phóng ảnh phủ kín màn hình (cắt bớt mép)")
    p.add_argument("--once", action="store_true", help="GIF động: chỉ phát một lượt")
    p.add_argument("--orientation", choices=["landscape", "portrait"], help="hướng hiển thị (mặc định theo theme)")
    p = add("test", cmd_test, "hiện hình kiểm tra hướng màn hình")
    p.add_argument("--orientation", choices=["landscape", "portrait"], help="hướng hiển thị (mặc định theo theme)")
    add("off", cmd_off, "tắt màn hình")
    add("config", cmd_config, "mở trình cấu hình gốc của turing-smart-screen-python (cần tkinter)")
    p = add("panel", cmd_panel, "mở giao diện quản lý trên trình duyệt của máy này")
    p.add_argument("--no-open", action="store_true", help="chỉ bật giao diện, không mở trình duyệt")
    p = add("web", cmd_web, "mật khẩu và quyền truy cập giao diện web từ điện thoại (mạng LAN)")
    p.add_argument("--password", action="store_true", help="đặt mật khẩu (bắt buộc trước khi mở cho mạng LAN)")
    p.add_argument("--lan", choices=["on", "off"], help="mở / đóng giao diện cho các máy khác trong mạng LAN")
    p = add("logs", cmd_logs, "xem nhật ký của dịch vụ")
    p.add_argument("-n", "--lines", type=int, default=50, help="số dòng (mặc định 50)")
    p.add_argument("-f", "--follow", action="store_true", help="theo dõi liên tục (Linux)")
    p = add("install", cmd_install, "cài dịch vụ, lệnh igam3-screen và lối tắt trong menu")
    p.add_argument("--enable", action="store_true", help="bật tự chạy và chạy ngay")
    p = add("init", cmd_init, "(bộ cài dùng) dò card mạng, phần cứng và tạo theme iGam3 cho máy này")
    p.add_argument("--title", help="chữ tiêu đề")
    p.add_argument("--tag", help="nhãn bên cạnh tiêu đề")
    add("run", cmd_run, "(dùng nội bộ) chạy màn hình chính ở chế độ nền")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return
    args.func(args)


if __name__ == "__main__":
    main()
