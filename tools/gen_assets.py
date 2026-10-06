#!/usr/bin/env python
"""程序化生成游戏全部 PNG 素材（可复现，不使用任何外部图片）。

用法:  python tools/gen_assets.py
输出:  game/assets/*.png
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ASSETS = Path(__file__).resolve().parent.parent / "game" / "assets"
W, H = 540, 1170  # 游戏窗口尺寸

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
]


def font(size: int) -> ImageFont.FreeTypeFont:
    for p in FONT_CANDIDATES:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    raise FileNotFoundError("未找到中文字体(微软雅黑/黑体/宋体)")


def vgrad(w: int, h: int, top: tuple, bottom: tuple) -> Image.Image:
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(h - 1, 1)
        c = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        d.line([(0, y), (w, y)], fill=c)
    return img


def lerp(a: tuple, b: tuple, t: float) -> tuple:
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


# ---------------------------------------------------------------- 背景
WATER_TOP = int(H * 0.64)  # 水面起始 y（与抛竿区上缘一致）


def make_background(theme: str) -> Image.Image:
    themes = {
        # 天空上/下, 远山, 近丘, 岸树, 水面上/下
        "taolin": dict(sky=(168, 205, 235), sky2=(232, 215, 224),
                       far=(196, 176, 208), hill=(120, 168, 120),
                       tree=(235, 170, 190), tree2=(208, 130, 158),
                       water=(96, 168, 170), water2=(40, 96, 110)),
        "qingshan": dict(sky=(190, 220, 240), sky2=(224, 236, 240),
                         far=(140, 180, 200), hill=(88, 150, 118),
                         tree=(96, 158, 108), tree2=(70, 128, 88),
                         water=(80, 150, 190), water2=(30, 80, 118)),
        "luwei": dict(sky=(242, 196, 148), sky2=(246, 224, 186),
                      far=(172, 150, 158), hill=(120, 118, 108),
                      tree=(150, 118, 92), tree2=(108, 86, 70),
                      water=(96, 130, 128), water2=(38, 70, 74)),
    }[theme]
    rng_seed = sum(ord(c) for c in theme)
    img = vgrad(W, H, themes["sky"], themes["sky2"])
    d = ImageDraw.Draw(img)

    # 远山两层
    for i, (col, base) in enumerate([(themes["far"], 0.30), (lerp(themes["far"], themes["hill"], 0.5), 0.36)]):
        pts = [(0, H)]
        for k in range(0, W + 1, 60):
            y = H * base - math.sin((k / W * math.pi * (2 + i)) + i) * H * 0.06
            pts.append((k, y))
        pts += [(W, H)]
        d.polygon(pts, fill=col)

    # 近丘
    pts = [(0, H)]
    for k in range(0, W + 1, 45):
        y = H * 0.52 - math.sin(k / W * math.pi * 3 + rng_seed) * H * 0.03
        pts.append((k, y))
    pts += [(W, H)]
    d.polygon(pts, fill=themes["hill"])

    # 岸树（圆簇）
    rnd = rng_seed
    for k in range(9):
        rnd = (rnd * 1103515245 + 12345) & 0x7FFFFFFF
        x = 20 + (rnd % 500)
        y = int(H * 0.44 + (rnd >> 8) % int(H * 0.10))
        r = 16 + (rnd >> 12) % 22
        col = themes["tree"] if k % 2 == 0 else themes["tree2"]
        d.ellipse([x - r, y - r, x + r, y + r], fill=col)
        d.rectangle([x - 2, y, x + 2, y + r], fill=themes["tree2"])

    # 水面（上缘微波线）
    water = vgrad(W, H - WATER_TOP, themes["water"], themes["water2"])
    img.paste(water, (0, WATER_TOP))
    dw = ImageDraw.Draw(img)
    for k in range(14):
        rnd = (rnd * 1103515245 + 12345) & 0x7FFFFFFF
        x = (rnd % W) // 20 * 20
        y = WATER_TOP + 8 + (rnd >> 6) % (H - WATER_TOP - 30)
        ln = 14 + (rnd >> 10) % 26
        dw.line([(x, y), (x + ln, y)], fill=lerp(themes["water"], (255, 255, 255), 0.35), width=2)

    # 芦苇主题加前景剪影
    if theme == "luwei":
        for k in range(16):
            rnd = (rnd * 1103515245 + 12345) & 0x7FFFFFFF
            x = (rnd % W)
            h = 60 + (rnd >> 7) % 90
            dw.line([(x, H), (x + 12 - (rnd >> 3) % 24, H - h)], fill=(70, 56, 48), width=3)
            dw.ellipse([x - 4, H - h - 14, x + 6, H - h + 2], fill=(84, 66, 54))
    return img


# ---------------------------------------------------------------- 图标
def icon_rounded(size: int, grad_top: tuple, grad_bottom: tuple, ch: str,
                 border: tuple) -> Image.Image:
    img = vgrad(size, size, grad_top, grad_bottom).convert("RGBA")
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=size // 5,
                        outline=border, width=3)
    f = font(int(size * 0.62))
    bbox = d.textbbox((0, 0), ch, font=f)
    d.text(((size - bbox[2] - bbox[0]) / 2, (size - bbox[3] - bbox[1]) / 2 - 1),
           ch, font=f, fill=(255, 255, 255, 255),
           stroke_width=1, stroke_fill=(0, 0, 0, 90))
    return img


def make_side_icons() -> None:
    # 左侧竖排功能图标：求福（主锚点）、垂钓助手、奇异生物
    icon_rounded(56, (232, 84, 84), (188, 46, 46), "福", (250, 214, 120)).save(ASSETS / "qiufu.png")
    icon_rounded(56, (94, 152, 214), (52, 100, 168), "钓", (222, 238, 250)).save(ASSETS / "icon_assist.png")
    icon_rounded(56, (150, 112, 196), (100, 66, 148), "异", (232, 224, 250)).save(ASSETS / "icon_strange.png")


def make_equip_icons() -> None:
    # 顶部装备栏：鱼饵/鱼竿/鱼线/鱼钩
    for name, grad, ch in [
        ("eq_bait", ((150, 108, 66), (104, 70, 38)), "饵"),
        ("eq_rod", ((172, 140, 92), (120, 94, 58)), "竿"),
        ("eq_line", ((120, 148, 176), (78, 102, 130)), "线"),
        ("eq_hook", ((130, 140, 152), (86, 96, 110)), "钩"),
    ]:
        icon_rounded(40, grad[0], grad[1], ch, (240, 232, 200)).save(ASSETS / f"{name}.png")


# ---------------------------------------------------------------- 鱼漂 / 鱼 / 横幅
def make_bobber() -> None:
    img = Image.new("RGBA", (44, 40), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # 白莲花漂：一圈花瓣 + 中心红点
    for ang in range(0, 360, 60):
        a = math.radians(ang)
        cx, cy = 22 + 12 * math.cos(a), 20 + 10 * math.sin(a)
        d.ellipse([cx - 7, cy - 5, cx + 7, cy + 5], fill=(250, 248, 240, 255),
                  outline=(210, 200, 190, 255), width=1)
    d.ellipse([16, 14, 28, 26], fill=(226, 88, 80, 255), outline=(160, 50, 46, 255))
    img.save(ASSETS / "bobber.png")


def make_fish(name: str, tint: tuple[int, int, int]) -> None:
    """简单鱼剪影：椭圆身 + 三角尾 + 背鳍 + 眼睛，稀有度色着色。"""
    img = Image.new("RGBA", (190, 110), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    dark = tuple(max(0, c - 70) for c in tint)
    lite = tuple(min(255, c + 60) for c in tint)
    d.polygon([(150, 55), (186, 26), (186, 84)], fill=lite, outline=dark)      # 尾
    d.ellipse([16, 22, 158, 88], fill=tint, outline=dark)                       # 身
    d.polygon([(70, 26), (98, 6), (112, 26)], fill=lite, outline=dark)          # 背鳍
    d.polygon([(78, 84), (96, 102), (110, 84)], fill=lite, outline=dark)        # 腹鳍
    d.ellipse([132, 40, 144, 52], fill=(255, 255, 255, 255), outline=dark)      # 眼
    d.ellipse([137, 45, 141, 49], fill=(20, 20, 20, 255))
    for i in range(3):                                                          # 鳞纹
        d.arc([40 + i * 26, 34, 92 + i * 26, 76], 200, 340, fill=dark, width=2)
    img.save(ASSETS / f"fish_{name}.png")


def make_banner() -> None:
    """金色横幅底图（'恭喜获得'文字运行时叠加）。"""
    img = vgrad(400, 74, (238, 196, 92), (206, 150, 52)).convert("RGBA")
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, 399, 73], radius=18, outline=(120, 84, 28), width=3)
    d.rounded_rectangle([6, 6, 393, 67], radius=14, outline=(255, 236, 170), width=2)
    # 两端飘带
    d.polygon([(-18, 20), (0, 30), (0, 52), (-18, 62)], fill=(188, 132, 44))
    d.polygon([(418, 20), (400, 30), (400, 52), (418, 62)], fill=(188, 132, 44))
    img.save(ASSETS / "banner_gold.png")


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    make_background("taolin").save(ASSETS / "bg_taolin.png")
    make_background("qingshan").save(ASSETS / "bg_qingshan.png")
    make_background("luwei").save(ASSETS / "bg_luwei.png")
    make_side_icons()
    make_equip_icons()
    make_bobber()
    make_banner()
    import sys
    sys.path.insert(0, str(ASSETS.parent))
    from fish_data import FISH, RARITIES
    for rarity, names in FISH.items():
        for n in names:
            make_fish(n, RARITIES[rarity].rgb)
    print(f"素材已生成 -> {ASSETS}")
    for p in sorted(ASSETS.glob('*.png')):
        print("  ", p.name)


if __name__ == "__main__":
    main()
