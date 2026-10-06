"""六态状态机（纯模型，不含 UI）。

状态流转见 README 状态机图。所有点击经 click(x, y) 路由（x/y 为窗口比例坐标），
返回事件名（用于日志与测试断言）。
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum

from config import (LAYOUT, RANDOM_AD_CHANCE, THEMES, in_zone)
from fish_data import RARITIES, roll_fish, roll_rarity
from orders import OrderSystem

# 出售单价（按稀有度）
SELL_PRICE = {"白": 10, "绿": 20, "蓝": 40, "紫": 100, "黄": 250}


class State(Enum):
    HOME = "HOME"                    # 开始页（非钓鱼界面）
    READY = "READY"                  # 准备钓鱼
    WAITING = "WAITING"              # 钓鱼等待（任何点击无效）
    CATCH = "CATCH"                  # 鱼获结算
    ORDER_DETAIL = "ORDER_DETAIL"    # 订单详情（误触订单条目；非钓鱼界面）
    RANDOM_POPUP = "RANDOM_POPUP"    # 活动公告（随机干扰；非钓鱼界面）


@dataclass
class Catch:
    name: str
    rarity: str
    length: float   # 米
    weight: float   # 公斤


class GameModel:
    def __init__(self, seed: int | None = None, wait_min: float = 6.0,
                 wait_max: float = 15.0, force_rarities: list[str] | None = None,
                 force_order: bool = False) -> None:
        self.rng = random.Random(seed)
        self.wait_min, self.wait_max = wait_min, wait_max
        self.force_rarities = force_rarities or []
        self._force_i = 0
        self.force_order = force_order

        self.state = State.HOME
        self.theme = self.rng.choice(THEMES)
        self.gold = 0
        self.total_catch = 0
        self.equip_visible = True
        self.catch: Catch | None = None
        self.wait_left = 0.0
        self.orders = OrderSystem(self.rng)
        self.order_detail_idx: int | None = None
        self.return_state = State.READY
        self.events: list[tuple[float, str]] = []   # (虚拟时钟, 事件)
        self.clock = 0.0

    # ---------------------------------------------------------------- 日志
    def _log(self, event: str) -> None:
        self.events.append((self.clock, event))

    # ---------------------------------------------------------------- 流程
    def _enter_ready(self) -> None:
        self.theme = self.rng.choice(THEMES)   # 每次回到准备态随机换背景
        self.state = State.READY
        self._log(f"READY theme={self.theme}")

    def _cast(self) -> None:
        self.state = State.WAITING
        self.wait_left = self.rng.uniform(self.wait_min, self.wait_max)
        self._log(f"WAITING {self.wait_left:.1f}s")

    def _roll_catch(self) -> None:
        if self._force_i < len(self.force_rarities):
            rarity = self.force_rarities[self._force_i]
            self._force_i += 1
        else:
            rarity = roll_rarity(self.rng)
        fish = None
        if self.force_order:
            fish = self.orders.open_order_fish()
            if fish is not None:
                rarity = fish_rarity_of(fish)
        if fish is None:
            fish = roll_fish(self.rng, rarity)
        span = {"白": (0.1, 0.5), "绿": (0.3, 1.0), "蓝": (0.5, 1.6),
                "紫": (0.8, 2.2), "黄": (1.2, 3.0)}[rarity]
        length = round(self.rng.uniform(*span), 2)
        weight = round(length * self.rng.uniform(0.4, 1.6), 2)
        self.catch = Catch(fish, rarity, length, weight)
        self.state = State.CATCH
        action = "提交订单" if self.orders.match(fish) else "出售"
        self._log(f"CATCH {fish}({rarity}) {length}m 按钮={action}")

    def _dispose(self, action: str) -> None:
        assert self.catch is not None
        if action == "sell":
            self.gold += SELL_PRICE[self.catch.rarity]
        elif action == "submit":
            _, gold = self.orders.submit(self.catch.name)
            self.gold += gold
        # pool（放入瑶池）不加金币
        self.total_catch += 1
        self.catch = None
        if self.rng.random() < RANDOM_AD_CHANCE:
            self.state = State.RANDOM_POPUP
            self._log("RANDOM_POPUP")
        else:
            self._enter_ready()

    # ---------------------------------------------------------------- 点击路由
    def click(self, x: float, y: float) -> str:
        st = self.state
        if st is State.HOME:
            if in_zone(LAYOUT["home_btn"], x, y):
                self._enter_ready()
                return "enter"
            return "ignore"

        if st is State.ORDER_DETAIL:
            if in_zone(LAYOUT["close_x"], x, y):
                self.state = self.return_state
                self._log(f"CLOSE order_detail -> {self.state.name}")
                return "close_detail"
            return "ignore"

        if st is State.RANDOM_POPUP:
            if in_zone(LAYOUT["ad_close_x"], x, y):
                self._enter_ready()
                self._log("CLOSE random_popup")
                return "close_ad"
            return "ignore"

        # 设置按钮（钓鱼三态均可用）
        if in_zone(LAYOUT["settings"], x, y):
            self.equip_visible = not self.equip_visible
            self._log(f"equip_visible={self.equip_visible}")
            return "toggle_equip"

        if st is State.READY:
            # 订单面板在最上层：先判订单（含与抛竿区的重叠带 → 误触）
            if in_zone(LAYOUT["order_panel"], x, y):
                idx = self._order_row(y)
                self.order_detail_idx = idx
                self.return_state = State.READY
                self.state = State.ORDER_DETAIL
                self._log(f"ORDER_DETAIL idx={idx} (误触: {x:.2f},{y:.2f})")
                return "open_detail"
            if in_zone(LAYOUT["cast_zone"], x, y):
                self._cast()
                return "cast"
            return "ignore"

        if st is State.WAITING:
            return "ignore"       # 等待期任何点击无效（含订单面板）

        if st is State.CATCH:
            if in_zone(LAYOUT["btn_left"], x, y):
                action = "submit" if self.orders.match(self.catch.name) else "sell"
                self._dispose(action)
                return action
            if in_zone(LAYOUT["btn_right"], x, y):
                self._dispose("pool")
                return "pool"
            return "ignore"
        return "ignore"

    def _order_row(self, y: float) -> int:
        z = LAYOUT["order_panel"]
        rows = len(self.orders.orders)
        i = int((y - z["y0"]) / (z["y1"] - z["y0"]) * rows)
        return max(0, min(rows - 1, i))

    # ---------------------------------------------------------------- 时钟
    def tick(self, dt: float) -> None:
        self.clock += dt
        if self.state is State.WAITING:
            self.wait_left -= dt
            if self.wait_left <= 0:
                self._roll_catch()

    # 结算左下按钮当前应显示的文案
    def catch_action_label(self) -> str:
        if self.catch and self.orders.match(self.catch.name):
            return "提交订单"
        return "出售"


def fish_rarity_of(name: str) -> str:
    from fish_data import fish_rarity
    return fish_rarity(name)
