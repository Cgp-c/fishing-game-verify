"""鱼种与稀有度数据（唯一配置点）。

颜色规格见 docs/colors.md；色值来源为真实游戏截图的像素聚类分析。
"""
from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class Rarity:
    key: str           # 白/绿/蓝/紫/黄
    rgb: tuple[int, int, int]   # 名字文字颜色
    stroke: tuple[int, int, int]  # 描边色
    weight: int        # 随机出现权重
    plugin_pause: bool  # 将来检测程序遇到是否应暂停
    label: str         # 订单/图鉴中显示的稀有度文字


RARITIES: dict[str, Rarity] = {
    "白": Rarity("白", (245, 245, 245), (64, 64, 64), 40, False, "普通"),
    "绿": Rarity("绿", (108, 203, 80), (30, 77, 20), 25, False, "优秀"),
    "蓝": Rarity("蓝", (85, 160, 220), (16, 48, 92), 20, False, "稀有"),
    "紫": Rarity("紫", (170, 100, 220), (58, 21, 96), 10, True, "史诗"),
    "黄": Rarity("黄", (235, 200, 60), (107, 82, 8), 5, True, "传说"),
}

# 鱼种清单（名字源自真实游戏目录截图；稀有度以名字颜色为准）
FISH: dict[str, list[str]] = {
    "白": ["海星", "沙丁鱼"],
    "绿": ["海马", "石斑鱼"],
    "蓝": ["胭脂鱼", "文鳐鱼", "香鱼", "狮子鱼", "矛尾鱼", "五彩鳗", "小丑鱼"],
    "紫": ["神仙鱼", "鬼头刀", "月光水母"],
    "黄": ["霓虹鱼", "鳟鱼", "骨舌鱼"],
}

# 订单只指向常见鱼，保证「出售」与「提交订单」两种按钮都会自然出现
ORDERABLE = ["海星", "沙丁鱼", "海马", "石斑鱼", "香鱼", "小丑鱼"]


def roll_rarity(rng: random.Random, forced: str | None = None) -> str:
    if forced:
        return forced
    keys = list(RARITIES)
    weights = [RARITIES[k].weight for k in keys]
    return rng.choices(keys, weights=weights, k=1)[0]


def roll_fish(rng: random.Random, rarity: str) -> str:
    return rng.choice(FISH[rarity])


def fish_rarity(name: str) -> str:
    for rarity, names in FISH.items():
        if name in names:
            return rarity
    raise KeyError(name)
