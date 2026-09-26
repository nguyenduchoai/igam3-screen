#!/usr/bin/env python3
# Generates background.png + theme.yaml for the "iGam3" theme (Turing Smart Screen 3.5", landscape 480x320).
# Layout coordinates live only here, so the background and the live values always line up.
# Header text, background photo and the blocks switched on come from custom.yaml
# (edited by 'igam3-screen title / background / blocks' or the web panel).
# Run from anywhere:  ~/igam3-screen/.venv/bin/python ~/igam3-screen/app/res/themes/iGam3/make_theme.py
# Values marked "Igam3..." come from library/sensors/sensors_custom.py

from pathlib import Path

import yaml
from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps

THEME_DIR = Path(__file__).resolve().parent
FONTS = THEME_DIR.parent.parent / "fonts"
CUSTOM_FILE = THEME_DIR / "custom.yaml"

# Blocks that can be switched on/off, with the names shown by the CLI and the web panel
BLOCKS = {
    "clock": "Đồng hồ",
    "hostname": "Tên máy",
    "cpu": "CPU",
    "ram": "RAM",
    "ssd": "SSD",
    "network": "Mạng",
    "system": "Hệ thống",
}

W, H = 480, 320
SS = 4  # supersampling factor for smooth shapes

# Palette
BG_TOP = (14, 20, 34)
BG_BOTTOM = (8, 11, 19)
PANEL = (18, 25, 40)
BORDER = (36, 50, 76)
TRACK = (38, 50, 72)
TEXT = (229, 231, 235)
SUB = (148, 163, 184)
MUTED = (100, 116, 139)
CYAN = (34, 211, 238)
VIOLET = (167, 139, 250)
AMBER = (251, 191, 36)
BLUE = (96, 165, 250)
GREEN = (52, 211, 153)
ORANGE = (251, 146, 60)
PILL_BG = (21, 55, 66)

ROBOTO_BOLD = "roboto/Roboto-Bold.ttf"
ROBOTO_MEDIUM = "roboto/Roboto-Medium.ttf"
ROBOTO = "roboto/Roboto-Regular.ttf"
MONO_BOLD = "jetbrains-mono/JetBrainsMono-Bold.ttf"
MONO = "jetbrains-mono/JetBrainsMono-Regular.ttf"

# Background photo: darkened, panels drawn semi-transparent on top of it
PHOTO_BRIGHTNESS = 0.6
PHOTO_PANEL_ALPHA = 205

# Layout
MARGIN = 12
HEADER_DIVIDER_Y = 49
BODY_TOP, BODY_BOTTOM = 57, 308
ROW_GAP, COL_GAP = 8, 6
GAUGE_PANEL_H, BOTTOM_PANEL_H = 139, 104
BOTTOM_PAIR_WIDTHS = (228, 222)  # network + system side by side
GAUGE_DY, GAUGE_R, GAUGE_W = 77, 41, 8

GAUGES = [
    # block, title, accent colour, custom data class drawn as the gauge (subtitles come from hardware_labels())
    ("cpu", "CPU", CYAN, "Igam3CpuPercent"),
    ("ram", "RAM", VIOLET, "Igam3RamPercent"),
    ("ssd", "SSD", AMBER, "Igam3DiskPercent"),
]
RAM_SIZES_GB = (1, 2, 4, 6, 8, 12, 16, 24, 32, 48, 64, 96, 128, 192, 256)


def hardware_labels():
    """Subtitles of the CPU / RAM / SSD panels, read from the machine the theme is generated on"""
    import os
    import re
    import psutil
    labels = {"cpu": "", "ram": "", "ssd": ""}
    try:
        if os.name == "nt":
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
                name = winreg.QueryValueEx(key, "ProcessorNameString")[0]
        else:
            with open("/proc/cpuinfo", encoding="utf8") as f:
                name = next(line.split(":", 1)[1] for line in f if line.startswith("model name"))
        name = re.sub(r"\((R|TM)\)|\bCPU\b|\bProcessor\b|\d+-Core|@.*$|with .*$", "", name, flags=re.I)
        labels["cpu"] = " ".join(name.split())
    except (OSError, StopIteration):
        pass
    gb = psutil.virtual_memory().total / 1e9  # usable memory is a bit below the installed size
    labels["ram"] = f"{next((s for s in RAM_SIZES_GB if s >= gb), round(gb))} GB"
    try:
        # Whole disk that holds the system, not just its partition (Linux)
        device = next(p.device for p in psutil.disk_partitions() if p.mountpoint == "/")
        block = Path("/sys/class/block") / os.path.basename(os.path.realpath(device))
        disk = block.resolve().parent.name if (block / "partition").exists() else block.name
        size = int((Path("/sys/class/block") / disk / "size").read_text()) * 512
    except (OSError, StopIteration, ValueError):
        size = psutil.disk_usage(Path.home().anchor if os.name == "nt" else "/").total
    gb = size / 1e9
    labels["ssd"] = f"{gb / 1000:.1f}".rstrip("0").rstrip(".") + " TB" if gb >= 1000 else f"{round(gb)} GB"
    return labels


def font(name, size):
    return ImageFont.truetype(str(FONTS / name), size)


def rgb(c):
    return f"{c[0]}, {c[1]}, {c[2]}"


def load_custom():
    custom = {"title": "iGam3 M1", "tag": "DePIN NODE", "background": "", "blocks": {k: True for k in BLOCKS}}
    if CUSTOM_FILE.is_file():
        with open(CUSTOM_FILE, encoding="utf8") as f:
            data = yaml.safe_load(f) or {}
        for key in ("title", "tag", "background"):
            if data.get(key) is not None:
                custom[key] = str(data[key])
        for key, on in (data.get("blocks") or {}).items():
            if key in BLOCKS:
                custom["blocks"][key] = bool(on)
    return custom


def compute_layout(blocks):
    """Panels of the visible blocks: rows share the body height, panels share their row width"""
    gauges = [g for g in GAUGES if blocks[g[0]]]
    bottoms = [key for key in ("network", "system") if blocks[key]]
    rows = ([GAUGE_PANEL_H] if gauges else []) + ([BOTTOM_PANEL_H] if bottoms else [])
    y = BODY_TOP + (BODY_BOTTOM - BODY_TOP - sum(rows) - ROW_GAP * (len(rows) - 1)) // 2
    layout = {"gauges": [], "bottoms": []}
    if gauges:
        w = (W - 2 * MARGIN - COL_GAP * (len(gauges) - 1)) // len(gauges)
        layout["gauges"] = [(g, MARGIN + i * (w + COL_GAP), y, w) for i, g in enumerate(gauges)]
        y += GAUGE_PANEL_H + ROW_GAP
    x = MARGIN
    for key, w in zip(bottoms, BOTTOM_PAIR_WIDTHS if len(bottoms) == 2 else (W - 2 * MARGIN,)):
        layout["bottoms"].append((key, x, y, w))
        x += w + COL_GAP
    # Nothing but the clock left: show it big in the middle instead of in the header
    layout["big_clock"] = blocks["clock"] and not gauges and not bottoms
    layout["header_clock"] = blocks["clock"] and not layout["big_clock"]
    return layout


def fit_text(draw, text, name, size, max_w, min_size):
    """Shrink the font until text fits max_w; below min_size, cut the text and add an ellipsis"""
    while size > min_size and draw.textlength(text, font=font(name, size)) > max_w:
        size -= 1
    fnt = font(name, size)
    if draw.textlength(text, font=fnt) > max_w:
        while text and draw.textlength(text + "…", font=fnt) > max_w:
            text = text[:-1]
        text = text.rstrip() + "…"
    return text, fnt


def base_layer(custom):
    """(RGB image at SS resolution, panel alpha): background photo if configured, else the dark gradient"""
    photo = THEME_DIR / custom["background"] if custom["background"] else None
    if photo and photo.is_file():
        img = ImageOps.fit(ImageOps.exif_transpose(Image.open(photo)).convert("RGB"), (W * SS, H * SS), Image.LANCZOS)
        return ImageEnhance.Brightness(img).enhance(PHOTO_BRIGHTNESS), PHOTO_PANEL_ALPHA
    if photo:
        print(f"Background photo {photo} not found: using the default gradient")
    img = Image.new("RGB", (W * SS, H * SS))
    d = ImageDraw.Draw(img)
    for y in range(H * SS):
        t = y / (H * SS - 1)
        d.line([(0, y), (W * SS, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOTTOM)))
    return img, 255


def draw_header(d, title, tag, max_x):
    x = 14
    avail = max_x - x
    if tag:
        tag, tag_font = fit_text(d, tag, ROBOTO_BOLD, 9, 140, 8)
        pill_w = d.textlength(tag, font=tag_font) + 14
        avail -= pill_w + 9
    if title:
        title, title_font = fit_text(d, title, ROBOTO_BOLD, 21, avail, 13)
        d.text((x, 17), title, font=title_font, fill=TEXT, anchor="lm")
        x += d.textlength(title, font=title_font) + 9
    if tag:
        d.rounded_rectangle([x, 10, x + pill_w, 26], radius=8, fill=PILL_BG)
        d.text((x + pill_w / 2, 18), tag, font=tag_font, fill=CYAN, anchor="mm")


def draw_background(custom, layout):
    # Shapes at SS x resolution on a transparent layer, composited over the base, then downscaled for anti-aliasing
    base, panel_alpha = base_layer(custom)
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    if panel_alpha < 255:
        # Darken the top of the photo so the header text stays readable
        for y in range((HEADER_DIVIDER_Y + 8) * SS):
            d.line([(0, y), (W * SS, y)], fill=(0, 0, 0, int(170 * (1 - y / ((HEADER_DIVIDER_Y + 8) * SS)))))

    def panel(x, y, w, h):
        d.rounded_rectangle([x * SS, y * SS, (x + w) * SS - 1, (y + h) * SS - 1], radius=10 * SS,
                            fill=PANEL + (panel_alpha,), outline=BORDER + (255,), width=SS)

    for _, x, y, w in layout["gauges"]:
        panel(x, y, w, GAUGE_PANEL_H)
    for _, x, y, w in layout["bottoms"]:
        panel(x, y, w, BOTTOM_PANEL_H)
    d.line([(MARGIN * SS, HEADER_DIVIDER_Y * SS), ((W - MARGIN) * SS, HEADER_DIVIDER_Y * SS)],
           fill=BORDER + (255,), width=SS)

    big = Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")
    img = big.resize((W, H), Image.LANCZOS)
    d = ImageDraw.Draw(img)

    draw_header(d, custom["title"], custom["tag"], 318 if layout["header_clock"] else W - 14)

    labels = hardware_labels() if layout["gauges"] else {}
    for (key, title, accent, _), x, y, w in layout["gauges"]:
        d.text((x + 12, y + 9), title, font=font(ROBOTO_BOLD, 12), fill=accent, anchor="lt")
        title_w = d.textlength(title, font=font(ROBOTO_BOLD, 12))
        subtitle, sub_font = fit_text(d, labels[key], ROBOTO, 10, w - 36 - title_w, 8)
        d.text((x + w - 12, y + 10), subtitle, font=sub_font, fill=MUTED, anchor="rt")

    for key, x, y, w in layout["bottoms"]:
        row1, row2 = y + 42, y + 76
        if key == "network":
            d.text((x + 12, y + 9), "MẠNG", font=font(ROBOTO_BOLD, 12), fill=BLUE, anchor="lt")
            for label, cy in (("Wi-Fi", row1), ("LAN", row2)):
                d.text((x + 12, cy), label, font=font(ROBOTO_MEDIUM, 12), fill=SUB, anchor="lm")
                d.text((x + 54, cy), "↓", font=font(MONO_BOLD, 12), fill=BLUE, anchor="lm")
                d.text((x + w - 90, cy), "↑", font=font(MONO_BOLD, 12), fill=GREEN, anchor="lm")
        else:
            d.text((x + 12, y + 9), "HỆ THỐNG", font=font(ROBOTO_BOLD, 12), fill=GREEN, anchor="lt")
            d.text((x + 12, row1), "Thời gian chạy", font=font(ROBOTO_MEDIUM, 12), fill=SUB, anchor="lm")
            d.text((x + 12, row2), "Ping", font=font(ROBOTO_MEDIUM, 12), fill=SUB, anchor="lm")
        d.line([(x + 12, y + 59), (x + w - 12, y + 59)], fill=BORDER)

    img.save(THEME_DIR / "background.png")


def text_block(x, y, w, h, fnt, size, color, anchor, indent=8):
    # Fixed WIDTH/HEIGHT: the whole box is redrawn on refresh, so shorter values never leave "ghost" characters
    fields = {"X": x, "Y": y, "WIDTH": w, "HEIGHT": h, "FONT": fnt, "FONT_SIZE": size, "FONT_COLOR": rgb(color),
              "BACKGROUND_IMAGE": "background.png", "ANCHOR": anchor}
    return "".join(f"{' ' * indent}{k}: {v}\n" for k, v in fields.items())


def custom_text(name, x, y, w, h, fnt, size, color, anchor):
    return f"    {name}:\n      TEXT:\n        SHOW: True\n" + text_block(x, y, w, h, fnt, size, color, anchor)


def custom_gauge(name, cx, cy, accent):
    return (f"    {name}:\n      RADIAL:\n        SHOW: True\n"
            f"        X: {cx}\n        Y: {cy}\n"
            f"        RADIUS: {GAUGE_R}\n        WIDTH: {GAUGE_W}\n        MIN_VALUE: 0\n        MAX_VALUE: 100\n"
            f"        ANGLE_START: 135\n        ANGLE_END: 45\n        ANGLE_STEPS: 1\n        ANGLE_SEP: 0\n"
            f"        CLOCKWISE: True\n        BAR_COLOR: {rgb(accent)}\n"
            f"        DRAW_BAR_BACKGROUND: True\n        BAR_BACKGROUND_COLOR: {rgb(TRACK)}\n"
            f"        SHOW_TEXT: True\n        FONT: {MONO_BOLD}\n        FONT_SIZE: 18\n"
            f"        FONT_COLOR: {rgb(TEXT)}\n        BACKGROUND_IMAGE: background.png\n")


def net_rate(direction, x, cy):
    return (f"      {direction}:\n        TEXT:\n          SHOW: True\n"
            + text_block(x, cy - 8, 70, 16, MONO_BOLD, 11, TEXT, "rm", indent=10))


def date_section(layout):
    if layout["big_clock"]:
        day = text_block(MARGIN, 190, W - 2 * MARGIN, 26, ROBOTO, 20, SUB, "mm")
        hour = text_block(MARGIN, 110, W - 2 * MARGIN, 70, MONO_BOLD, 64, TEXT, "mm")
    else:
        day = text_block(236, 31, 230, 13, ROBOTO, 11, SUB, "rm")
        hour = text_block(326, 5, 140, 24, MONO_BOLD, 20, TEXT, "rm")
    return (f"  DATE:\n    INTERVAL: 1\n"
            f"    DAY:\n      TEXT:\n        SHOW: True\n        FORMAT: \"EEEE, dd/MM/yyyy\"\n{day}"
            f"    HOUR:\n      TEXT:\n        SHOW: True\n        FORMAT: \"HH:mm:ss\"\n{hour}")


def write_theme_yaml(custom, layout):
    blocks = custom["blocks"]
    stats = []
    if blocks["clock"]:
        stats.append(date_section(layout))

    gauges, texts = [], []
    for (key, _, accent, cls), x, y, w in layout["gauges"]:
        cx, below_y = x + w // 2, y + 121
        gauges.append(custom_gauge(cls, cx, y + GAUGE_DY, accent))
        if key == "cpu":
            texts.append(custom_text("Igam3CpuTemp", cx - 66, below_y, 64, 14, MONO_BOLD, 12, ORANGE, "mm"))
            texts.append(custom_text("Igam3CpuFreq", cx + 2, below_y, 64, 14, MONO_BOLD, 11, SUB, "mm"))
        else:
            texts.append(custom_text("Igam3RamText" if key == "ram" else "Igam3DiskText",
                                     cx - 66, below_y, 132, 14, MONO_BOLD, 11, SUB, "mm"))
    if blocks["hostname"]:
        texts.append(custom_text("Igam3Hostname", 14, 31, 220 if layout["header_clock"] else W - 28, 13,
                                 ROBOTO, 11, SUB, "lm"))
    for key, x, y, w in layout["bottoms"]:
        row1, row2 = y + 42, y + 76
        if key == "network":
            texts.append(custom_text("Igam3Ip", x + w - 136, y + 8, 124, 15, MONO, 11, SUB, "rm"))
            stats.append(f"  NET:\n    INTERVAL: 2\n"
                         f"    WLO:\n{net_rate('DOWNLOAD', x + 62, row1)}{net_rate('UPLOAD', x + w - 82, row1)}"
                         f"    ETH:\n{net_rate('DOWNLOAD', x + 62, row2)}{net_rate('UPLOAD', x + w - 82, row2)}")
        else:
            texts.append(custom_text("Igam3Uptime", x + w - 118, row1 - 8, 106, 16, MONO_BOLD, 12, TEXT, "rm"))
            texts.append(custom_text("Igam3Ping", x + w - 118, row2 - 8, 106, 16, MONO_BOLD, 12, TEXT, "rm"))
    if gauges or texts:
        stats.append("  CUSTOM:\n    INTERVAL: 3\n" + "".join(gauges + texts))

    y = f"""# iGam3 M1 - DePIN node dashboard for the built-in Turing Smart Screen 3.5" (480x320 landscape)
# GENERATED by make_theme.py from custom.yaml: change those rather than editing this file by hand
author: "iGam3 M1"

display:
  DISPLAY_SIZE: 3.5"
  DISPLAY_ORIENTATION: landscape
  DISPLAY_RGB_LED: {rgb(CYAN)}

static_images:
  BACKGROUND:
    PATH: background.png
    X: 0
    Y: 0
    WIDTH: {W}
    HEIGHT: {H}

STATS:
""" + "\n".join(stats)
    (THEME_DIR / "theme.yaml").write_text(y, encoding="utf8")


if __name__ == "__main__":
    custom = load_custom()
    layout = compute_layout(custom["blocks"])
    draw_background(custom, layout)
    write_theme_yaml(custom, layout)
    print("Generated", THEME_DIR / "background.png", "and", THEME_DIR / "theme.yaml")
