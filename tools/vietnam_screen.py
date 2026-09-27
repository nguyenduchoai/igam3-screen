# "Vietnam Theme": a main screen in lacquer red and gold with a Đông Sơn bronze drum in the background: time, solar
# and lunar dates (can chi, lunar holidays), the moonphase window of Swiss watches, the weather, and every system value
# (CPU, RAM, SSD, GPU, network, uptime, ping), plus an optional small logo. Drawn at 480x320; only the parts of the
# picture that change are sent to the screen.

import datetime
import math
import socket
import threading
import time
from pathlib import Path

import psutil
from PIL import Image, ImageChops, ImageDraw, ImageFont

import i18n
import lunar
import moon
import weather
from i18n import tr

FONTS = Path(__file__).resolve().parent.parent / "app" / "res" / "fonts"
W, H = 480, 320
SS = 4
LACQUER_TOP, LACQUER_BOTTOM = (98, 16, 14), (26, 5, 7)
GOLD, GOLD_LIGHT, GOLD_DARK = (228, 182, 86), (250, 222, 150), (150, 108, 44)
CREAM, MUTED = (253, 244, 222), (212, 176, 146)
RED, JADE = (248, 90, 70), (110, 220, 150)
PANEL = (8, 2, 2, 120)
MONTHS_VI = ["Giêng", "Hai", "Ba", "Tư", "Năm", "Sáu", "Bảy", "Tám", "Chín", "Mười", "Mười Một", "Chạp"]
WEEKDAYS_VI = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]
WEEKDAYS_EN = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MONTHS_EN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
ROBOTO, ROBOTO_MEDIUM, ROBOTO_BOLD = "roboto/Roboto-Regular.ttf", "roboto/Roboto-Medium.ttf", "roboto/Roboto-Bold.ttf"
MONO_BOLD = "jetbrains-mono/JetBrainsMono-Bold.ttf"
CARDS = {"cpu": (12, 166), "ram": (166, 166), "ssd": (320, 166), "gpu": (12, 232), "net": (166, 232), "system": (320, 232)}
CARD_W, CARD_H = 148, 58
TILE_W, TILE_H = 40, 16  # changes are sent tile by tile, merged into strips

_fonts = {}


def font(name, size):
    if (name, size) not in _fonts:
        _fonts[(name, size)] = ImageFont.truetype(str(FONTS / name), size)
    return _fonts[(name, size)]


def fit(draw, text, name, size, width, smallest=8):
    while size > smallest and draw.textlength(text, font=font(name, size)) > width:
        size -= 1
    return font(name, size)


# ---------------------------------------------------------------- ornaments

def drum(size, color):
    """Face of a Đông Sơn bronze drum: 14-ray sun, rings of circles and hatching, flying Lạc birds (RGBA)"""
    s = size * 2
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = s / 2
    line = max(1, int(s * 0.006))

    def ring(r):
        d.ellipse([c - r * s, c - r * s, c + r * s, c + r * s], outline=color, width=line)

    def circles(r, radius):
        count = int(2 * math.pi * r / (radius * 2.1))
        for i in range(count):
            a = 2 * math.pi * i / count
            x, y = c + math.cos(a) * r * s, c + math.sin(a) * r * s
            d.ellipse([x - radius * s, y - radius * s, x + radius * s, y + radius * s], outline=color, width=line)
            d.ellipse([x - line, y - line, x + line, y + line], fill=color)

    def ticks(r0, r1, step_deg):
        for deg in range(0, 360, step_deg):
            a = math.radians(deg)
            d.line([(c + math.cos(a) * r0 * s, c + math.sin(a) * r0 * s), (c + math.cos(a) * r1 * s, c + math.sin(a) * r1 * s)],
                   fill=color, width=line)

    # The sun: 14 rays and the feather-like V patterns between them
    d.ellipse([c - 0.05 * s, c - 0.05 * s, c + 0.05 * s, c + 0.05 * s], fill=color)
    for i in range(14):
        a = 2 * math.pi * i / 14
        half = math.pi / 14 * 0.42
        d.polygon([(c + math.cos(a - half) * 0.05 * s, c + math.sin(a - half) * 0.05 * s),
                   (c + math.cos(a) * 0.19 * s, c + math.sin(a) * 0.19 * s),
                   (c + math.cos(a + half) * 0.05 * s, c + math.sin(a + half) * 0.05 * s)], fill=color)
        b = a + math.pi / 14
        for k in (0.10, 0.14):
            d.line([(c + math.cos(b - 0.12) * k * s, c + math.sin(b - 0.12) * k * s),
                    (c + math.cos(b) * (k - 0.03) * s, c + math.sin(b) * (k - 0.03) * s),
                    (c + math.cos(b + 0.12) * k * s, c + math.sin(b + 0.12) * k * s)], fill=color, width=line)
    ring(0.21)
    ring(0.225)
    circles(0.255, 0.022)
    ring(0.285)
    ticks(0.29, 0.325, 4)
    ring(0.33)
    # Flying Lạc birds with long beaks, counterclockwise
    bird = [(0.50, 0.00), (0.20, -0.04), (0.10, -0.10), (0.02, -0.05), (-0.12, -0.04), (-0.30, -0.14), (-0.50, -0.16),
            (-0.36, -0.02), (-0.50, 0.06), (-0.20, 0.07), (0.04, 0.04), (0.20, 0.02)]
    for i in range(10):
        a = 2 * math.pi * i / 10
        cx, cy = c + math.cos(a) * 0.405 * s, c + math.sin(a) * 0.405 * s
        heading = a - math.pi / 2  # tangent: flying around the sun
        length = 0.13 * s
        pts = [(cx + (px * math.cos(heading) - py * math.sin(heading)) * length,
                cy + (px * math.sin(heading) + py * math.cos(heading)) * length) for px, py in bird]
        d.polygon(pts, fill=color)
    ring(0.48)
    ring(0.495)
    circles(0.52, 0.02)
    ring(0.545)
    ticks(0.55, 0.585, 3)
    ring(0.59)
    ring(0.605)
    return img.resize((size, size), Image.LANCZOS)


def lotus(size, color=GOLD, heart=(240, 120, 110)):
    """A small lotus flower (RGBA)"""
    s = size * SS
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for angle, scale in ((-58, 0.8), (58, 0.8), (-28, 0.95), (28, 0.95), (0, 1.0)):
        petal = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        ImageDraw.Draw(petal).ellipse([s * 0.38, s * (0.95 - 0.8 * scale), s * 0.62, s * 0.95],
                                      fill=heart if angle == 0 else color)
        petal = petal.rotate(angle, center=(s / 2, s * 0.95), resample=Image.BICUBIC)
        img.alpha_composite(petal)
    d.rounded_rectangle([s * 0.18, s * 0.86, s * 0.82, s * 0.98], radius=s * 0.06, fill=color)
    return img.resize((size, size), Image.LANCZOS)


def star(draw, cx, cy, r, color):
    pts = []
    for i in range(10):
        a = -math.pi / 2 + i * math.pi / 5
        radius = r if i % 2 == 0 else r * 0.42
        pts.append((cx + math.cos(a) * radius, cy + math.sin(a) * radius))
    draw.polygon(pts, fill=color)


def logo_badge(path, height=22, max_width=92):
    """The logo on a small cream plate (brand colours stay readable on the lacquer)"""
    try:
        with Image.open(path) as src:
            logo = src.convert("RGBA")
    except (OSError, ValueError):
        return None
    box = logo.getbbox()
    if box:
        logo = logo.crop(box)
    inner_h = height - 8
    ratio = min(inner_h / logo.height, (max_width - 14) / logo.width)
    logo = logo.resize((max(1, int(logo.width * ratio)), max(1, int(logo.height * ratio))), Image.LANCZOS)
    plate = Image.new("RGBA", (logo.width + 14, height), (0, 0, 0, 0))
    ImageDraw.Draw(plate).rounded_rectangle([0, 0, plate.width - 1, height - 1], radius=height // 2,
                                            fill=(252, 246, 232, 255), outline=GOLD + (255,), width=1)
    plate.alpha_composite(logo, (7, (height - logo.height) // 2))
    return plate


# ---------------------------------------------------------------- system values

def human_rate(value):
    for unit in ("B/s", "KB/s", "MB/s", "GB/s"):
        if value < 1000 or unit == "GB/s":
            return f"{value:.0f} {unit}" if unit == "B/s" else f"{value:.1f} {unit}"
        value /= 1024


def human_duration(seconds):
    days, rest = divmod(int(seconds), 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    return (f"{days}{tr(' ngày ', 'd ')}" if days else "") + f"{hours:02d}:{minutes:02d}"


class Stats:
    """Values of the computer, read every 2 s; ping in the background every 5 s"""

    def __init__(self, active_interface, primary_ipv4):
        self.active_interface, self.primary_ipv4 = active_interface, primary_ipv4
        psutil.cpu_percent(interval=None)
        self.net_before, self.net_at = None, None
        self.ping_ms, self.pinged = None, False
        self.gpu = None
        try:
            from library.sensors import sensors_python  # NVIDIA, AMD and Intel integrated graphics
            if sensors_python.Gpu.is_available():
                self.gpu = sensors_python.Gpu
                self.gpu.stats()
        except Exception:
            self.gpu = None
        threading.Thread(target=self._ping_loop, daemon=True).start()
        self.values = self.read()

    def _ping_loop(self):
        while True:
            delay = None
            try:
                from ping3 import ping
                delay = ping("8.8.8.8", timeout=1, unit="ms")
            except Exception:
                pass
            if not delay:
                start = time.perf_counter()
                try:
                    with socket.create_connection(("8.8.8.8", 53), timeout=1):
                        delay = (time.perf_counter() - start) * 1000
                except OSError:
                    delay = None
            self.ping_ms, self.pinged = delay, True
            time.sleep(5)

    def read(self):
        v = {"cpu": psutil.cpu_percent(interval=None)}
        try:
            entries = psutil.sensors_temperatures().get("coretemp") or []
            package = [e.current for e in entries if e.label.lower().startswith("package")] or [e.current for e in entries]
            v["cpu_temp"] = max(package) if package else None
        except (AttributeError, OSError):
            v["cpu_temp"] = None
        try:
            v["cpu_freq"] = psutil.cpu_freq().current / 1000
        except (AttributeError, OSError, TypeError):
            v["cpu_freq"] = None
        memory = psutil.virtual_memory()
        v["ram"], v["ram_used"], v["ram_total"] = memory.percent, (memory.total - memory.available) / 1024 ** 3, memory.total / 1024 ** 3
        disk = psutil.disk_usage(Path.home().anchor if Path.home().anchor != "" else "/")
        v["ssd"], v["ssd_used"], v["ssd_total"] = disk.percent, disk.used / 1024 ** 3, disk.total / 1024 ** 3
        v["gpu"] = None
        if self.gpu:
            try:
                load, _, memory_mb, _, temperature = self.gpu.stats()
                v["gpu"] = {"load": load, "memory": memory_mb, "temp": temperature}
            except Exception:
                pass
        interface = self.active_interface()
        counters = psutil.net_io_counters(pernic=True).get(interface) if interface else None
        now = time.monotonic()
        v["iface"], v["down"], v["up"] = interface or "", 0.0, 0.0
        if counters and self.net_before and self.net_before[0] == interface:
            elapsed = max(0.5, now - self.net_at)
            v["down"] = max(0, counters.bytes_recv - self.net_before[1].bytes_recv) / elapsed
            v["up"] = max(0, counters.bytes_sent - self.net_before[1].bytes_sent) / elapsed
        self.net_before, self.net_at = ((interface, counters) if counters else None), now
        v["ip"] = self.primary_ipv4() or ""
        v["uptime"] = time.time() - psutil.boot_time()
        v["ping"], v["pinged"] = self.ping_ms, self.pinged
        self.values = v
        return v


# ---------------------------------------------------------------- picture

class VietnamScreen:
    def __init__(self, logo=None):
        self.logo = logo
        self._background = {}
        self._dials = {}

    def background(self):
        """Lacquer, drum, frame, panels and labels: drawn once per language and logo"""
        key = (i18n.LANG, self.logo)
        if key in self._background:
            return self._background[key]
        img = Image.new("RGBA", (W, H))
        d = ImageDraw.Draw(img)
        for y in range(H):  # red lacquer, darker towards the bottom
            t = (y / H) ** 1.2
            d.line([(0, y), (W, y)], fill=tuple(int(LACQUER_TOP[j] + (LACQUER_BOTTOM[j] - LACQUER_TOP[j]) * t) for j in range(3)) + (255,))
        watermark = drum(360, GOLD + (255,))
        watermark.putalpha(watermark.getchannel("A").point(lambda a: a * 44 // 255))
        img.alpha_composite(watermark, (300, 70))
        d.rectangle([2, 2, W - 3, H - 3], outline=GOLD_DARK, width=1)
        d.rectangle([5, 5, W - 6, H - 6], outline=GOLD_DARK + (140,), width=1)
        for x, y in ((5, 5), (W - 6, 5), (5, H - 6), (W - 6, H - 6)):  # corner studs
            d.ellipse([x - 3, y - 3, x + 3, y + 3], fill=GOLD)
        # Header
        badge = logo_badge(self.logo) if self.logo else None
        if badge:
            img.alpha_composite(badge, (12, 9))
        else:
            star(d, 22, 20, 7, GOLD)
            d.text((34, 20), "VIỆT NAM", font=font(ROBOTO_BOLD, 12), fill=GOLD, anchor="lm")
        if badge:
            star(d, 196, 20, 5, GOLD)
            d.text((240, 20), "VIỆT NAM", font=font(ROBOTO_BOLD, 12), fill=GOLD, anchor="mm")
            star(d, 284, 20, 5, GOLD)
        d.line([(12, 34), (W - 12, 34)], fill=GOLD_DARK, width=1)
        for x in range(14, W - 14, 8):  # saw-tooth band, as on the rims of the drums
            d.polygon([(x, 35), (x + 4, 39), (x + 8, 35)], fill=GOLD_DARK)
        # Divider with a small drum in the middle
        d.line([(12, 158), (W / 2 - 16, 158)], fill=GOLD_DARK, width=1)
        d.line([(W / 2 + 16, 158), (W - 12, 158)], fill=GOLD_DARK, width=1)
        small = drum(28, GOLD + (255,))
        img.alpha_composite(small, (W // 2 - 14, 144))
        # Panels and their labels
        labels = {"cpu": "CPU", "ram": "RAM", "ssd": tr("Ổ SSD", "SSD"), "gpu": "GPU", "net": tr("MẠNG", "NETWORK"),
                  "system": tr("HỆ THỐNG", "SYSTEM")}
        panels = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        p = ImageDraw.Draw(panels)
        for key_, (x, y) in CARDS.items():
            p.rounded_rectangle([x, y, x + CARD_W, y + CARD_H], radius=8, fill=PANEL, outline=GOLD_DARK + (255,), width=1)
        img.alpha_composite(panels)
        for key_, (x, y) in CARDS.items():
            d.text((x + 10, y + 11), labels[key_], font=font(ROBOTO_BOLD, 11), fill=GOLD, anchor="lm")
        x, y = CARDS["system"]
        d.text((x + 10, y + 31), tr("Đã chạy", "Uptime"), font=font(ROBOTO, 11), fill=MUTED, anchor="lm")
        d.text((x + 10, y + 47), "Ping", font=font(ROBOTO, 11), fill=MUTED, anchor="lm")
        self._background = {key: img}
        return img

    def moon_dial(self, fraction):
        key = round(fraction, 3)
        if key not in self._dials:
            self._dials = {key: moon.dial(112, fraction, plate=(84, 14, 12), frame=GOLD, gold=(238, 198, 104))}
        return self._dials[key]

    def render(self, now, values, place, forecast):
        img = self.background().copy()
        d = ImageDraw.Draw(img)
        vi = i18n.LANG == "vi"
        # Header right: the place of the weather
        if place:
            d.text((W - 14, 20), place["name"], font=fit(d, place["name"], ROBOTO, 11, 140), fill=MUTED, anchor="rm")
        # Time and dates
        hhmm = now.strftime("%H:%M")
        big = font(MONO_BOLD, 50)
        d.text((13, 85), hhmm, font=big, fill=(60, 10, 8), anchor="ls")  # engraved shadow
        d.text((12, 84), hhmm, font=big, fill=GOLD_LIGHT, anchor="ls")
        d.text((16 + d.textlength(hhmm, font=big), 84), f":{now:%S}", font=font(MONO_BOLD, 18), fill=GOLD, anchor="ls")
        solar = f"{WEEKDAYS_VI[now.weekday()]}, {now:%d/%m/%Y}" if vi else \
            f"{WEEKDAYS_EN[now.weekday()]}, {now.day} {MONTHS_EN[now.month - 1]} {now.year}"
        d.text((12, 102), solar, font=font(ROBOTO_MEDIUM, 14), fill=CREAM, anchor="lm")
        lday, lmonth, lyear, leap = lunar.solar_to_lunar(now.day, now.month, now.year)
        icon = lotus(16)
        img.alpha_composite(icon, (11, 114))
        month_name = MONTHS_VI[lmonth - 1] + (" nhuận" if leap else "")
        lunar_text = f"{lday} tháng {month_name} · {lunar.year_name(lyear)}" if vi else \
            f"Lunar {lday}/{lmonth}{' (leap)' if leap else ''} · {lunar.year_name(lyear)}"
        d.text((31, 123), lunar_text, font=fit(d, lunar_text, ROBOTO_BOLD, 14, 190), fill=GOLD, anchor="lm")
        holiday = None if leap else lunar.HOLIDAYS.get((lday, lmonth))
        special = tr(*holiday) if holiday else {1: tr("Mùng Một", "1st of the lunar month"), 15: tr("Rằm", "Full moon day")}.get(lday)
        if special:
            width = d.textlength(special, font=font(ROBOTO_BOLD, 11))
            d.rounded_rectangle([12, 134, 26 + width, 150], radius=8, fill=(150, 24, 18), outline=GOLD)
            d.text((19, 142), special, font=font(ROBOTO_BOLD, 11), fill=GOLD_LIGHT, anchor="lm")
        else:
            names = tr(f"Ngày {lunar.day_name(now.day, now.month, now.year)} · Tháng {lunar.month_name(lmonth, lyear)}",
                       f"Day {lunar.day_name(now.day, now.month, now.year)} · Month {lunar.month_name(lmonth, lyear)}")
            d.text((12, 142), names, font=fit(d, names, ROBOTO, 11, 212), fill=MUTED, anchor="lm")
        # Moonphase window
        m = moon.phase(now)
        dial = self.moon_dial(m["fraction"])
        img.alpha_composite(dial, (234, 44))
        phase_name = moon.name(m, vi)
        d.text((290, 116), phase_name, font=fit(d, phase_name, ROBOTO_MEDIUM, 11, 112), fill=CREAM, anchor="mm")
        dates = tr(f"Tròn {m['next_full']:%d/%m} · Non {m['next_new']:%d/%m}", f"Full {m['next_full']:%d/%m} · New {m['next_new']:%d/%m}")
        d.text((290, 132), dates, font=fit(d, dates, ROBOTO, 10, 112), fill=MUTED, anchor="mm")
        d.text((290, 146), tr(f"Sáng {m['illumination'] * 100:.0f}%", f"{m['illumination'] * 100:.0f}% lit"),
               font=font(ROBOTO, 10), fill=MUTED, anchor="mm")
        # Weather
        import clock_screen
        current = (forecast or {}).get("current") or {}
        x0 = 354
        if current:
            kind, text = weather.describe(current.get("weather_code"), vi)
            ic = clock_screen.icon(kind, 40, bool(current.get("is_day", 1)))
            img.alpha_composite(ic, (x0, 42))
            d.text((x0 + 46, 64), f"{round(current.get('temperature_2m', 0))}°", font=font(ROBOTO_BOLD, 30), fill=CREAM, anchor="lm")
            d.text((x0, 98), text, font=fit(d, text, ROBOTO_MEDIUM, 12, W - 14 - x0), fill=CREAM, anchor="lm")
            feels = tr(f"Cảm giác {round(current.get('apparent_temperature', 0))}° · Ẩm {current.get('relative_humidity_2m', 0)}%",
                       f"Feels {round(current.get('apparent_temperature', 0))}° · Hum. {current.get('relative_humidity_2m', 0)}%")
            d.text((x0, 114), feels, font=fit(d, feels, ROBOTO, 10, W - 14 - x0), fill=MUTED, anchor="lm")
            daily = (forecast or {}).get("daily") or {}
            if len(daily.get("time") or []) > 1:
                rain = (daily.get("precipitation_probability_max") or [None, None])[1]
                tomorrow = tr("Mai", "Tomorrow") + f" {round(daily['temperature_2m_min'][1])}–{round(daily['temperature_2m_max'][1])}°" + \
                    (tr(f" · mưa {rain}%", f" · rain {rain}%") if rain is not None else "")
                d.text((x0, 130), tomorrow, font=fit(d, tomorrow, ROBOTO, 10, W - 14 - x0), fill=MUTED, anchor="lm")
            d.text((x0, 146), "Open-Meteo", font=font(ROBOTO, 8), fill=GOLD_DARK, anchor="lm")
        else:
            lines = [tr("Chưa đặt thành phố", "No city set"), tr("cho thời tiết", "for the weather")] if not place else \
                [tr("Đang lấy thời tiết…", "Getting the weather…")]
            for i, line in enumerate(lines):
                d.text((x0, 70 + i * 16), line, font=fit(d, line, ROBOTO, 11, W - 14 - x0), fill=MUTED, anchor="lm")
        # System values
        self.card_value(d, "cpu", values["cpu"], " · ".join(x for x in (
            f"{values['cpu_temp']:.0f}°C" if values.get("cpu_temp") is not None else "",
            f"{values['cpu_freq']:.2f} GHz" if values.get("cpu_freq") else "") if x))
        self.card_value(d, "ram", values["ram"], f"{values['ram_used']:.1f}/{values['ram_total']:.1f} GB")
        self.card_value(d, "ssd", values["ssd"], f"{values['ssd_used']:.0f}/{values['ssd_total']:.0f} GB")
        gpu = values.get("gpu")
        if gpu and gpu["load"] == gpu["load"]:  # not NaN
            sub = " · ".join(x for x in (f"{gpu['memory']:.0f} MB" if gpu["memory"] == gpu["memory"] else "",
                                         f"{gpu['temp']:.0f}°C" if gpu["temp"] == gpu["temp"] else "") if x)
            self.card_value(d, "gpu", gpu["load"], sub)
        else:
            x, y = CARDS["gpu"]
            d.text((x + 10, y + 36), tr("Không đọc được", "Not available"), font=font(ROBOTO, 12), fill=MUTED, anchor="lm")
        x, y = CARDS["net"]
        d.text((x + CARD_W - 10, y + 11), values["iface"], font=fit(d, values["iface"], ROBOTO, 10, 70), fill=MUTED, anchor="rm")
        d.text((x + 10, y + 31), "↓", font=font(MONO_BOLD, 13), fill=JADE, anchor="lm")
        d.text((x + CARD_W - 10, y + 31), human_rate(values["down"]), font=font(MONO_BOLD, 13), fill=CREAM, anchor="rm")
        d.text((x + 10, y + 47), "↑", font=font(MONO_BOLD, 13), fill=GOLD, anchor="lm")
        d.text((x + CARD_W - 10, y + 47), human_rate(values["up"]), font=font(MONO_BOLD, 13), fill=CREAM, anchor="rm")
        x, y = CARDS["system"]
        d.text((x + CARD_W - 10, y + 31), human_duration(values["uptime"]), font=font(ROBOTO_BOLD, 13), fill=CREAM, anchor="rm")
        if values.get("ping"):
            ping, color = f"{values['ping']:.0f} ms", CREAM
        elif not values.get("pinged"):
            ping, color = "…", MUTED  # first measure on its way
        else:
            ping, color = tr("mất kết nối", "offline"), RED
        d.text((x + CARD_W - 10, y + 47), ping, font=font(ROBOTO_BOLD, 13), fill=color, anchor="rm")
        # Footer
        footer = " · ".join(x for x in (f"IP {values['ip']}" if values["ip"] else tr("Không có mạng", "No network"),
                                        socket.gethostname()) if x)
        d.text((14, 305), footer, font=font(ROBOTO, 10), fill=MUTED, anchor="lm")
        d.text((W - 14, 305), "igam3-screen · Vietnam Theme", font=font(ROBOTO, 9), fill=GOLD_DARK, anchor="rm")
        return img.convert("RGB")

    @staticmethod
    def card_value(d, key, percent, sub):
        x, y = CARDS[key]
        if sub:
            d.text((x + CARD_W - 10, y + 11), sub, font=fit(d, sub, ROBOTO, 10, 92), fill=MUTED, anchor="rm")
        d.text((x + 10, y + 33), f"{percent:.0f}%", font=font(ROBOTO_BOLD, 19), fill=CREAM, anchor="lm")
        x0, x1, top = x + 60, x + CARD_W - 10, y + 30
        d.rounded_rectangle([x0, top, x1, top + 6], radius=3, fill=(20, 4, 4))
        filled = x0 + (x1 - x0) * max(0.0, min(100.0, percent)) / 100
        if filled > x0 + 2:
            d.rounded_rectangle([x0, top, filled, top + 6], radius=3, fill=RED if percent >= 85 else GOLD)


def changed_strips(frame, previous):
    """Rectangles covering what changed, tile by tile, merged into horizontal strips"""
    diff = ImageChops.difference(frame, previous).convert("L")
    if not diff.getbbox():
        return []
    strips = []
    for y in range(0, H, TILE_H):
        x = 0
        while x < W:
            if diff.crop((x, y, min(W, x + TILE_W), min(H, y + TILE_H))).getbbox():
                start = x
                while x < W and diff.crop((x, y, min(W, x + TILE_W), min(H, y + TILE_H))).getbbox():
                    x += TILE_W
                strips.append((start, y, min(W, x), min(H, y + TILE_H)))
            else:
                x += TILE_W
    merged = []  # the same strip in consecutive rows: one taller rectangle
    for box in strips:
        for i, other in enumerate(merged):
            if other[0] == box[0] and other[2] == box[2] and other[3] == box[1]:
                merged[i] = (other[0], other[1], other[2], box[3])
                break
        else:
            merged.append(box)
    return merged


def run_vietnam(lcd, stop, place, cache_path, logo, active_interface, primary_ipv4, control=None):
    """Main screen loop: the whole picture first, then only what changed, every second"""
    screen = VietnamScreen(logo)
    stats = Stats(active_interface, primary_ipv4)
    forecasts = weather.Weather(Path(cache_path), place)
    shown = {"image": None}
    if control:
        control.redraw = lambda: shown.update(image=None)
    last_read = 0.0
    while not stop.is_set():
        if time.monotonic() - last_read >= 2:
            stats.read()
            last_read = time.monotonic()
        data, _ = forecasts.snapshot()
        frame = screen.render(datetime.datetime.now(), stats.values, place(), data)
        previous = shown["image"]
        if previous is None:
            lcd.DisplayPILImage(frame)
        else:
            for box in changed_strips(frame, previous):
                lcd.DisplayPILImage(frame.crop(box), box[0], box[1])
        shown["image"] = frame
        stop.wait(1.02 - time.time() % 1)


def preview(place, forecast, logo, active_interface, primary_ipv4):
    """One picture of the screen with the current values (theme gallery of the web panel)"""
    stats = Stats(active_interface, primary_ipv4)
    return VietnamScreen(logo).render(datetime.datetime.now(), stats.values, place, forecast)
