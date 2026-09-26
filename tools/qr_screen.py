# QR code screen: scan it with a phone to open the web panel, with the keyboard shortcuts next to it.
# Used by the "QR code" main screen, "igam3-screen qr" (shortcut Ctrl+Alt+Q) and the waiting screen of the console mode.

import os
from pathlib import Path

import qrcode
from PIL import Image, ImageDraw, ImageFont

from i18n import tr

FONTS = Path(__file__).resolve().parent.parent / "app" / "res" / "fonts"
W, H = 480, 320
BG = (12, 16, 28)
TEXT, SUB, MUTED = (229, 231, 235), (148, 163, 184), (100, 116, 139)
CYAN, WARN, CARD_EDGE = (34, 211, 238), (251, 191, 36), (36, 50, 76)


def shortcuts():
    keys = [("Ctrl+Alt+Q", tr("Hiện mã QR này", "This QR code"))]
    if os.name != "nt":
        keys += [("Ctrl+Alt+F3", tr("Dòng lệnh (tty3)", "Console (tty3)")), ("Ctrl+Alt+F2", tr("Về desktop", "Back to desktop"))]
    return keys


def font(name, size):
    return ImageFont.truetype(str(FONTS / name), size)


def fit(draw, text, name, size, max_w, min_size=9):
    while size > min_size and draw.textlength(text, font=font(name, size)) > max_w:
        size -= 1
    return font(name, size)


def qr_card(url, size):
    """White square card with the QR code of url: modules as large as the card allows, 2-module quiet zone"""
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=0)
    qr.add_data(url)
    qr.make(fit=True)
    matrix = qr.get_matrix()
    n = len(matrix)
    module = size // (n + 4)
    offset = (size - n * module) // 2
    card = Image.new("RGB", (size, size), "white")
    d = ImageDraw.Draw(card)
    for y, row in enumerate(matrix):
        for x, dark in enumerate(row):
            if dark:
                d.rectangle([offset + x * module, offset + y * module,
                             offset + (x + 1) * module - 1, offset + (y + 1) * module - 1], fill="black")
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius=12, fill=255)
    return card, mask


def panel_url(ip, port):
    return f"http://{ip}:{port}" if ip else None


def make_qr_screen(ip, port, lan_on, title):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    size, x0 = 232, 16
    y0 = (H - size) // 2
    url = panel_url(ip, port)
    if url and lan_on:
        card, mask = qr_card(url, size)
        img.paste(card, (x0, y0), mask)
    else:
        d.rounded_rectangle([x0, y0, x0 + size - 1, y0 + size - 1], radius=12, outline=CARD_EDGE, width=2)
        d.text((x0 + size / 2, y0 + size / 2 - 12), tr("Chưa có mã QR", "No QR code yet"),
               font=font("roboto/Roboto-Bold.ttf", 18), fill=SUB, anchor="mm")
        d.text((x0 + size / 2, y0 + size / 2 + 14),
               tr("không có mạng", "no network") if not ip else tr("chưa mở cho điện thoại", "not open to phones yet"),
               font=font("roboto/Roboto-Regular.ttf", 14), fill=MUTED, anchor="mm")

    tx = x0 + size + 20
    tw = W - tx - 12
    d.text((tx, 40), title, font=fit(d, title, "roboto/Roboto-Bold.ttf", 20, tw, 13), fill=TEXT, anchor="lt")
    scan = tr("Quét mã để quản lý màn hình", "Scan to manage this screen")
    d.text((tx, 70), scan, font=fit(d, scan, "roboto/Roboto-Regular.ttf", 13, tw), fill=SUB, anchor="lt")
    d.text((tx, 100), tr("ĐỊA CHỈ", "ADDRESS"), font=font("roboto/Roboto-Bold.ttf", 10), fill=MUTED, anchor="lt")
    address = f"{ip}:{port}" if ip else tr("không có mạng", "no network")
    d.text((tx, 114), address, font=fit(d, address, "jetbrains-mono/JetBrainsMono-Bold.ttf", 14, tw),
           fill=CYAN, anchor="lt")
    regular, mono = "roboto/Roboto-Regular.ttf", "jetbrains-mono/JetBrainsMono-Regular.ttf"
    if url and lan_on:
        lines, color = [(tr("Đăng nhập: tên bất kỳ", "Sign in: any user name"), regular),
                        (tr("và mật khẩu của bạn", "and your password"), regular)], TEXT
    elif url:
        lines, color = [(tr("Chưa mở cho điện thoại:", "Not open to phones yet:"), regular),
                        ("igam3-screen web --lan on", mono)], WARN
    else:
        lines, color = [(tr("Kiểm tra Wi-Fi hoặc", "Check the Wi-Fi"), regular),
                        (tr("cáp mạng LAN", "or the network cable"), regular)], WARN
    for i, (line, name) in enumerate(lines):
        d.text((tx, 142 + i * 17), line, font=fit(d, line, name, 12, tw), fill=color, anchor="lt")

    d.text((tx, 192), tr("PHÍM TẮT", "SHORTCUTS"), font=font("roboto/Roboto-Bold.ttf", 10), fill=MUTED, anchor="lt")
    key_font, desc_font = font("jetbrains-mono/JetBrainsMono-Bold.ttf", 11), font("roboto/Roboto-Regular.ttf", 12)
    for i, (key, desc) in enumerate(shortcuts()):
        y = 210 + i * 20
        d.text((tx, y), key, font=key_font, fill=CYAN, anchor="lt")
        d.text((tx + 84, y), desc, font=desc_font, fill=TEXT, anchor="lt")
    return img
