# Console mode: shows the Linux text console tty3 on the 3.5" screen, to use the computer without an HDMI monitor.
# Plug in a USB keyboard, press Ctrl+Alt+F3, log in and type commands: the text appears on the small screen.
#
# Reads the text console through /dev/vcsa3 (size, cursor, colours) and /dev/vcsu3 (Unicode characters), and only
# redraws the rows that changed (a full redraw of the rev. A screen takes ~2 s, one text row ~0.1 s).
# Read access to those devices comes from the "tty" group (setup-root.sh). Once someone is logged in on tty3 the
# console belongs to that user, and it is resized to the 60x19 cells of the small screen.

import errno
import fcntl
import os
import struct
import termios
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from i18n import tr

VT = 3
CELL_W, CELL_H = 8, 16
COLS, ROWS = 60, 19  # 480 x 304 px of console + a 16 px status row at the bottom
SCREEN_W = COLS * CELL_W
FONTS = Path(__file__).resolve().parent.parent / "app" / "res" / "fonts"
SETUP_ROOT = str(Path(__file__).resolve().parent.parent / "setup-root.sh").replace(str(Path.home()), "~", 1)

# Linux console colours, in the VGA order used by the attribute bytes of /dev/vcsa
PALETTE = [(0, 0, 0), (0, 0, 170), (0, 170, 0), (0, 170, 170), (170, 0, 0), (170, 0, 170), (170, 85, 0),
           (170, 170, 170), (85, 85, 85), (85, 85, 255), (85, 255, 85), (85, 255, 255), (255, 85, 85),
           (255, 85, 255), (255, 255, 85), (255, 255, 255)]
STATUS_BG, STATUS_FG = (21, 55, 66), (165, 243, 252)


class ConsoleUnavailable(Exception):
    pass


def read_console():
    """(rows, cols, cursor_x, cursor_y, chars, attrs) of tty3; ConsoleUnavailable with the reason otherwise"""
    try:
        with open(f"/dev/vcsa{VT}", "rb") as f:
            header_and_cells = f.read()
        with open(f"/dev/vcsu{VT}", "rb") as f:
            unicode_cells = f.read()
    except PermissionError:
        raise ConsoleUnavailable("permission")
    except OSError as e:
        raise ConsoleUnavailable("closed" if e.errno == errno.ENXIO else str(e))
    rows, cols, cursor_x, cursor_y = header_and_cells[:4]
    count = min(rows * cols, len(unicode_cells) // 4, (len(header_and_cells) - 4) // 2)
    chars = struct.unpack(f"={count}I", unicode_cells[:count * 4])
    attrs = header_and_cells[5:4 + 2 * count:2]
    return rows, cols, cursor_x, cursor_y, chars, attrs


def fit_console_size():
    """Resize tty3 to the small screen once it belongs to the logged-in user (programs then wrap at 60 columns)"""
    tty = f"/dev/tty{VT}"
    try:
        if os.stat(tty).st_uid != os.getuid():
            return
        fd = os.open(tty, os.O_WRONLY | os.O_NOCTTY | os.O_NONBLOCK)
        try:
            rows, cols = struct.unpack("HHHH", fcntl.ioctl(fd, termios.TIOCGWINSZ, bytes(8)))[:2]
            if (rows, cols) != (ROWS, COLS):
                fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLS, 0, 0))
        finally:
            os.close(fd)
    except OSError:
        pass


def active_vt():
    try:
        return Path("/sys/class/tty/tty0/active").read_text().strip()
    except OSError:
        return ""


def logged_in():
    try:
        return os.stat(f"/dev/tty{VT}").st_uid != 0
    except OSError:
        return False


class ConsoleRenderer:
    def __init__(self, lcd):
        self.lcd = lcd
        self.font = ImageFont.truetype(str(FONTS / "jetbrains-mono/JetBrainsMono-Regular.ttf"), 13)
        self.bold = ImageFont.truetype(str(FONTS / "jetbrains-mono/JetBrainsMono-Bold.ttf"), 13)
        self.shown_rows = [None] * ROWS
        self.shown_status = None
        self.shown_message = None

    def row_image(self, cells):
        img = Image.new("RGB", (SCREEN_W, CELL_H), PALETTE[0])
        d = ImageDraw.Draw(img)
        for col, (char, attr, cursor) in enumerate(cells):
            fg, bg = PALETTE[attr & 0x0F], PALETTE[(attr >> 4) & 0x07]
            if cursor:
                fg, bg = bg, (229, 231, 235)
            x = col * CELL_W
            if bg != PALETTE[0]:
                d.rectangle([x, 0, x + CELL_W - 1, CELL_H - 1], fill=bg)
            if char > 32:
                d.text((x + CELL_W / 2, CELL_H / 2), chr(char), font=self.bold if attr & 0x08 else self.font,
                       fill=fg, anchor="mm")
        return img

    def draw_rows(self, first, images):
        block = Image.new("RGB", (SCREEN_W, CELL_H * len(images)))
        for i, img in enumerate(images):
            block.paste(img, (0, i * CELL_H))
        self.lcd.DisplayPILImage(block, 0, first * CELL_H)

    def show_console(self, snapshot):
        rows, cols, cursor_x, cursor_y, chars, attrs = snapshot
        wanted = []
        for r in range(ROWS):
            cells = []
            for c in range(COLS):
                i = r * cols + c
                if r < rows and c < cols and i < len(chars):
                    cells.append((chars[i], attrs[i], (c, r) == (cursor_x, cursor_y)))
                else:
                    cells.append((32, 0x07, False))
            wanted.append(tuple(cells))
        self.shown_message = None
        # Redraw consecutive changed rows as one block
        r = 0
        while r < ROWS:
            if wanted[r] == self.shown_rows[r]:
                r += 1
                continue
            first = r
            while r < ROWS and wanted[r] != self.shown_rows[r]:
                r += 1
            self.draw_rows(first, [self.row_image(cells) for cells in wanted[first:r]])
            self.shown_rows[first:r] = wanted[first:r]

    def show_message(self, lines, qr=None):
        # Full-screen explanation (no console to show yet), with the QR code of the web panel on the right if given
        key = (tuple(lines), qr[2] if qr else None)
        if key == self.shown_message:
            return
        img = Image.new("RGB", (SCREEN_W, ROWS * CELL_H), (12, 16, 28))
        d = ImageDraw.Draw(img)
        title = ImageFont.truetype(str(FONTS / "roboto/Roboto-Bold.ttf"), 22)
        body = ImageFont.truetype(str(FONTS / "roboto/Roboto-Regular.ttf"), 16 if not qr else 14)
        if qr:
            card, mask, _ = qr
            x = SCREEN_W - card.width - 20
            y = (ROWS * CELL_H - card.height) // 2 - 10
            img.paste(card, (x, y), mask)
            d.text((x + card.width / 2, y + card.height + 14), tr("Quét để quản lý", "Scan to manage"), font=body,
                   fill=(148, 163, 184), anchor="mm")
            text_x, anchor = 20, "lm"
        else:
            text_x, anchor = SCREEN_W / 2, "mm"
        d.text((text_x, 90), lines[0], font=title, fill=(229, 231, 235), anchor=anchor)
        for i, line in enumerate(lines[1:]):
            d.text((text_x, 136 + i * 26), line, font=body, fill=(148, 163, 184), anchor=anchor)
        self.lcd.DisplayPILImage(img, 0, 0)
        self.shown_message = key
        self.shown_rows = [None] * ROWS

    def show_status(self, text):
        if text == self.shown_status:
            return
        img = Image.new("RGB", (SCREEN_W, CELL_H), STATUS_BG)
        ImageDraw.Draw(img).text((6, CELL_H / 2), text, font=self.font, fill=STATUS_FG, anchor="lm")
        self.lcd.DisplayPILImage(img, 0, ROWS * CELL_H)
        self.shown_status = text


def how_to(beside_qr):
    if beside_qr:  # narrower lines next to the QR code
        return [tr("Chế độ dòng lệnh", "Console mode"), tr("Cắm bàn phím USB,", "Plug in a USB keyboard,"),
                tr("bấm Ctrl+Alt+F3 để đăng nhập", "press Ctrl+Alt+F3 to log in"),
                tr("và gõ lệnh trên màn này", "and type commands here")]
    return [tr("Chế độ dòng lệnh", "Console mode"),
            tr("Cắm bàn phím USB rồi bấm Ctrl+Alt+F3", "Plug in a USB keyboard and press Ctrl+Alt+F3"),
            tr("để đăng nhập và gõ lệnh trên màn này", "to log in and type commands on this screen")]


def run_console(lcd, stop, primary_ipv4, web_qr=None):
    """web_qr() -> (card, mask, url) of the web panel QR code, or None when the panel is not open to the network"""
    renderer = ConsoleRenderer(lcd)
    ip, qr, checked = "", None, 0.0
    while not stop.is_set():
        if time.monotonic() - checked > 5:
            ip, checked = primary_ipv4() or tr("không có mạng", "no network"), time.monotonic()
            qr = web_qr() if web_qr else None
        try:
            fit_console_size()
            snapshot = read_console()
            if any(char > 32 for char in snapshot[4]):
                renderer.show_console(snapshot)
            else:
                # Nothing on tty3 until someone switches to it (getty starts then)
                renderer.show_message(how_to(qr is not None), qr)
            if active_vt() != f"tty{VT}":
                status = f"Ctrl+Alt+F{VT}: " + tr("gõ lệnh trên màn này", "console on this screen") + f"   IP {ip}"
            elif not logged_in():
                status = f"tty{VT}: " + tr("đăng nhập bằng tài khoản Ubuntu", "log in with your account") + f"   IP {ip}"
            else:
                status = f"tty{VT}   IP {ip}   {time.strftime('%H:%M')}"
        except ConsoleUnavailable as e:
            if str(e) == "permission":
                renderer.show_message([tr("Chưa có quyền đọc dòng lệnh", "No permission to read the console"),
                                       tr("Chạy một lần: ", "Run once: ") + f"sudo {SETUP_ROOT}",
                                       tr("rồi khởi động lại máy", "then restart the computer")])
            else:
                renderer.show_message(how_to(qr is not None), qr)
            status = f"IP {ip}"
        renderer.show_status(status)
        stop.wait(0.1)
