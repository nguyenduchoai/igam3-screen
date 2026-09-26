# Ảnh giới thiệu 480x320 theo kiểu ảnh mẫu iGam3: chữ lớn, dòng phụ, dòng cuối, ảnh nền hoặc logo tuỳ chọn.
# Dùng qua lệnh: igam3-screen splash "Chữ lớn" "Dòng phụ" "Dòng cuối" [--photo ảnh.jpg] [--logo logo.png]

from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps

FONTS = Path(__file__).resolve().parent.parent / "app" / "res" / "fonts"
W, H = 480, 320
MARGIN = 32
LOGO_BOX = 140


def _font(name, size):
    return ImageFont.truetype(str(FONTS / name), size)


def _cut(draw, text, fnt, max_w):
    if draw.textlength(text, font=fnt) <= max_w:
        return text
    while text and draw.textlength(text + "…", font=fnt) > max_w:
        text = text[:-1]
    return text.rstrip() + "…"


def _fit(draw, text, name, size, max_w, min_size):
    """(text, font): shrink the font to fit max_w, cut the text with an ellipsis below min_size"""
    while size > min_size and draw.textlength(text, font=_font(name, size)) > max_w:
        size -= 1
    fnt = _font(name, size)
    return _cut(draw, text, fnt, max_w), fnt


def _title_lines(draw, text, max_w):
    """(lines, font): one big line if possible, else two balanced lines, else one cut line"""
    bold = "roboto/Roboto-Bold.ttf"
    for size in range(58, 29, -1):
        fnt = _font(bold, size)
        if draw.textlength(text, font=fnt) <= max_w:
            return [text], fnt
    words = text.split()
    splits = [(" ".join(words[:i]), " ".join(words[i:])) for i in range(1, len(words))]
    for size in range(40, 19, -1):
        fnt = _font(bold, size)
        fitting = [s for s in splits if max(draw.textlength(line, font=fnt) for line in s) <= max_w]
        if fitting:
            return list(min(fitting, key=lambda s: abs(draw.textlength(s[0], font=fnt) -
                                                        draw.textlength(s[1], font=fnt)))), fnt
    fnt = _font(bold, 22)
    return [_cut(draw, text, fnt, max_w)], fnt


def _gradient_background(with_ring):
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / (H - 1)
        d.line([(0, y), (W, y)], fill=(int(10 + 10 * t), int(20 + 90 * t), int(45 + 70 * t)))
    if with_ring:
        d.ellipse([300, -120, 620, 200], fill=(34, 211, 238))
        d.ellipse([318, -102, 602, 182], fill=(14, 40, 70))
    return img


def _photo_background(photo):
    img = ImageOps.fit(ImageOps.exif_transpose(Image.open(photo)).convert("RGB"), (W, H), Image.LANCZOS)
    img = ImageEnhance.Brightness(img).enhance(0.6).convert("RGBA")
    # Darker on the left, where the text sits
    shade = Image.new("RGBA", (W, H))
    d = ImageDraw.Draw(shade)
    for x in range(W):
        d.line([(x, 0), (x, H)], fill=(0, 0, 0, int(150 * max(0.0, 1 - x / (W * 0.75)))))
    return Image.alpha_composite(img, shade).convert("RGB")


def make_splash(title, subtitle="", footer="", photo=None, logo=None):
    # Decorative ring only on the plain background, and only if the title fits beside it without being cut
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    ring = not photo and not logo and " ".join(_title_lines(probe, title, 268)[0]) == " ".join(title.split())
    img = _photo_background(photo) if photo else _gradient_background(with_ring=ring)
    title_w = subtitle_w = W - 2 * MARGIN
    if ring:
        title_w, subtitle_w = 268, 300  # stay left of the decorative ring
    if logo:
        mark = ImageOps.contain(ImageOps.exif_transpose(Image.open(logo)).convert("RGBA"), (LOGO_BOX, LOGO_BOX),
                                Image.LANCZOS)
        img.paste(mark, (W - MARGIN - mark.width, MARGIN), mark)
        title_w = subtitle_w = W - 2 * MARGIN - mark.width - 16  # title and subtitle share their rows with the logo
    d = ImageDraw.Draw(img)
    if title:
        lines, fnt = _title_lines(d, title, title_w)
        for i, line in enumerate(reversed(lines)):  # the last line always sits on the same baseline
            d.text((MARGIN, 110 - i * round(fnt.size * 1.15)), line, font=fnt, fill=(255, 255, 255), anchor="ls")
    if subtitle:
        text, fnt = _fit(d, subtitle, "roboto/Roboto-Medium.ttf", 22, subtitle_w, 13)
        d.text((MARGIN + 2, 150), text, font=fnt, fill=(165, 243, 252), anchor="ls")
    if footer:
        text, fnt = _fit(d, footer, "roboto/Roboto-Regular.ttf", 17, W - 2 * MARGIN, 11)
        d.text((MARGIN + 2, 280), text, font=fnt, fill=(226, 232, 240), anchor="ls")
    return img
