"""
Пиксельная графика Seikatsu Dealer: баннеры команд и эмодзи.
Всё рисуется кодом из banner.png при запуске и кешируется в папке art/.
"""
import math
import os

from PIL import Image, ImageDraw, ImageFont

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


def profile_card(banner_path, data: dict, avatar: bytes | None = None,
                 W: int = 1200, H: int = 450) -> bytes:
    """Картинка профиля: персонаж работы слева, имя, уровень, шкала опыта и статистика."""
    import io
    P = 3
    w, h = W // P, H // P
    portrait = None
    if banner_path and os.path.exists(banner_path):
        b = Image.open(banner_path).convert("RGB")
        portrait = b.crop((0, 0, 330, b.height)).resize((round(330 * H / b.height), H), Image.LANCZOS)
    x0 = (portrait.width if portrait else 0) // P
    lo = Image.new("RGB", (w, h), RED)
    mask = Image.new("L", (w, h), 0)
    md = ImageDraw.Draw(mask)
    for x in range(w):
        md.line([(x, 0), (x, h)], fill=max(0, min(170, (x - x0) * 6)))
    lo = Image.composite(Image.new("RGB", (w, h), DARK_RED), lo, mask)
    d = ImageDraw.Draw(lo)
    d.fontmode = "1"

    def text(xy, s, f, color):
        d.text((xy[0] + 1, xy[1] + 1), s, font=f, fill=SHADOW)
        d.text(xy, s, font=f, fill=color)

    tx, right = x0 + 10, w - 10
    nx = tx
    if avatar:
        try:
            av = Image.open(io.BytesIO(avatar)).convert("RGB").resize((26, 26), Image.LANCZOS)
            d.rectangle([tx - 1, 7, tx + 26, 34], outline=CREAM)
            lo.paste(av, (tx, 8))
            nx = tx + 32
        except Exception:
            pass
    name, f = _fit(d, str(data["name"]).upper(), 14, right - nx, 9)
    text((nx, 7), name, f, CREAM)
    title, f = _fit(d, f"{data['title']} • УРОВЕНЬ {data['level']}".upper(), 9, right - nx)
    text((nx, 25), title, f, RAY)

    have, need = data["have"], max(1, data["need"])
    f8 = _font(8)
    text((tx, 42), f"ОПЫТ {have} / {need}", f8, CREAM)
    pct = f"{have * 100 // need}%"
    text((right - d.textlength(pct, font=f8), 42), pct, f8, GOLD)
    d.rectangle([tx, 54, right, 62], fill=SHADOW, outline=CREAM)
    fill = (right - tx - 2) * min(have, need) // need
    if fill > 0:
        d.rectangle([tx + 1, 55, tx + 1 + fill, 61], fill=GOLD)

    col = (right - tx) // 2
    for i, (label, value) in enumerate(data["cells"][:6]):
        cx, cy = tx + (i % 2) * col, 71 + (i // 2) * 26
        lab, f = _fit(d, str(label).upper(), 8, col - 6)
        text((cx, cy), lab, f, RAY)
        val, f = _fit(d, str(value).upper(), 11, col - 6, 8)
        text((cx, cy + 10), val, f, CREAM)

    big = lo.resize((W, H), Image.NEAREST)
    if portrait:
        fade = Image.new("L", portrait.size, 255)
        fd = ImageDraw.Draw(fade)
        for x in range(portrait.width - 30, portrait.width):
            fd.line([(x, 0), (x, H)], fill=int(255 * (portrait.width - x) / 30))
        big.paste(portrait, (0, 0), fade)
    out = io.BytesIO()
    big.save(out, "PNG")
    return out.getvalue()
