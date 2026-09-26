#!/usr/bin/env python3
# Web panel of the iGam3 screen: http://localhost:8686
#   By default it only opens on this computer ("igam3-screen panel" or the "iGam3 Screen" icon).
#   Opening it to phones on the local network is the user's own choice: "igam3-screen web --lan on" (needs a password).
# Every action runs the igam3-screen command line, so the panel and the CLI always behave the same.

import argparse
import base64
import hashlib
import hmac
import io
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import i18n
import igam3_screen as core
from i18n import tr
from platform_support import WINDOWS, background_kwargs, no_window_kwargs, watch_stop_file

WEB_DIR = core.TOOLS / "web"
UPLOADS = core.ROOT / "uploads"
SPLASH_PREVIEW = core.RUNTIME / "splash-preview.png"
MAX_UPLOAD = 20 * 1024 * 1024
UPLOAD_SLOTS = ("image", "background", "logo", "photo")
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
LOCAL_CLIENTS = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}
LOCAL_HOST_NAMES = {"localhost", "127.0.0.1", "[::1]"}

LANGUAGE_CHOICES = ("auto", "vi", "en")


def no_password_page():
    return f"""<!doctype html><html lang="{i18n.LANG}"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>iGam3 Screen</title>
<body style="font-family:system-ui;background:#0b0f1a;color:#e5e7eb;padding:24px;line-height:1.6">
<h2>{tr("Chưa đặt mật khẩu", "No password yet")}</h2>
<p>{tr("Để mở giao diện từ điện thoại hoặc máy khác, cần đặt mật khẩu trước theo một trong hai cách:",
       "To open this panel from a phone or another computer, set a password first, in one of two ways:")}</p>
<ul><li>{tr('Trên máy iGam3, mở <b>http://localhost:8686</b> và đặt mật khẩu ở mục "Truy cập từ điện thoại".',
            'On the iGam3 itself, open <b>http://localhost:8686</b> and set it under "Access from a phone".')}</li>
<li>{tr("Hoặc chạy lệnh:", "Or run:")} <code>igam3-screen web --password</code></li></ul></body></html>"""

_verified = set()  # Authorization headers already accepted: PBKDF2 is slow, check each one only once
_action_lock = threading.Lock()  # one change of the screen at a time
_last_request = time.monotonic()


def run_cli(*args, timeout=180):
    result = subprocess.run([str(core.VENV_PYTHON), str(core.TOOLS / "igam3_screen.py"), *args],
                            capture_output=True, text=True, encoding="utf8", errors="replace", timeout=timeout,
                            env=dict(os.environ, PYTHONIOENCODING="utf8"), **no_window_kwargs())
    return result.returncode == 0, (result.stdout + result.stderr).strip()


def password_config():
    data = core.load_yaml_dict(core.WEB_CONFIG, {}) if core.WEB_CONFIG.is_file() else {}
    return data if data.get("salt") and data.get("hash") else None


def uploaded(slot):
    files = sorted(UPLOADS.glob(f"{slot}.*"), key=lambda p: p.stat().st_mtime) if UPLOADS.is_dir() else []
    return files[-1] if files else None


def do_action(data):
    """(ok, message) for one change requested by the page"""
    action = data.get("action")
    text = lambda key: str(data.get(key) or "")
    if action == "mode" and data.get("mode") in core.MODES:
        return run_cli("mode", data["mode"])
    if action == "power":
        return run_cli("start" if data.get("on") else "off")
    if action == "qr_now":
        # Runs for a minute, then gives the screen back: do not keep the page waiting
        subprocess.Popen([str(core.VENV_PYTHONW), str(core.TOOLS / "igam3_screen.py"), "qr", "--seconds", "60"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         **background_kwargs())
        return True, tr("Màn nhỏ đang hiện mã QR trong 1 phút", "The small screen shows the QR code for 1 minute")
    if action == "language" and data.get("language") in LANGUAGE_CHOICES:
        return run_cli("language", data["language"])
    if action == "autostart":
        return run_cli("autostart", "on" if data.get("on") else "off")
    if action == "blocks" and isinstance(data.get("blocks"), dict):
        return run_cli("blocks", *[f"{k}={'on' if v else 'off'}" for k, v in data["blocks"].items()])
    if action == "title":
        return run_cli("title", "--", text("title"), text("tag"))
    if action == "background":
        if data.get("remove"):
            return run_cli("background", "--none")
        file = uploaded("background")
        return run_cli("background", str(file)) if file else (False, tr("Chưa chọn ảnh nền", "No background picture chosen"))
    if action == "image":
        file = uploaded("image")
        if not file:
            return False, tr("Chưa chọn ảnh", "No picture chosen")
        return run_cli("image", str(file), "--keep", *(["--fill"] if data.get("fill") else []))
    if action == "splash":
        options = []
        for slot in ("logo", "photo"):
            if data.get(slot):
                file = uploaded(slot)
                if not file:
                    return False, (tr("Chưa chọn logo", "No logo chosen") if slot == "logo"
                                   else tr("Chưa chọn ảnh nền", "No background photo chosen"))
                options += [f"--{slot}", str(file)]
        options += ["--keep"] if data.get("keep") else ["--out", str(SPLASH_PREVIEW)]
        return run_cli("splash", *options, "--", text("title"), text("subtitle"), text("footer"))
    if action == "brightness":
        level = int(data.get("level", -1))
        return run_cli("brightness", str(level)) if 0 <= level <= 100 else (False, tr("Độ sáng phải từ 0 đến 100", "Brightness must be between 0 and 100"))
    if action == "rotate":
        return run_cli("rotate", "on" if data.get("on") else "off")
    if action == "theme" and text("name"):
        return run_cli("theme", text("name"))
    if action == "password":
        if len(text("password")) < 6:
            return False, tr("Mật khẩu cần ít nhất 6 ký tự", "The password needs at least 6 characters")
        core.set_web_password(text("password"))
        _verified.clear()
        return True, tr("Đã đổi mật khẩu. Tên đăng nhập bất kỳ, ví dụ: admin",
                        "Password changed. Any user name works, for example: admin")
    return False, tr("Yêu cầu không hợp lệ", "Invalid request")


class Handler(BaseHTTPRequestHandler):
    server_version = "igam3-screen"

    def log_message(self, fmt, *args):
        pass  # keep the journal quiet

    # ------------------------------------------------------------ responses

    def send_body(self, status, body, content_type, extra=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, obj, status=HTTPStatus.OK):
        self.send_body(status, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def send_file(self, path, content_type):
        if not path.is_file():
            self.send_body(HTTPStatus.NOT_FOUND, b"", "text/plain")
            return
        self.send_body(HTTPStatus.OK, path.read_bytes(), content_type)

    # ------------------------------------------------------------ access control

    def host_name(self):
        host = self.headers.get("Host", "")
        return host.split("]")[0] + "]" if host.startswith("[") else host.rsplit(":", 1)[0]

    def authorized(self):
        global _last_request
        _last_request = time.monotonic()
        i18n.refresh()  # the language may have changed since the panel started
        config = password_config()
        if config is None:
            # No password yet: this machine only, through a local host name (a remote page cannot rebind to it)
            if self.client_address[0] in LOCAL_CLIENTS and self.host_name() in LOCAL_HOST_NAMES:
                return True
            self.send_body(HTTPStatus.FORBIDDEN, no_password_page().encode(), "text/html; charset=utf-8")
            return False
        header = self.headers.get("Authorization", "")
        key = hashlib.sha256((config["hash"] + header).encode()).hexdigest()
        if key in _verified:
            return True
        if header.startswith("Basic "):
            try:
                password = base64.b64decode(header[6:]).decode("utf8").partition(":")[2]
            except ValueError:
                password = None
            if password is not None:
                digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(config["salt"]), 200_000)
                if hmac.compare_digest(digest.hex(), config["hash"]):
                    _verified.add(key)
                    return True
        self.send_body(HTTPStatus.UNAUTHORIZED, tr("Cần mật khẩu", "Password required").encode(), "text/plain; charset=utf-8",
                       {"WWW-Authenticate": 'Basic realm="iGam3 Screen", charset="UTF-8"'})
        return False

    def same_origin(self):
        # Changes need a custom header (other sites cannot send it without a CORS preflight we never answer)
        if self.headers.get("X-Igam3") != "1":
            return False
        origin = self.headers.get("Origin")
        return origin is None or urllib.parse.urlsplit(origin).netloc == self.headers.get("Host")

    # ------------------------------------------------------------ routes

    def do_GET(self):
        if not self.authorized():
            return
        path = urllib.parse.urlsplit(self.path).path
        if path == "/":
            page = (WEB_DIR / "index.html").read_text(encoding="utf8")
            page = page.replace('<html lang="en">', f'<html lang="{i18n.LANG}">', 1)  # the page picks its texts from it
            self.send_body(HTTPStatus.OK, page.encode(), "text/html; charset=utf-8")
        elif path == "/api/state":
            state = core.status_dict()
            state["preview"] = core.PREVIEW.is_file()
            self.send_json(state)
        elif path == "/screen.png":
            self.send_file(core.PREVIEW, "image/png")
        elif path == "/splash-preview.png":
            self.send_file(SPLASH_PREVIEW, "image/png")
        else:
            self.send_body(HTTPStatus.NOT_FOUND, b"", "text/plain")

    def do_POST(self):
        if not self.authorized():
            return
        if not self.same_origin():
            self.send_json({"ok": False, "message": tr("Yêu cầu bị từ chối", "Request refused")}, HTTPStatus.FORBIDDEN)
            return
        url = urllib.parse.urlsplit(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_UPLOAD:
            self.send_json({"ok": False, "message": tr("File quá lớn (tối đa 20 MB)", "File too large (20 MB at most)")},
                           HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return
        body = self.rfile.read(length)
        if url.path == "/api/upload":
            self.send_json(self.save_upload(dict(urllib.parse.parse_qsl(url.query)), body))
        elif url.path == "/api/action":
            try:
                data = json.loads(body or b"{}")
            except ValueError:
                data = {}
            with _action_lock:
                try:
                    ok, message = do_action(data)
                except (ValueError, subprocess.TimeoutExpired) as e:
                    ok, message = False, str(e)
                except Exception as e:  # tell the page instead of dropping the connection
                    ok, message = False, f"{type(e).__name__}: {e}"
            self.send_json({"ok": ok, "message": message})
        else:
            self.send_body(HTTPStatus.NOT_FOUND, b"", "text/plain")

    def save_upload(self, query, body):
        from PIL import Image
        slot, ext = query.get("slot"), Path(query.get("name", "")).suffix.lower()
        if slot not in UPLOAD_SLOTS or ext not in IMAGE_EXTS:
            return {"ok": False, "message": tr("Chỉ nhận ảnh PNG, JPG, GIF, WEBP hoặc BMP",
                                               "Only PNG, JPG, GIF, WEBP or BMP pictures")}
        try:
            with Image.open(io.BytesIO(body)) as img:
                img.verify()
        except Exception:
            return {"ok": False, "message": tr("File này không phải ảnh hợp lệ", "This file is not a valid picture")}
        UPLOADS.mkdir(exist_ok=True)
        for old in UPLOADS.glob(f"{slot}.*"):
            old.unlink()
        (UPLOADS / f"{slot}{ext}").write_bytes(body)
        return {"ok": True, "message": tr("Đã tải ảnh lên", "Picture uploaded")}


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True


class LanServer(LocalServer):
    address_family = socket.AF_INET6  # "::" also accepts IPv4 clients (as ::ffff:a.b.c.d)

    def server_bind(self):
        self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        super().server_bind()


def stop_when_idle(server, minutes):
    while time.monotonic() - _last_request < minutes * 60:
        time.sleep(30)
    server.shutdown()


if __name__ == "__main__":
    if sys.stdout is None:  # pythonw.exe on Windows has no console: keep the messages in a log file
        core.RUNTIME.mkdir(parents=True, exist_ok=True)
        sys.stdout = sys.stderr = open(core.RUNTIME / "web-panel.log", "a", encoding="utf8", buffering=1)
    parser = argparse.ArgumentParser(description="iGam3 screen web panel")
    parser.add_argument("--lan", action="store_true", help="listen on every network interface (needs a password)")
    parser.add_argument("--idle-exit", type=int, default=0, metavar="MIN", help="stop after MIN minutes without use")
    args = parser.parse_args()
    if args.lan and password_config() is None:
        sys.exit(tr("Mở cho mạng LAN cần mật khẩu: igam3-screen web --password",
                    "Opening the panel to the local network needs a password: igam3-screen web --password"))
    if args.lan:
        server = LanServer(("::", core.WEB_PORT), Handler)
    else:
        server = LocalServer(("127.0.0.1", core.WEB_PORT), Handler)
    if args.idle_exit:
        threading.Thread(target=stop_when_idle, args=(server, args.idle_exit), daemon=True).start()
    if WINDOWS and args.lan:
        watch_stop_file("web", server.shutdown)  # "igam3-screen web --lan off" on Windows
    where = tr("mạng LAN", "local network") if args.lan else tr("chỉ máy này", "this computer only")
    print(tr("Giao diện quản lý", "Web panel") + f" ({where}): http://localhost:{core.WEB_PORT}", flush=True)
    server.serve_forever()
