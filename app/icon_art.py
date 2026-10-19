"""Uygulama simgesi: sıcak sarı zemin üzerinde açık kitaptan filizlenen fide."""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


def _leaf(d: ImageDraw.ImageDraw, base: tuple[float, float], length: float, width: float, angle_deg: float, fill):
    a = math.radians(angle_deg)
    pts = []
    n = 40
    for i in range(n + 1):
        t = i / n
        x = t * length
        y = math.sin(math.pi * t) * width * (1 - 0.25 * t)
        pts.append((x, y))
    for i in range(n, -1, -1):
        t = i / n
        x = t * length
        y = -math.sin(math.pi * t) * width * 0.35 * (1 - 0.25 * t)
        pts.append((x, y))
    bx, by = base
    rot = [(bx + x * math.cos(a) - y * math.sin(a), by - (x * math.sin(a) + y * math.cos(a))) for x, y in pts]
    d.polygon(rot, fill=fill)


def render_icon(size: int = 256) -> Image.Image:
    S = 1024
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    # zemin: dikey degrade, yuvarlatılmış kare
    grad = Image.new("RGBA", (S, S))
    gd = ImageDraw.Draw(grad)
    top, bot = (255, 205, 60), (255, 150, 30)
    for y in range(S):
        t = y / (S - 1)
        gd.line([(0, y), (S, y)], fill=tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3)) + (255,))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([40, 40, S - 40, S - 40], radius=220, fill=255)
    img.paste(grad, (0, 0), mask)
    # yumuşak gölge
    shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.ellipse([250, 760, 774, 840], fill=(150, 70, 0, 90))
    shadow = shadow.filter(ImageFilter.GaussianBlur(18))
    img.alpha_composite(shadow)
    d = ImageDraw.Draw(img)
    # açık kitap
    cx, by = S / 2, 790
    left = [(cx, by), (cx - 330, by - 70), (cx - 330, by - 300), (cx, by - 230)]
    right = [(cx, by), (cx + 330, by - 70), (cx + 330, by - 300), (cx, by - 230)]
    d.polygon(left, fill=(255, 255, 255, 255))
    d.polygon(right, fill=(250, 246, 238, 255))
    d.line([(cx, by), (cx, by - 230)], fill=(225, 190, 140, 255), width=10)
    for k in range(3):
        y0 = by - 250 + k * 55
        d.line([(cx - 280, y0 - 10 + 25), (cx - 60, y0 + 45)], fill=(240, 205, 150, 255), width=10)
        d.line([(cx + 60, y0 + 45), (cx + 280, y0 - 10 + 25)], fill=(232, 196, 140, 255), width=10)
    # fide: gövde + iki yaprak
    green, green2 = (34, 170, 100, 255), (24, 140, 82, 255)
    stem_top = (cx, 330)
    d.line([(cx, by - 230), (cx, stem_top[1] + 40)], fill=green2, width=34)
    _leaf(d, (cx, 470), 250, 95, 35, green)
    _leaf(d, (cx, 420), 230, 85, 145, (46, 190, 115, 255))
    d.ellipse([cx - 30, 330, cx + 30, 390], fill=(46, 190, 115, 255))
    return img.resize((size, size), Image.LANCZOS)


def write_assets(root: Path) -> None:
    assets = root / "assets"
    assets.mkdir(exist_ok=True)
    big = render_icon(256)
    big.save(assets / "app.png")
    big.save(assets / "app.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    web = root / "web"
    web.mkdir(exist_ok=True)
    big.save(web / "icon.png")
    render_icon(64).save(web / "favicon.png")


if __name__ == "__main__":
    write_assets(Path(__file__).resolve().parent.parent)
