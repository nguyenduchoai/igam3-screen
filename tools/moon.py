# Moon phase: age of the moon, next new / full moon (Jean Meeus, "Astronomical Algorithms", chapter 49: accurate to a
# few minutes), and the moonphase window of Swiss watches: a blue disc carrying golden moons turns behind an aperture
# whose two bosses hide the moon at new moon.

import datetime
import math

from PIL import Image, ImageDraw

SYNODIC = 29.530588861
SS = 4  # drawn 4x larger then reduced: smooth edges


def _phase_jde(k):
    """Julian ephemeris day of the new moon (integer k) or full moon (k + 0.5), k = 0 near 2000-01-06"""
    t = k / 1236.85
    jde = 2451550.09766 + SYNODIC * k + 0.00015437 * t * t - 0.000000150 * t ** 3 + 0.00000000073 * t ** 4
    e = 1 - 0.002516 * t - 0.0000074 * t * t
    r = math.radians
    m = r(2.5534 + 29.10535670 * k - 0.0000014 * t * t - 0.00000011 * t ** 3)
    mp = r(201.5643 + 385.81693528 * k + 0.0107582 * t * t + 0.00001238 * t ** 3 - 0.000000058 * t ** 4)
    f = r(160.7108 + 390.67050284 * k - 0.0016118 * t * t - 0.00000227 * t ** 3 + 0.000000011 * t ** 4)
    om = r(124.7746 - 1.56375588 * k + 0.0020672 * t * t + 0.00000215 * t ** 3)
    full = k % 1 != 0
    a = (-0.40614, 0.17302, 0.01614, 0.01043, 0.00734, -0.00515, 0.00209) if full else \
        (-0.40720, 0.17241, 0.01608, 0.01039, 0.00739, -0.00514, 0.00208)
    jde += (a[0] * math.sin(mp) + a[1] * e * math.sin(m) + a[2] * math.sin(2 * mp) + a[3] * math.sin(2 * f)
            + a[4] * e * math.sin(mp - m) + a[5] * e * math.sin(mp + m) + a[6] * e * e * math.sin(2 * m)
            - 0.00111 * math.sin(mp - 2 * f) - 0.00057 * math.sin(mp + 2 * f) + 0.00056 * e * math.sin(2 * mp + m)
            - 0.00042 * math.sin(3 * mp) + 0.00042 * e * math.sin(m + 2 * f) + 0.00038 * e * math.sin(m - 2 * f)
            - 0.00024 * e * math.sin(2 * mp - m) - 0.00017 * math.sin(om))
    return jde - 69.0 / 86400  # ΔT: ephemeris time -> universal time


def _jd(moment):
    return moment.timestamp() / 86400 + 2440587.5


def _moment(jd):
    return datetime.datetime.fromtimestamp((jd - 2440587.5) * 86400)


def phase(moment=None):
    """Moon at a local time: {"age" days, "fraction" 0-1 of the lunation, "illumination" 0-1, "next_full", "next_new"}"""
    moment = moment or datetime.datetime.now()
    jd = _jd(moment)
    k = math.floor((jd - 2451550.09766) / SYNODIC)
    while _phase_jde(k) > jd:
        k -= 1
    while _phase_jde(k + 1) <= jd:
        k += 1
    new, following = _phase_jde(k), _phase_jde(k + 1)
    full = _phase_jde(k + 0.5)
    age = jd - new
    fraction = age / (following - new)
    return {"age": age, "fraction": fraction, "illumination": (1 - math.cos(2 * math.pi * fraction)) / 2,
            "full": _moment(full), "new": _moment(new),
            "next_full": _moment(full if full > jd else _phase_jde(k + 1.5)), "next_new": _moment(following)}


def name(moon, vi=True):
    """Phase name; new, quarters and full moon within a day of the exact moment"""
    days = moon["age"]
    length = days / moon["fraction"] if moon["fraction"] else SYNODIC
    names = [("Trăng non", "New moon"), ("Trăng lưỡi liềm đầu tháng", "Waxing crescent"),
             ("Trăng thượng huyền", "First quarter"), ("Trăng gần tròn", "Waxing gibbous"),
             ("Trăng tròn", "Full moon"), ("Trăng bắt đầu khuyết", "Waning gibbous"),
             ("Trăng hạ huyền", "Last quarter"), ("Trăng lưỡi liềm cuối tháng", "Waning crescent")]
    for i, point in ((0, 0), (2, 0.25), (4, 0.5), (6, 0.75), (0, 1)):
        if abs(days - point * length) < 1:
            return names[i][0 if vi else 1]
    index = 1 if moon["fraction"] < 0.25 else 3 if moon["fraction"] < 0.5 else 5 if moon["fraction"] < 0.75 else 7
    return names[index][0 if vi else 1]


def _moon_face(size, gold):
    """A golden moon with a little relief and a few craters"""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    light, dark = tuple(min(255, c + 40) for c in gold), tuple(int(c * 0.72) for c in gold)
    steps = 12
    for i in range(steps):  # lit from the upper left
        t = i / steps
        inset = t * size * 0.35
        color = tuple(int(dark[j] + (light[j] - dark[j]) * t) for j in range(3))
        d.ellipse([inset * 0.6, inset * 0.6, size - inset * 1.4, size - inset * 1.4], fill=color)
    for cx, cy, r in ((0.35, 0.42, 0.09), (0.58, 0.30, 0.06), (0.62, 0.62, 0.11), (0.42, 0.70, 0.05)):
        d.ellipse([(cx - r) * size, (cy - r) * size, (cx + r) * size, (cy + r) * size], fill=dark + (170,))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size - 1, size - 1], fill=255)
    img.putalpha(mask)
    return img


def dial(width, fraction, plate=(120, 20, 20), frame=(214, 170, 82), sky=((12, 22, 64), (30, 58, 138)),
         gold=(236, 196, 102)):
    """Moonphase window of width x width/2 (RGBA): fraction 0 = new moon, 0.5 = full moon"""
    radius = width // 2 - 2
    height = radius + 4
    w, h, rad = width * SS, height * SS, radius * SS
    cx, cy = w / 2, h - 2 * SS
    moon_r = rad * 0.40
    orbit = rad - moon_r - rad * 0.08
    # Night sky of the disc, with stars
    sky_img = Image.new("RGBA", (w, h))
    d = ImageDraw.Draw(sky_img)
    for y in range(h):
        t = y / h
        d.line([(0, y), (w, y)], fill=tuple(int(sky[0][j] + (sky[1][j] - sky[0][j]) * t) for j in range(3)) + (255,))
    for i in range(14):
        a = i * 2.39996  # golden angle: stars spread evenly without a grid
        dist = rad * (0.35 + 0.6 * ((i * 37) % 11) / 11)
        x, y = cx + math.cos(a) * dist, cy - abs(math.sin(a)) * dist
        s = SS * (1.2 if i % 3 else 2.2)
        d.polygon([(x, y - s * 2), (x + s * 0.6, y - s * 0.6), (x + s * 2, y), (x + s * 0.6, y + s * 0.6), (x, y + s * 2),
                   (x - s * 0.6, y + s * 0.6), (x - s * 2, y), (x - s * 0.6, y - s * 0.6)], fill=gold + (230,))
    # The moon, carried along its orbit: from the left boss (new) over the top (full) to the right boss
    angle = math.pi * (1 - fraction % 1)
    mx, my = cx + orbit * math.cos(angle), cy - orbit * math.sin(angle)
    face = _moon_face(int(moon_r * 2), gold)
    sky_img.alpha_composite(face, (int(mx - moon_r), int(my - moon_r)))
    # Aperture: upper half disc minus the two bosses
    aperture = Image.new("L", (w, h), 0)
    a = ImageDraw.Draw(aperture)
    a.pieslice([cx - rad, cy - rad, cx + rad, cy + rad], 180, 360, fill=255)
    boss_r = moon_r * 1.04
    for sign in (-1, 1):
        a.ellipse([cx + sign * orbit - boss_r, cy - boss_r, cx + sign * orbit + boss_r, cy + boss_r], fill=0)
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    plate_img = Image.new("RGBA", (w, h), plate + (255,))
    shape = Image.new("L", (w, h), 0)
    ImageDraw.Draw(shape).pieslice([cx - rad, cy - rad, cx + rad, cy + rad], 180, 360, fill=255)
    out.paste(plate_img, (0, 0), shape)  # the bosses are part of the dial plate
    out.paste(sky_img, (0, 0), aperture)
    d = ImageDraw.Draw(out)
    for sign in (-1, 1):
        d.arc([cx + sign * orbit - boss_r, cy - boss_r, cx + sign * orbit + boss_r, cy + boss_r], 180, 360,
              fill=frame + (255,), width=int(1.2 * SS))
    d.arc([cx - rad, cy - rad, cx + rad, cy + rad], 180, 360, fill=frame + (255,), width=int(2.2 * SS))
    d.line([(cx - rad, cy), (cx + rad, cy)], fill=frame + (255,), width=int(2.2 * SS))
    return out.resize((width, height), Image.LANCZOS)
