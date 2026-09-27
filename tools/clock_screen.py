# Clock main screen: time, date, Vietnamese lunar calendar and the weather of the place in the settings (Open-Meteo).
# Drawn at 480x320 (landscape); every second only the part of the picture that changed is sent to the screen.

import datetime
import math
import time
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

import i18n
import lunar
import moon
import weather
from i18n import tr

FONTS = Path(__file__).resolve().parent.parent / "app" / "res" / "fonts"
W, H = 480, 320
BG, CARD, BORDER = (12, 16, 28), (20, 28, 45), (34, 48, 74)
TEXT, SUB, MUTED = (229, 231, 235), (148, 163, 184), (100, 116, 139)
CYAN, AMBER, BLUE, YELLOW, GREEN = (34, 211, 238), (251, 191, 36), (96, 165, 250), (253, 224, 71), (52, 211, 153)
SS = 4  # icons are drawn 4x larger then reduced: smooth edges

WEEKDAYS_VI = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]
WEEKDAYS_EN = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MONTHS_EN = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
             "November", "December"]

_fonts = {}


def font(name, size):
    if (name, size) not in _fonts:
        _fonts[(name, size)] = ImageFont.truetype(str(FONTS / name), size)
    return _fonts[(name, size)]


ROBOTO, ROBOTO_MEDIUM, ROBOTO_BOLD = "roboto/Roboto-Regular.ttf", "roboto/Roboto-Medium.ttf", "roboto/Roboto-Bold.ttf"
MONO_BOLD = "jetbrains-mono/JetBrainsMono-Bold.ttf"


def fit(draw, text, name, size, width, smallest=9):
    while size > smallest and draw.textlength(text, font=font(name, size)) > width:
        size -= 1
    return font(name, size)


# ---------------------------------------------------------------- weather icons

_icons = {}


def _cloud(d, s, box, color):
    x0, y0, x1, y1 = [v * s for v in box]
    w, h = x1 - x0, y1 - y0
    d.ellipse([x0 + w * 0.10, y0 + h * 0.35, x0 + w * 0.50, y1], fill=color)
    d.ellipse([x0 + w * 0.28, y0, x0 + w * 0.78, y0 + h * 0.85], fill=color)
    d.ellipse([x0 + w * 0.55, y0 + h * 0.30, x1, y1], fill=color)
    d.rectangle([x0 + w * 0.30, y0 + h * 0.60, x0 + w * 0.80, y1], fill=color)


def _sun(d, s, cx, cy, r, color):
    for i in range(8):
        a = i * math.pi / 4
        d.line([((cx + math.cos(a) * r * 1.35) * s, (cy + math.sin(a) * r * 1.35) * s),
                ((cx + math.cos(a) * r * 1.8) * s, (cy + math.sin(a) * r * 1.8) * s)], fill=color, width=int(r * 0.28 * s))
    d.ellipse([(cx - r) * s, (cy - r) * s, (cx + r) * s, (cy + r) * s], fill=color)


def icon(kind, size, day=True):
    """Weather icon as an RGBA picture of size x size (drawn with shapes: no icon font needed)"""
    key = (kind, size, day)
    if key in _icons:
        return _icons[key]
    s = size * SS / 100  # draw on a 100x100 grid
    img = Image.new("RGBA", (size * SS, size * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    grey, dark = (203, 213, 225), (148, 163, 184)
    if kind == "clear":
        if day:
            _sun(d, s, 50, 50, 22, YELLOW)
        else:
            d.ellipse([22 * s, 18 * s, 82 * s, 78 * s], fill=(226, 232, 240))
            d.ellipse([36 * s, 8 * s, 96 * s, 68 * s], fill=(0, 0, 0, 0))
    elif kind == "partly":
        if day:
            _sun(d, s, 36, 36, 17, YELLOW)
        else:
            d.ellipse([14 * s, 10 * s, 58 * s, 54 * s], fill=(226, 232, 240))
            d.ellipse([26 * s, 2 * s, 70 * s, 46 * s], fill=(0, 0, 0, 0))
        _cloud(d, s, (22, 40, 94, 84), grey)
    elif kind == "fog":
        _cloud(d, s, (12, 14, 88, 58), dark)
        for i, y in enumerate((68, 80, 92)):
            d.rounded_rectangle([(14 + i * 6) * s, (y - 3) * s, (86 - i * 6) * s, (y + 3) * s], radius=3 * s, fill=grey)
    else:
        _cloud(d, s, (8, 10, 92, 62), grey if kind != "storm" else dark)
        if kind in ("rain", "drizzle", "storm"):
            drops = 3 if kind != "drizzle" else 4
            for i in range(drops):
                x = 26 + i * (48 / max(1, drops - 1))
                length = 16 if kind != "drizzle" else 8
                d.line([(x * s, 70 * s), ((x - 6) * s, (70 + length) * s)], fill=BLUE, width=int(5 * s))
        if kind == "storm":
            d.polygon([(52 * s, 56 * s), (36 * s, 80 * s), (50 * s, 80 * s), (42 * s, 99 * s), (66 * s, 70 * s),
                       (52 * s, 70 * s), (60 * s, 56 * s)], fill=YELLOW)
        if kind == "snow":
            for x, y in ((30, 76), (50, 86), (70, 76)):
                d.ellipse([(x - 5) * s, (y - 5) * s, (x + 5) * s, (y + 5) * s], fill=(241, 245, 249))
    _icons[key] = img.resize((size, size), Image.LANCZOS)
    return _icons[key]


# ---------------------------------------------------------------- screen

def date_line(now):
    if i18n.LANG == "vi":
        return f"{WEEKDAYS_VI[now.weekday()]}, {now:%d/%m/%Y}"
    return f"{WEEKDAYS_EN[now.weekday()]}, {now.day} {MONTHS_EN[now.month - 1]} {now.year}"


def day_label(date, today):
    delta = (date - today).days
    if delta == 0:
        return tr("Hôm nay", "Today")
    if delta == 1:
        return tr("Ngày mai", "Tomorrow")
    vi = i18n.LANG == "vi"
    return (WEEKDAYS_VI if vi else WEEKDAYS_EN)[date.weekday()][: None if vi else 3]


def render(now, place, forecast, age):
    """The whole clock screen for the time now"""
    vi = i18n.LANG == "vi"
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    # Date and place
    d.text((16, 22), date_line(now), font=font(ROBOTO_MEDIUM, 18), fill=TEXT, anchor="lm")
    if place:
        name = place["name"]
        d.text((W - 16, 22), name, font=fit(d, name, ROBOTO, 13, 150), fill=SUB, anchor="rm")
    # Time: hours and minutes big, seconds small
    hhmm = now.strftime("%H:%M")
    big = font(MONO_BOLD, 80)
    d.text((12, 104), hhmm, font=big, fill=TEXT, anchor="ls")
    d.text((14 + d.textlength(hhmm, font=big), 104), f":{now:%S}", font=font(MONO_BOLD, 26), fill=CYAN, anchor="ls")
    # Weather now (right column)
    x0 = 322
    current = (forecast or {}).get("current") or {}
    if current:
        kind, text = weather.describe(current.get("weather_code"), vi)
        img.paste(ic := icon(kind, 58, bool(current.get("is_day", 1))), (x0, 44), ic)
        d.text((x0 + 64, 76), f"{round(current.get('temperature_2m', 0))}°", font=font(ROBOTO_BOLD, 40), fill=TEXT, anchor="lm")
        d.text((x0, 116), text, font=fit(d, text, ROBOTO_MEDIUM, 15, W - 12 - x0), fill=TEXT, anchor="lm")
        details = tr(f"Cảm giác {round(current.get('apparent_temperature', 0))}° · Ẩm {current.get('relative_humidity_2m', 0)}%",
                     f"Feels {round(current.get('apparent_temperature', 0))}° · Humidity {current.get('relative_humidity_2m', 0)}%")
        d.text((x0, 138), details, font=fit(d, details, ROBOTO, 12, W - 12 - x0), fill=SUB, anchor="lm")
        if age and age > 2 * 3600:
            d.text((x0, 156), tr("(số liệu cũ, chưa cập nhật được)", "(old data, cannot update)"), font=font(ROBOTO, 10),
                   fill=AMBER, anchor="lm")
    else:
        img.paste(ic := icon("cloud", 50), (x0, 46), ic)
        lines = [tr("Chưa đặt thành phố:", "No city set yet:"), tr("đặt ở trang quản lý", "set it in the web panel")] \
            if not place else [tr("Đang lấy thời tiết…", "Getting the weather…")]
        for i, line in enumerate(lines):
            d.text((x0, 112 + i * 18), line, font=fit(d, line, ROBOTO, 13, W - 12 - x0), fill=SUB, anchor="lm")
    d.line([(12, 168), (W - 12, 168)], fill=BORDER, width=1)
    # Lunar calendar card, with the moonphase window of Swiss watches
    d.rounded_rectangle([12, 178, 232, 308], radius=10, fill=CARD, outline=BORDER)
    lday, lmonth, lyear, leap = lunar.solar_to_lunar(now.day, now.month, now.year)
    label = tr("ÂM LỊCH", "LUNAR CALENDAR")
    d.text((24, 192), label, font=font(ROBOTO_BOLD, 11), fill=MUTED, anchor="lm")
    holiday = None if leap else lunar.HOLIDAYS.get((lday, lmonth))
    special = tr(*holiday) if holiday else {1: tr("Mùng 1", "1st"), 15: tr("Rằm", "15th")}.get(lday)
    if special:
        x = 30 + d.textlength(label, font=font(ROBOTO_BOLD, 11))
        width = d.textlength(special, font=font(ROBOTO_BOLD, 10))
        d.rounded_rectangle([x, 184, x + width + 12, 200], radius=8, fill=(69, 43, 8))
        d.text((x + 6, 192), special, font=font(ROBOTO_BOLD, 10), fill=AMBER, anchor="lm")
    d.text((24, 226), f"{lday}/{lmonth}", font=font(ROBOTO_BOLD, 36), fill=AMBER, anchor="lm")
    phase = moon.phase(now)
    dial = moon.dial(70, phase["fraction"], plate=CARD, frame=BORDER, gold=(236, 196, 102))
    img.paste(dial, (154, 186), dial)
    d.text((189, 234), tr(f"Sáng {phase['illumination'] * 100:.0f}%", f"{phase['illumination'] * 100:.0f}% lit"),
           font=font(ROBOTO, 9), fill=MUTED, anchor="mm")
    year = lunar.year_name(lyear)
    tag = tr("tháng nhuận", "leap month") if leap else tr(f"năm con {lunar.ANIMALS_VI[(lyear + 8) % 12]}",
                                                         f"year of the {lunar.year_animal(lyear)}")
    line = f"{year} · {tag}"
    d.text((24, 256), line, font=fit(d, line, ROBOTO_MEDIUM, 13, 200), fill=TEXT, anchor="lm")
    names = tr(f"Ngày {lunar.day_name(now.day, now.month, now.year)} · Tháng {lunar.month_name(lmonth, lyear)}",
               f"Day {lunar.day_name(now.day, now.month, now.year)} · Month {lunar.month_name(lmonth, lyear)}")
    d.text((24, 276), names, font=fit(d, names, ROBOTO, 11, 200), fill=SUB, anchor="lm")
    moons = tr(f"{moon.name(phase)} · tròn {phase['next_full']:%d/%m}", f"{moon.name(phase, False)} · full {phase['next_full']:%d/%m}")
    d.text((24, 294), moons, font=fit(d, moons, ROBOTO, 10, 200), fill=MUTED, anchor="lm")
    # Forecast card
    d.rounded_rectangle([244, 178, W - 12, 308], radius=10, fill=CARD, outline=BORDER)
    d.text((256, 192), tr("DỰ BÁO", "FORECAST"), font=font(ROBOTO_BOLD, 11), fill=MUTED, anchor="lm")
    daily = (forecast or {}).get("daily") or {}
    if daily.get("time"):
        today = now.date()
        for i, day in enumerate(daily["time"][:3]):
            y = 216 + i * 30
            date = datetime.date.fromisoformat(day)
            kind, _ = weather.describe(daily["weather_code"][i], vi)
            img.paste(ic := icon(kind, 24), (254, y - 12), ic)
            d.text((284, y), day_label(date, today), font=font(ROBOTO_MEDIUM, 13), fill=TEXT, anchor="lm")
            temps = f"{round(daily['temperature_2m_min'][i])}–{round(daily['temperature_2m_max'][i])}°"
            d.text((400, y), temps, font=font(ROBOTO_MEDIUM, 13), fill=TEXT, anchor="rm")
            rain = daily.get("precipitation_probability_max", [None] * 3)[i]
            if rain is not None:
                d.text((W - 22, y), f"{rain}%", font=font(ROBOTO, 12), fill=BLUE if rain >= 50 else SUB, anchor="rm")
        d.text((W - 20, 301), "Open-Meteo", font=font(ROBOTO, 9), fill=MUTED, anchor="rm")  # CC BY 4.0 credit
    else:
        hint = tr("Thời tiết: đặt thành phố ở giao diện web", "Weather: set the city in the web panel") if not place \
            else tr("Chưa có dự báo", "No forecast yet")
        d.text((256, 240), hint, font=fit(d, hint, ROBOTO, 12, 200), fill=SUB, anchor="lm")
    return img


def run_clock(lcd, stop, place, cache_path, control=None):
    """Main screen loop: draw the clock, then only what changes, until stop is set"""
    forecasts = weather.Weather(Path(cache_path), place)
    shown = {"image": None}
    if control:
        control.redraw = lambda: shown.update(image=None)  # after an alert screen: draw everything again
    while not stop.is_set():
        now = datetime.datetime.now()
        data, age = forecasts.snapshot()
        frame = render(now, place(), data, age)
        previous = shown["image"]
        if previous is None:
            lcd.DisplayPILImage(frame)
        else:
            box = ImageChops.difference(frame, previous).getbbox()
            if box:
                lcd.DisplayPILImage(frame.crop(box), box[0], box[1])
        shown["image"] = frame
        stop.wait(1.02 - time.time() % 1)  # just after the next second starts
