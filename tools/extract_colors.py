#!/usr/bin/env python
"""从截图中提取"鱼获名字稀有度颜色"的候选色值。

用法:
    python tools/extract_colors.py <截图路径> [<截图路径2> ...]

原理:
    稀有度名字是"彩色文字 + 深色描边"。按五种稀有度各自的色相/饱和度/明度
    特征做像素掩码, 再把命中像素按量化 RGB 聚类, 输出每个色带内最大的几个
    色簇(均值RGB、像素数、包围盒), 人工从中挑出"文字簇"(小而横长、位于列表区),
    排除大面积 UI 装饰(金色横幅、按钮底色等)。

仅依赖 numpy 与 Pillow。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image

# 五种稀有度的像素掩码定义(与 docs/colors.md 对应)
BANDS: dict[str, str] = {
    "白": "低饱和高亮度 (mx-mn<35 且 mn>200)",
    "绿": "g>r+40 且 g>b+40 且 g>120",
    "蓝": "b>r+30 且 b>g+30 且 b>130",
    "紫": "r>b+20 且 b>g+40 且 r>g+60",
    "黄": "r>200 且 g>170 且 b<120 (亮黄, 排除暗金装饰)",
}


def band_masks(arr: np.ndarray) -> dict[str, np.ndarray]:
    r, g, b = arr[..., 0].astype(int), arr[..., 1].astype(int), arr[..., 2].astype(int)
    mx = arr.max(axis=2).astype(int)
    mn = arr.min(axis=2).astype(int)
    return {
        "白": ((mx - mn) < 35) & (mn > 200),
        "绿": (g > r + 40) & (g > b + 40) & (g > 120),
        "蓝": (b > r + 30) & (b > g + 30) & (b > 130),
        "紫": (r > b + 20) & (b > g + 40) & (r > g + 60),
        "黄": (r > 200) & (g > 170) & (b < 120),
    }


def clusters(px: np.ndarray, quant: int = 32, top: int = 4) -> list[tuple[tuple[int, int, int], int]]:
    """把命中像素按量化 RGB 聚类, 返回 (均值RGB, 像素数) 最大的前 top 个。"""
    if len(px) == 0:
        return []
    q = (px // quant) * quant
    keys, counts = np.unique(q.reshape(-1, 3), axis=0, return_counts=True)
    order = np.argsort(counts)[::-1][:top]
    out = []
    for i in order:
        m = (q == keys[i]).all(axis=1)
        out.append((tuple(int(v) for v in px[m].mean(axis=0)), int(counts[i])))
    return out


def analyze(path: str) -> None:
    img = Image.open(path).convert("RGB")
    arr = np.array(img)
    h, w = arr.shape[:2]
    print(f"\n===== {path}  ({w}x{h}) =====")
    for name, mask in band_masks(arr).items():
        ys, xs = np.nonzero(mask)
        total = len(xs)
        print(f"\n[{name}] {BANDS[name]} -> {total} px")
        if total == 0:
            continue
        px = arr[mask]
        # 掩码整体包围盒(粗略, 可能被装饰拉大)
        print(f"   整体包围盒 x {xs.min()}-{xs.max()} ({xs.min()/w:.0%}-{xs.max()/w:.0%}W), "
              f"y {ys.min()}-{ys.max()} ({ys.min()/h:.0%}-{ys.max()/h:.0%}H)")
        for rgb, n in clusters(px):
            print(f"   簇 RGB{rgb}  {n} px ({100*n/total:.1f}%)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("images", nargs="+", help="截图路径")
    args = ap.parse_args()
    for p in args.images:
        if not Path(p).exists():
            print(f"跳过(不存在): {p}", file=sys.stderr)
            continue
        analyze(p)


if __name__ == "__main__":
    main()
