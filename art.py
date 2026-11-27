"""
Пиксельная графика Seikatsu Dealer: баннеры команд и эмодзи.
Всё рисуется кодом из banner.png при запуске и кешируется в папке art/.
"""
import math
import os

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageOps

RED = (209, 53, 57)
DARK_RED = (150, 28, 34)
RAY = (196, 150, 118)
SHADOW = (60, 10, 14)
CREAM = (250, 236, 222)
GOLD = (240, 190, 70)
GOLD_D = (180, 120, 30)
BLACK = (25, 12, 14)
WHITE = (250, 246, 240)
GREEN = (90, 170, 90)
BLUE = (80, 120, 200)

# команда: (заголовок, подзаголовок)
BANNERS = {
    "help": ("SEIKATSU", "DEALER  •  ПОМОЩЬ"),
    "work": ("РАБОТА", "ТРУД • МОНЕТЫ"),
    "daily": ("НАГРАДА", "КАЖДЫЙ ДЕНЬ"),
    "balance": ("БАЛАНС", "КОШЕЛЁК  •  БАНК"),
    "coinflip": ("МОНЕТКА", "ОРЁЛ ИЛИ РЕШКА"),
    "slots": ("СЛОТЫ", "ИСПЫТАЙ УДАЧУ"),
    "shop": ("МАГАЗИН", "ТРАТЬ С УМОМ"),
    "top": ("ТОП", "САМЫЕ БОГАТЫЕ"),
    "rob": ("ОГРАБЛЕНИЕ", "РИСК  •  НАГРАДА"),
}

# персонажи из листа chars.png: команда -> (x1, y1, x2, y2)
CHAR_BOXES = {
    "work": (405, 50, 630, 350),
    "daily": (600, 50, 825, 350),
    "balance": (10, 40, 235, 340),
    "coinflip": (205, 40, 430, 340),
    "slots": (205, 40, 430, 340),
    "shop": (795, 50, 1020, 350),
    "top": (410, 590, 690, 963),
    "rob": (720, 600, 1000, 973),
}

S = 6  # размер «пикселя»


def _font_path():
    try:
        import matplotlib  # в нём есть шрифт DejaVu с кириллицей
        p = os.path.join(matplotlib.get_data_path(), "fonts", "ttf", "DejaVuSans-Bold.ttf")
        if os.path.exists(p):
            return p
    except ImportError:
        pass
    return None


FONT_PATH = _font_path()


def _font(size: int):
    if FONT_PATH:
        return ImageFont.truetype(FONT_PATH, size)
    return ImageFont.load_default(size=size)


def make_banner(char: Image.Image, title: str, subtitle: str,
                W: int = 1200, H: int = 400) -> Image.Image:
    """Баннер: персонаж слева, лучи, крупная пиксельная надпись справа."""
    w, h = W // S, H // S
    char = char.convert("RGB")
    CW = round(H * char.width / char.height)
    char = char.resize((CW, H), Image.LANCZOS)
    cwl = CW // S
    cx, cy = cwl // 2, int(0.36 * h)
    lo = Image.new("RGB", (w, h), RED)
    d = ImageDraw.Draw(lo)
    for i in range(36):
        a = math.radians(i * 10 + 5)
        d.line([(cx, cy), (cx + math.cos(a) * 400, cy + math.sin(a) * 400)], fill=RAY, width=1)
    mask = Image.new("L", (w, h), 0)
    md = ImageDraw.Draw(mask)
    for x in range(w):
        md.line([(x, 0), (x, h)], fill=max(0, min(170, (x - cwl - 6) * 5)))
    lo = Image.composite(Image.new("RGB", (w, h), DARK_RED), lo, mask)
    d = ImageDraw.Draw(lo)
    d.fontmode = "1"
    tx = cwl + 14
    room = w - tx - 8
    size = 26
    f1 = _font(size)
    while size > 10 and d.textlength(title, font=f1) > room:
        size -= 1
        f1 = _font(size)
    s2 = 9
    f2 = _font(s2)
    while s2 > 6 and d.textlength(subtitle, font=f2) > room:
        s2 -= 1
        f2 = _font(s2)
    ty = h // 2 - size + 2
    d.text((tx + 1, ty + 1), title, font=f1, fill=SHADOW)
    d.text((tx, ty), title, font=f1, fill=CREAM)
    ly = ty + size + 6
    d.line([(tx, ly), (tx + min(room, 120), ly)], fill=RAY)
    d.text((tx + 1, ly + 5), subtitle, font=f2, fill=SHADOW)
    d.text((tx, ly + 4), subtitle, font=f2, fill=RAY)
    big = lo.resize((W, H), Image.NEAREST)
    fade = Image.new("L", (CW, H), 255)
    fd = ImageDraw.Draw(fade)
    for x in range(CW - 30, CW):
        fd.line([(x, 0), (x, H)], fill=int(255 * (CW - x) / 30))
    big.paste(char, (0, 0), fade)
    return big.quantize(colors=64)


# ───────── эмодзи 32×32, увеличиваются до 128 ─────────
def _canvas():
    im = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    return im, ImageDraw.Draw(im)


def emoji_coin():
    im, d = _canvas()
    d.ellipse([3, 3, 28, 28], fill=GOLD_D)
    d.ellipse([3, 2, 28, 26], fill=GOLD)
    d.ellipse([7, 6, 24, 22], outline=GOLD_D)
    d.ellipse([11, 10, 20, 18], outline=GOLD_D, width=2)
    d.point([(8, 7), (9, 6), (7, 8)], fill=WHITE)
    return im


def emoji_gift():
    im, d = _canvas()
    d.rectangle([5, 13, 26, 28], fill=RED)
    d.rectangle([3, 9, 28, 14], fill=DARK_RED)
    d.rectangle([14, 9, 17, 28], fill=GOLD)
    d.rectangle([3, 11, 28, 12], fill=GOLD)
    d.ellipse([8, 3, 15, 10], outline=GOLD, width=2)
    d.ellipse([16, 3, 23, 10], outline=GOLD, width=2)
    return im


def emoji_work():
    im, d = _canvas()
    d.rectangle([11, 5, 20, 9], outline=SHADOW, width=2)
    d.rectangle([3, 9, 28, 27], fill=(120, 70, 40))
    d.rectangle([3, 9, 28, 15], fill=(150, 90, 50))
    d.rectangle([14, 13, 17, 18], fill=GOLD)
    return im


def emoji_bank():
    im, d = _canvas()
    d.polygon([(16, 2), (2, 10), (29, 10)], fill=CREAM)
    d.rectangle([3, 10, 28, 12], fill=RAY)
    for x in (5, 11, 18, 24):
        d.rectangle([x, 13, x + 3, 24], fill=CREAM)
    d.rectangle([2, 25, 29, 28], fill=RAY)
    d.ellipse([13, 4, 18, 9], fill=GOLD)
    return im


def emoji_dice():
    im, d = _canvas()
    d.rounded_rectangle([3, 3, 28, 28], radius=5, fill=WHITE, outline=(200, 190, 180), width=2)
    for x, y in [(9, 9), (16, 16), (22, 22), (22, 9), (9, 22)]:
        d.ellipse([x - 2, y - 2, x + 2, y + 2], fill=RED)
    return im


def emoji_shop():
    im, d = _canvas()
    d.line([(2, 6), (7, 6), (11, 21), (25, 21)], fill=SHADOW, width=2)
    d.polygon([(8, 9), (28, 9), (25, 18), (10, 18)], fill=RED)
    d.ellipse([10, 23, 14, 27], fill=SHADOW)
    d.ellipse([21, 23, 25, 27], fill=SHADOW)
    return im


def emoji_trophy():
    im, d = _canvas()
    d.rectangle([9, 3, 22, 14], fill=GOLD)
    d.pieslice([9, 6, 22, 20], 0, 180, fill=GOLD)
    d.arc([3, 5, 12, 14], 90, 270, fill=GOLD_D, width=2)
    d.arc([19, 5, 28, 14], 270, 90, fill=GOLD_D, width=2)
    d.rectangle([14, 19, 17, 23], fill=GOLD_D)
    d.rectangle([9, 24, 22, 28], fill=(120, 70, 40))
    d.point([(11, 5), (11, 6), (12, 5)], fill=WHITE)
    return im


def emoji_bag():
    im, d = _canvas()
    d.ellipse([4, 9, 27, 29], fill=(140, 90, 50))
    d.polygon([(11, 4), (21, 4), (18, 10), (14, 10)], fill=(140, 90, 50))
    d.rectangle([12, 9, 19, 11], fill=GOLD)
    d.rectangle([15, 14, 16, 25], fill=GOLD)
    d.arc([11, 14, 20, 20], 90, 360, fill=GOLD, width=2)
    d.arc([11, 19, 20, 25], 270, 180, fill=GOLD, width=2)
    return im


EMOJIS = {
    "sd_coin": emoji_coin,
    "sd_gift": emoji_gift,
    "sd_work": emoji_work,
    "sd_bank": emoji_bank,
    "sd_dice": emoji_dice,
    "sd_shop": emoji_shop,
    "sd_top": emoji_trophy,
    "sd_rob": emoji_bag,
}


def emoji_png(name: str) -> Image.Image:
    return EMOJIS[name]().resize((128, 128), Image.NEAREST)


def build_all(src_path: str, out_dir: str, chars_path: str = "") -> dict:
    """Рисует все баннеры (если их ещё нет) и возвращает {команда: путь}."""
    os.makedirs(out_dir, exist_ok=True)
    if not os.path.exists(src_path):
        return {}
    src = Image.open(src_path)
    main = src.crop((0, 0, src.height, src.height))
    sheet = Image.open(chars_path) if chars_path and os.path.exists(chars_path) else None
    paths = {}
    for key, (title, sub) in BANNERS.items():
        p = os.path.join(out_dir, f"banner_{key}.png")
        if not os.path.exists(p):
            char = main
            if sheet is not None and key in CHAR_BOXES:
                char = sheet.crop(CHAR_BOXES[key])
            make_banner(char, title, sub).save(p, optimize=True)
        paths[key] = p
    return paths


# ───────── карточка профиля (HUD) ─────────
def _fit(d, text, size, room, min_size=7):
    f = _font(size)
    while size > min_size and d.textlength(text, font=f) > room:
        size -= 1
        f = _font(size)
    while len(text) > 3 and d.textlength(text, font=f) > room:
        text = text[:-2].rstrip() + "…"
    return text, f


# ───────── карточки профиля и пары (рисованный стиль) ─────────
import io as _io
import numpy as _np

_FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
P_CREAM, P_GOLD, P_GOLD_D, P_MUTED = (242, 226, 200), (214, 172, 92), (140, 104, 48), (176, 140, 110)
P_PANEL = (30, 10, 13)


def _pfont(kind: str, size: int):
    """kind: sc (капитель) / text. Если шрифтов нет — обычный шрифт системы."""
    name = {"sc": "cormorant-sc-700.ttf", "sc6": "cormorant-sc-600.ttf",
            "text": "cormorant-garamond-700.ttf"}[kind]
    try:
        return ImageFont.truetype(os.path.join(_FONT_DIR, name), size)
    except OSError:
        return _font(max(8, size // 2))


try:
    from PIL import features as _features
    _LNUM = ["lnum"] if _features.check("raqm") else None
except Exception:
    _LNUM = None


def _tl(d, text, font):
    return d.textlength(text, font=font, features=_LNUM)


def _t(d, xy, text, font, fill):
    d.text(xy, text, font=font, fill=fill, features=_LNUM)


def _pfit(d, text, kind, size, room, min_size=14):
    f = _pfont(kind, size)
    while size > min_size and _tl(d, text, f) > room:
        size -= 1
        f = _pfont(kind, size)
    while len(text) > 3 and _tl(d, text, f) > room:
        text = text[:-2].rstrip() + "…"
    return text, f


def _pbg(w, h, cx=0.22):
    y, x = _np.mgrid[0:h, 0:w].astype(_np.float32)
    d = _np.sqrt(((x - w * cx) / (w * 0.75)) ** 2 + ((y - h * 0.45) / (h * 1.1)) ** 2)
    t = _np.clip(d, 0, 1)[..., None]
    img = _np.array([96, 18, 26]) * (1 - t) + _np.array([18, 6, 9]) * t
    img += _np.random.default_rng(7).normal(0, 3.0, img.shape)
    return Image.fromarray(_np.clip(img, 0, 255).astype(_np.uint8), "RGB")


def _pframe(img):
    d = ImageDraw.Draw(img)
    w, h = img.size
    d.rectangle([10, 10, w - 11, h - 11], outline=P_GOLD_D, width=2)
    for cx, cy in ((10, 10), (w - 11, 10), (10, h - 11), (w - 11, h - 11)):
        d.polygon([(cx, cy - 7), (cx + 7, cy), (cx, cy + 7), (cx - 7, cy)], fill=P_GOLD)


def portrait_path(banner_path):
    """Locate the transparent portrait beside a banner, including older PNG assets."""
    if not banner_path:
        return None
    banner_dir, filename = os.path.split(os.path.abspath(banner_path))
    stem = os.path.splitext(filename)[0]
    for extension in (".webp", ".png"):
        path = os.path.join(os.path.dirname(banner_dir), "chars", stem + extension)
        if os.path.isfile(path):
            return path
    return None


def _char_for(banner_path):
    path = portrait_path(banner_path)
    if path is None:
        return None
    with Image.open(path) as portrait:
        return portrait.convert("RGBA")


WIDE_RANK_PORTRAITS = {
    "faith_5_f", "faith_6", "faith_6_f", "faith_7", "faith_7_f", "faith_9", "noble_6",
}


def _portrait(img, banner_path, zone, *, skin=""):
    """Персонаж в своей левой зоне карточки (не заходит на текст). Возвращает x начала текста."""
    W, H = img.size
    char = _char_for(banner_path)
    inset, top = 12, 24
    bottom = H - inset
    layer = Image.new("RGBA", (zone, H))
    if char is not None:
        scale = H * 1.5 / char.height
        stem = os.path.splitext(os.path.basename(banner_path))[0]
        if stem.startswith(("noble_", "faith_")):
            scale = min(1, (bottom - top) / char.height)
        keep_full_width = stem in WIDE_RANK_PORTRAITS
        if keep_full_width:
            # These poses hold their props away from the body.
            scale = min(scale, (zone - 2 * inset) / char.width)
        portrait = char.resize((round(char.width * scale), round(char.height * scale)), Image.LANCZOS)
        x = (zone - portrait.width) // 2
        if keep_full_width:
            top += (bottom - top - portrait.height) // 2
            bottom = top + portrait.height
        layer.paste(portrait, (x, top))
    elif not skin and banner_path and os.path.exists(banner_path):   # запасной вариант: кусок баннера
        with Image.open(banner_path) as banner:
            part = banner.crop((14, 14, 14 + round(zone * (banner.height - 28) / H), banner.height - 14))
            layer.paste(part.resize((zone, H), Image.LANCZOS), (0, 0))
    else:
        return 40

    mask = Image.new("L", layer.size)
    paint = ImageDraw.Draw(mask)
    fade = round(H * 0.08)
    paint.rectangle((inset, inset, zone - 1, bottom - fade), fill=255)
    for y in range(bottom - fade + 1, bottom):
        opacity = round(255 * (bottom - y) / fade)
        paint.line((inset, y, zone - 1, y), fill=opacity)
    alpha = ImageChops.multiply(layer.getchannel("A"), mask)
    img.paste(layer, (0, 0), alpha)

    d = ImageDraw.Draw(img)
    d.rectangle([zone, 0, W, H], fill={"hall": (12,22,44), "yard": (19,32,51), "night": (8,31,38)}.get(skin,(16,5,8)))       # спокойный фон под текстом
    d.line([(zone, 18), (zone, H - 18)], fill=P_GOLD_D, width=2)
    d.polygon([(zone, H // 2 - 8), (zone + 8, H // 2), (zone, H // 2 + 8), (zone - 8, H // 2)], fill=P_GOLD)
    return zone + 34


def _avatar(img, data: bytes | None, xy, size):
    d = ImageDraw.Draw(img)
    x, y = xy
    d.ellipse([x - 4, y - 4, x + size + 4, y + size + 4], fill=P_GOLD)
    d.ellipse([x - 1, y - 1, x + size + 1, y + size + 1], fill=(20, 6, 8))
    try:
        av = Image.open(_io.BytesIO(data)).convert("RGB").resize((size, size), Image.LANCZOS)
    except Exception:
        return
    m = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(m).ellipse([0, 0, size * 4 - 1, size * 4 - 1], fill=255)
    img.paste(av, (x, y), m.resize((size, size), Image.LANCZOS))


def _shadow_text(d, xy, text, font, fill):
    _t(d, (xy[0] + 2, xy[1] + 3), text, font, (0, 0, 0))
    _t(d, xy, text, font, fill)


def _bar(d, x0, y, x1, have, need, label):
    f = _pfont("sc6", 22)
    _shadow_text(d, (x0, y), label, f, P_CREAM)
    pct = f"{have * 100 // max(1, need)}%"
    _t(d, (x1 - _tl(d, pct, f), y), pct, f, P_GOLD)
    y += 32
    d.rounded_rectangle([x0, y, x1, y + 16], radius=8, fill=(12, 4, 6), outline=P_GOLD_D, width=1)
    fill = round((x1 - x0 - 6) * min(have, need) / max(1, need))
    if fill > 6:
        d.rounded_rectangle([x0 + 3, y + 3, x0 + 3 + fill, y + 13], radius=5, fill=P_GOLD)
    return y + 16


def _cells(img, d, cells, x0, y, x1, cols, h=74, gap=12, panel=P_PANEL):
    cw = (x1 - x0 - gap * (cols - 1)) / cols
    for i, cell in enumerate(cells):
        label, value = cell[:2]
        icon = cell[2] if len(cell) > 2 else None
        cx = x0 + (i % cols) * (cw + gap)
        cy = y + (i // cols) * (h + gap)
        d.rounded_rectangle([cx, cy, cx + cw, cy + h], radius=8, fill=panel)
        d.rectangle([cx, cy + 10, cx + 3, cy + h - 10], fill=P_GOLD)
        badge = _icon(icon, 36) if icon else None
        text_w = cw - (70 if badge else 28)
        lab, f = _pfit(d, str(label).upper(), "sc6", 19, text_w, 12)
        _t(d, (cx + 16, cy + 9), lab, f, P_MUTED)
        val, f = _pfit(d, str(value), "text", 30, text_w, 15)
        _t(d, (cx + 16, cy + 33), val, f, P_CREAM)
        if badge:
            img.paste(badge, (round(cx + cw - 48), round(cy + (h - 36) / 2)), badge)


def _ring_strip(img, d, rings, left, top, right, caption):
    _t(d, (left, top), caption, _pfont("sc6", 19), P_GOLD)
    gap = 7
    width = (right - left - gap * (len(rings) - 1)) / len(rings)
    for i, (label, icon) in enumerate(rings):
        x = round(left + i * (width + gap))
        y = top + 25
        d.rounded_rectangle((x, y, round(x + width), y + 34), 6, fill=P_PANEL, outline=P_GOLD_D)
        badge = _icon(icon, 27)
        if badge:
            img.paste(badge, (x + 5, y + 4), badge)
        label, font = _pfit(d, label, "text", 22, width - 45, 12)
        _t(d, (x + 37, y + 4), label, font, P_CREAM)


def profile_card(banner_path, data: dict, avatar: bytes | None = None,
                 W: int = 1000, H: int = 600) -> bytes:
    """Профиль: персонаж слева, аватар, имя, титул, опыт и карточки характеристик."""
    skin = data.get("skin", "")
    badges = data.get("showcase") or []
    rings = data.get("rings") or []
    ring_top = H - 52
    if rings:
        H += 75 if badges else 30
    if skin:
        y, x = _np.mgrid[:H,:W]
        glow = _np.exp(-((x-W*.20)/(W*.29))**2 - ((y-H*.32)/(H*.70))**2)
        if skin == "night":
            glow *= .55 + .45*_np.sin(x/68 + y/107)**2
        base, light = ((8,17,36),(47,78,118)) if skin == "hall" else ((5,21,31),(33,105,99))
        rgb = _np.array(base) + glow[...,None]*(_np.array(light)-base)
        img = Image.fromarray(rgb.astype("uint8"), "RGB")
        sky = ImageDraw.Draw(img)
        rng = _np.random.default_rng(26)
        for sx, sy in zip(rng.integers(12,350,65),rng.integers(16,H-18,65)):
            sky.ellipse((sx,sy,sx+2,sy+2),fill=(164,190,210))
        if skin == "hall":
            sky.ellipse((45,43,111,109),fill=(198,215,228))
            sky.ellipse((64,36,127,99),fill=(35,57,87))
    else:
        img = _pbg(W, H)
    if skin=="yard":
        from PIL import ImageOps
        with Image.open(os.path.join(os.path.dirname(__file__), "winter_art", "courtyard.jpg")) as courtyard:
            img.paste(ImageOps.fit(courtyard.convert("RGB"), (360,H),centering=(.44,.5)),(0,0))
    tx = _portrait(img, banner_path, 360, skin=skin)
    d = ImageDraw.Draw(img)
    right = W - 34
    _avatar(img, avatar, (tx, 34), 78)
    frame = data.get("frame")
    if frame in ("frost", "crown","lace","aurora"):
        rim = _icon("wb_"+frame if frame in ("lace","aurora") else "wb_frame", 127)
        if rim:
            img.paste(rim,(tx-24,9),rim)
        if frame == "crown":
            crown = _icon("wb_crown",40)
            if crown:
                img.paste(crown,(tx+19,10),crown)
    nx = tx + 100
    name, f = _pfit(d, str(data["name"]), "sc", 52, right - nx, 24)
    _shadow_text(d, (nx, 26), name, f, P_CREAM)
    head = f"{data['title']} — уровень {data['level']}" if data.get("title") else f"Уровень {data['level']}"
    head, f = _pfit(d, head, "sc6", 28, right - nx, 16)
    _t(d, (nx, 86), head, f, P_GOLD)
    y = _bar(d, tx, 140, right, data["have"], max(1, data["need"]),
             f"Опыт {data['have']:,} / {data['need']:,}".replace(",", " "))
    _cells(img, d, data["cells"], tx, y + 22, right, cols=2,
           panel={"hall": (25,40,65), "yard": (36,55,77), "night": (15,52,55)}.get(skin,P_PANEL))
    if rings:
        _ring_strip(img, d, rings, tx, ring_top, right, "КОЛЛЕКЦИЯ КОЛЕЦ")
    if badges:
        gap = 10
        width = (right - tx - 2 * gap) / 3
        top, centre = H - 57, H - 38
        for index, (key, label, name, _) in enumerate(badges[:3]):
            left = round(tx + index * (width + gap))
            end = round(tx + index * (width + gap) + width)
            d.rounded_rectangle((left, top, end, H - 19), radius=7, fill=P_PANEL, outline=P_GOLD_D)
            icon = _icon(name, 26)
            if icon is None and key == "pair:weekly":
                icon = _icon("couple", 26)
            if icon:
                img.paste(icon, (left + 8, centre - 13), icon)
            text_x = left + (41 if icon else 10)
            label, font = _pfit(d, label, "sc6", 18, end - text_x - 8, 12)
            _, text_top, _, text_bottom = d.textbbox((0, 0), label, font=font, features=_LNUM)
            _t(d, (text_x, centre - (text_top + text_bottom) // 2), label, font, P_GOLD)
    _pframe(img)
    out = _io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def _heart(d, cx, cy, r, fill):
    d.ellipse([cx - r, cy - r * 0.6, cx, cy + r * 0.4], fill=fill)
    d.ellipse([cx, cy - r * 0.6, cx + r, cy + r * 0.4], fill=fill)
    d.polygon([(cx - r * 0.98, cy), (cx + r * 0.98, cy), (cx, cy + r * 1.15)], fill=fill)


def couple_card(banner_path, data: dict, avatar_a: bytes | None = None,
                avatar_b: bytes | None = None, W: int = 1000, H: int = 500) -> bytes:
    """Парный профиль с опытом пары и коллекцией колец."""
    collection = data.get("rings") or []
    if collection:
        H += 33
    img = _pbg(W, H)
    tx = _portrait(img, banner_path, 400)
    d = ImageDraw.Draw(img)
    right = W - 34
    mid = (tx + right) // 2
    size = 92
    _avatar(img, avatar_a, (mid - size - 38, 30), size)
    _avatar(img, avatar_b, (mid + 38, 30), size)
    rings = _icon("wb_rings", 68) if data.get("moon_rings") else None
    if rings:
        img.paste(rings, (mid-34,38), rings)
    else:
        _heart(d, mid, 70, 20, P_GOLD)
    if rings and data.get("engraved"):
        d.text((mid,116), "Первая зимняя луна", font=_pfont("sc6",18), fill=P_GOLD, anchor="mm")
    names = " & ".join(str(n) for n in data["names"])
    names, f = _pfit(d, names, "sc", 44, right - tx, 22)
    _shadow_text(d, (mid - _tl(d, names, f) / 2, 136), names, f, P_CREAM)
    lv = f"Уровень пары {data['level']}"
    f = _pfont("sc6", 28)
    _t(d, (mid - _tl(d, lv, f) / 2, 190), lv, f, P_GOLD)
    y = _bar(d, tx, 236, right, data["have"], max(1, data["need"]),
             f"Опыт пары {data['have']:,} / {data['need']:,}".replace(",", " "))
    _cells(img, d, data["cells"][:3], tx, y + 24, right, cols=3, h=80)
    if data.get("anniversary"):
        label = f"Годовщина · {data['anniversary']} дней вместе"
        label, font = _pfit(d, label, "sc6", 24, right - tx - 42)
        badge = _icon("top", 30)
        if badge:
            img.paste(badge, (tx, y + 117), badge)
        _t(d, (tx + 42, y + 120), label, font, P_GOLD)
    if collection:
        _ring_strip(img, d, collection, tx, H - 78, right, "КОЛЛЕКЦИЯ ПАРЫ")
    _pframe(img)
    out = _io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


# ───────── карточки-панели (меню, казна) ─────────
_ICON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")
P_TILE = (24, 8, 11)


def _icon(name, size):
    p = os.path.join(_ICON_DIR, f"{name}.png")
    if not name or not os.path.exists(p):
        return None
    return Image.open(p).convert("RGBA").resize((size, size), Image.LANCZOS)


def role_swatch(name: str, color: int) -> bytes:
    """Показывает цвет роли и пример имени на тёмном фоне."""
    img = _pbg(730, 165, cx=0.34)
    draw = ImageDraw.Draw(img)
    rgb = ((color >> 16) & 255, (color >> 8) & 255, color & 255)
    draw.rounded_rectangle((28, 36, 124, 131), radius=14, fill=rgb, outline=P_CREAM, width=2)
    _t(draw, (156, 29), f"Цвет роли · #{color:06X}", _pfont("sc6", 24), P_GOLD)
    draw.rounded_rectangle((149, 69, 698, 130), radius=9, fill=(43, 45, 49))
    text, font = _pfit(draw, name, "text", 34, 512)
    _t(draw, (164, 80), text, font, rgb)
    _pframe(img)
    out = _io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def ring_collection_card(banner_path, rings: list[dict], W: int = 1000, H: int = 370) -> bytes:
    """Коллекция колец: цветные значки для доступных, серые — для ещё не найденных."""
    img = _pbg(W, H)
    _portrait(img, banner_path, 300)
    d = ImageDraw.Draw(img)
    x0, right, y0 = 340, W - 30, 110
    title, f = _pfit(d, "КОЛЛЕКЦИЯ КОЛЕЦ", "sc", 42, right - x0, 20)
    _shadow_text(d, (x0, 34), title, f, P_CREAM)
    cw, gap, h = (right - x0 - 2 * 12) / 3, 12, 220
    for i, ring in enumerate(rings):
        x = x0 + i * (cw + gap)
        d.rounded_rectangle([x, y0, x + cw, y0 + h], radius=10, fill=P_PANEL,
                            outline=P_GOLD_D if ring["owned"] else (75, 66, 64), width=2)
        badge = _icon(f"ring_{ring['key']}", 86)
        if badge:
            if not ring["owned"]:
                grey = ImageOps.grayscale(badge).convert("RGBA")
                grey.putalpha(badge.getchannel("A"))
                badge = grey
            img.paste(badge, (round(x + (cw - 86) / 2), y0 + 18), badge)
        name, f = _pfit(d, ring["name"], "text", 25, cw - 20, 14)
        _t(d, (x + (cw - _tl(d, name, f)) / 2, y0 + 118), name, f,
           P_CREAM if ring["owned"] else P_MUTED)
        if ring["current"]:
            status = "В ПРОФИЛЕ · ЕСТЬ"
            fill = P_GOLD
        elif ring["owned"]:
            status = "ЕСТЬ"
            fill = P_GOLD
        else:
            status = f"НЕТ · {ring['price']:,} МОН.".replace(",", " ")
            fill = P_MUTED
        status, f = _pfit(d, status, "sc6", 18, cw - 20, 12)
        _t(d, (x + (cw - _tl(d, status, f)) / 2, y0 + 166), status, f, fill)
    _pframe(img)
    out = _io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def panel_card(banner_path, title: str, subtitle: str = "", icon: str = "", bar=None,
               tiles=(), lines=(), W: int = 1200, avatar: bytes | None = None) -> bytes:
    """Баннер сверху, ниже — заголовок, шкала, плитки с цифрами и строки.

    bar = (доля 0..1, подпись слева, подпись справа)
    tiles = [(иконка, подпись, значение, пояснение, готово: bool)]
    lines = [(иконка, текст)]
    """
    pad = 44
    ban = None
    if banner_path and os.path.exists(banner_path):
        ban = Image.open(banner_path).convert("RGB")
        ban = ban.resize((W, round(ban.height * W / ban.width)), Image.LANCZOS)
    top = ban.height if ban else 0
    H = top + 36 + 62 + (40 if subtitle else 0) + (62 if bar else 0) \
        + (150 if tiles else 0) + 48 * len(lines) + 30
    img = _pbg(W, H, cx=0.5)
    d = ImageDraw.Draw(img)
    d.rectangle([0, top, W, H], fill=(16, 5, 8))
    if ban:
        img.paste(ban, (0, 0))
        d.line([(0, top), (W, top)], fill=P_GOLD_D, width=2)
    y = top + 32
    x = pad
    ic = _icon(icon, 48)
    if ic:
        img.paste(ic, (x, y + 4), ic)
        x += 62
    av_w = 0
    if avatar:   # аватар участника справа от заголовка, в золотой рамке
        try:
            av = Image.open(_io.BytesIO(avatar)).convert("RGB").resize((112, 112), Image.LANCZOS)
            ax, ay = W - pad - 112, top + 20
            d.rectangle([ax - 5, ay - 5, ax + 116, ay + 116], fill=(8, 2, 4), outline=P_GOLD, width=3)
            img.paste(av, (ax, ay))
            d.rectangle([ax - 1, ay - 1, ax + 112, ay + 112], outline=P_GOLD_D, width=1)
            av_w = 150
        except Exception:
            pass
    t, f = _pfit(d, title, "sc", 58, W - pad - x - av_w, 26)
    _shadow_text(d, (x, y - 8), t, f, P_GOLD)
    y += 62
    if subtitle:
        s, f = _pfit(d, subtitle, "sc6", 30, W - 2 * pad - av_w, 16)
        _t(d, (pad, y), s, f, P_MUTED)
        y += 40
    if bar:
        frac, left, right = bar
        f = _pfont("sc6", 24)
        _t(d, (pad, y), left, f, P_CREAM)
        _t(d, (W - pad - _tl(d, right, f), y), right, f, P_MUTED)
        y += 32
        d.rounded_rectangle([pad, y, W - pad, y + 16], radius=8, fill=(8, 2, 4), outline=P_GOLD_D)
        fill = round((W - 2 * pad - 6) * max(0.0, min(1.0, frac)))
        if fill > 6:
            d.rounded_rectangle([pad + 3, y + 3, pad + 3 + fill, y + 13], radius=5, fill=P_GOLD)
        y += 30
    if tiles:
        y += 8
        n, gap = len(tiles), 18
        cw = (W - 2 * pad - gap * (n - 1)) / n
        for i, (tic, label, value, note, ready) in enumerate(tiles):
            cx = pad + i * (cw + gap)
            d.rounded_rectangle([cx, y, cx + cw, y + 128], radius=12, fill=P_TILE,
                                outline=P_GOLD if ready else P_GOLD_D, width=2 if ready else 1)
            ti = _icon(tic, 34)
            lx = cx + 18
            if ti:
                img.paste(ti, (round(lx), y + 14), ti)
                lx += 44
            lab, f = _pfit(d, label.upper(), "sc6", 22, cx + cw - lx - 12, 12)
            _t(d, (lx, y + 18), lab, f, P_MUTED)
            val, f = _pfit(d, str(value), "text", 44, cw - 36, 18)
            _t(d, (cx + 18, y + 52), val, f, P_CREAM)
            if note:
                nt, f = _pfit(d, note, "sc6", 21, cw - 36, 12)
                _t(d, (cx + 18, y + 98), nt, f, P_GOLD if ready else P_MUTED)
        y += 150
    for lic, text in lines:
        lx = pad
        li = _icon(lic, 32)
        if li:
            img.paste(li, (lx, y + 2), li)
            lx += 46
        tx, f = _pfit(d, text, "text", 30, W - pad - lx, 16)
        _t(d, (lx, y), tx, f, P_CREAM)
        y += 48
    _pframe(img)
    out = _io.BytesIO()
    img.save(out, "JPEG", quality=90)
    return out.getvalue()


def court_event_card(banner_path, month, total, goal, personal, personal_goal):
    """Баннер события и две шкалы в одном изображении."""
    with Image.open(banner_path) as source:
        banner = source.convert("RGB")
    width, top = banner.size
    image = Image.new("RGB", (width, top + 216), (27, 9, 13))
    image.paste(banner, (0, 0))
    draw = ImageDraw.Draw(image)

    pad, gap = 44, 24
    tile_width = (width - 2 * pad - gap) // 2
    period_font = _pfont("sc6", 31)
    label_font = _pfont("sc6", 36)
    value_font = _pfont("text", 40)
    _t(draw, (pad, top + 18), f"Вклад за {month}", period_font, P_CREAM)

    for index, (label, points, target) in enumerate((
        ("Весь двор", total, goal), ("Твой вклад", personal, personal_goal),
    )):
        x = pad + index * (tile_width + gap)
        right = x + tile_width
        y = top + 66
        draw.rounded_rectangle((x, y, right, y + 116), radius=12, fill=P_TILE,
                               outline=P_GOLD if points >= target else P_GOLD_D, width=2)
        _t(draw, (x + 22, y + 13), label, label_font, P_CREAM)
        value = f"{points} / {target}"
        _t(draw, (right - 22 - _tl(draw, value, value_font), y + 11), value, value_font, P_GOLD)

        left, right = x + 22, right - 22
        track_y = y + 74
        draw.rounded_rectangle((left, track_y, right, track_y + 20), radius=10, fill=(9, 2, 5),
                               outline=P_GOLD_D, width=2)
        fill = round((right - left - 6) * min(points, target) / target)
        if fill:
            draw.rounded_rectangle((left + 3, track_y + 3, left + 3 + fill, track_y + 17),
                                   radius=min(7, fill // 2), fill=P_GOLD)

    out = _io.BytesIO()
    image.save(out, "JPEG", quality=93)
    return out.getvalue()


_THUMBS = {}


def thumb(char_path: str, size: int = 256) -> bytes | None:
    """Квадратный портрет персонажа для коротких ответов (кешируется)."""
    if not char_path or not os.path.exists(char_path):
        return None
    cache_key = (char_path, size)
    if cache_key in _THUMBS:
        return _THUMBS[cache_key]
    with Image.open(char_path) as portrait:
        ch = portrait.convert("RGBA")
    is_pair = os.path.splitext(os.path.basename(char_path))[0] == "marry"
    fraction = 0.78 if is_pair else 0.65
    side = min(ch.width, round(ch.height * fraction))
    x0 = (ch.width - side) // 2
    top = max(1, round(size * 0.055))
    height = size - top
    width = round(size * 0.94) if is_pair else size
    # Use a square crop throughout so faces keep their proportions.
    face = ch.crop((x0, 0, x0 + side, side)).resize((width, width), Image.LANCZOS)
    bg = _pbg(size, size, cx=0.5).convert("RGBA")
    bg.alpha_composite(face.crop((0, 0, width, height)), ((size - width) // 2, top))
    d = ImageDraw.Draw(bg)
    d.rectangle([3, 3, size - 4, size - 4], outline=P_GOLD_D, width=3)
    out = _io.BytesIO()
    bg.convert("RGB").save(out, "PNG")
    _THUMBS[cache_key] = out.getvalue()
    return _THUMBS[cache_key]

