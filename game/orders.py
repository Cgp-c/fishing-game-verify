"""每日订单系统：生成/进度/完成/刷新。"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from config import ORDER_COUNT, ORDER_QTY
from fish_data import ORDERABLE, RARITIES, fish_rarity


@dataclass
class Order:
    fish: str
    need: int
    got: int = 0
    reward: int = 0
    done: bool = field(default=False)

    @property
    def rarity(self) -> str:
        return fish_rarity(self.fish)


class OrderSystem:
    """2~3 条订单；全部完成后立即刷新一批（并给一次性奖励）。"""

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.orders: list[Order] = []
        self.refresh_bonus = 0
        self.refresh()

    def refresh(self) -> None:
        n = self.rng.randint(*ORDER_COUNT)
        picked = self.rng.sample(ORDERABLE, k=min(n, len(ORDERABLE)))
        self.orders = []
        for fish in picked:
            need = self.rng.randint(*ORDER_QTY)
            # 奖励与数量和稀有度挂钩
            self.orders.append(Order(fish=fish, need=need,
                                     reward=30 * need + 10 * len(fish_rarity(fish))))

    def match(self, fish: str) -> Order | None:
        """返回该鱼可提交的未完成订单。"""
        for o in self.orders:
            if o.fish == fish and not o.done:
                return o
        return None

    def submit(self, fish: str) -> tuple[Order | None, int]:
        """提交一条鱼获：返回 (订单, 本事件获得的金币)。完成订单/全部完成时给奖励。"""
        order = self.match(fish)
        gold = 0
        if order is None:
            return None, 0
        order.got += 1
        if order.got >= order.need:
            order.done = True
            gold += order.reward
        if all(o.done for o in self.orders):
            gold += 50                       # 全部完成奖励
            self.refresh_bonus += 1
            self.rng.random()                # 保持随机序列消耗一致
            self.refresh()
        return order, gold

    def any_open(self) -> bool:
        return any(not o.done for o in self.orders)

    def open_order_fish(self) -> str | None:
        """任取一条未完成订单的鱼（--force-order / demo 使用）。"""
        for o in self.orders:
            if not o.done:
                return o.fish
        return None
