"""Лёгкий зацикленный снег поверх готовой карточки. Один общий цветовой набор сохраняет текст."""

from io import BytesIO
from math import cos, pi, sin
from random import Random

from PIL import Image, ImageDraw


BANNER_WIDTH = 1500
BANNER_HEIGHT = 480


def winter_px(*values):
    pixels = tuple(round(value * BANNER_WIDTH / 1000) for value in values)
    return pixels[0] if len(pixels) == 1 else pixels


def snowfall(image):
    rgb = image.convert("RGB")
    # Include the portrait a second time in the palette sample so the dark sky
    # does not crowd out the warm shades in faces, hair and embroidery.
    sample = Image.new("RGB", (rgb.width, rgb.height + BANNER_HEIGHT))
    sample.paste(rgb, (0, 0))
    portrait = rgb.crop((0, 0, rgb.width * 31 // 100, BANNER_HEIGHT))
    sample.paste(portrait.resize((rgb.width, BANNER_HEIGHT), Image.Resampling.NEAREST), (0, rgb.height))
    colors = sample.quantize(colors=244, method=Image.Quantize.MEDIANCUT)
    base = rgb.quantize(palette=colors, dither=Image.Dither.FLOYDSTEINBERG)
    palette = base.getpalette()[: 244 * 3]
    palette += [0] * (244 * 3 - len(palette))
    for n in range(12):
        palette.extend((68 + 15 * n, 85 + 14 * n, 108 + 13 * n))
    base.putpalette(palette)
    scale = base.width / 1000
    rng = Random(1512)
    flakes = [
        (
            rng.uniform(12, 988),
            rng.uniform(-70, 305),
            rng.random(),
            rng.uniform(40, 100),
            rng.choice((1, 1, 2, 2, 3)),
        )
        for _ in range(200)
    ]
    frames = []
    for frame in range(28):
        im = base.copy()
        draw = ImageDraw.Draw(im)
        for x, y, offset, travel, radius in flakes:
            phase = (frame / 28 + offset) % 1
            fy = int(y + phase * travel)
            fx = int(x - phase * travel * 0.31 + 2 * sin(phase * 2 * pi))
            if not (13 < fx < 987 and 13 < fy < 305):
                continue
            if (315 < fx < 966 and 75 < fy < 235) or fx < 317:
                continue
            strength = (1 - cos(phase * 2 * pi)) * 0.5
            if strength < 0.16:
                continue
            fx, fy = round(fx * scale), round(fy * scale)
            radius = max(1, round(radius * scale))
            tone = min(255, 244 + round(strength * (6 + radius)))
            draw.line((fx + radius, fy - radius * 2, fx, fy), fill=tone, width=radius)
            if radius >= 3:
                draw.ellipse((fx - 2, fy - 2, fx + 2, fy + 2), fill=min(255, tone + 2))
        frames.append(im)
    out = BytesIO()
    frames[0].save(
        out, "GIF", save_all=True, append_images=frames[1:], duration=100, loop=0, disposal=1, optimize=True
    )
    return out.getvalue()
