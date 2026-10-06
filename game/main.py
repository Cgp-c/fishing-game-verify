"""游戏入口。

    python game/main.py [--demo] [--force-rarity=白,绿,蓝,紫,黄] [--force-order]
                        [--wait-min=6] [--wait-max=15] [--seed=123]

--demo：自动演示（自动抛竿/处理鱼获/关弹窗，偶尔"手滑"点进订单区触发误触场景）。
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import LAYOUT, SAFE_CAST, WINDOW_TITLE  # noqa: E402
from states import GameModel, State                  # noqa: E402
from ui import GameUI                                # noqa: E402


def center(z: dict) -> tuple[float, float]:
    return (z["x0"] + z["x1"]) / 2, (z["y0"] + z["y1"]) / 2


def rand_in(rng: random.Random, z: dict) -> tuple[float, float]:
    return rng.uniform(z["x0"] + .01, z["x1"] - .01), rng.uniform(z["y0"] + .01, z["y1"] - .01)


class Demo:
    """状态驱动的自动演示。"""

    def __init__(self, ui: GameUI, seed: int | None = None) -> None:
        self.ui = ui
        self.rng = random.Random(seed)

    def step(self) -> None:
        m = self.ui.model
        st = m.state
        delay = 400
        if st is State.HOME:
            act = self.ui.click_pct(*center(LAYOUT["home_btn"]))
        elif st is State.READY:
            # 80% 安全区抛竿，20% 全区随机（可能误触订单面板 → 订单详情）
            z = SAFE_CAST if self.rng.random() < 0.8 else LAYOUT["cast_zone"]
            act = self.ui.click_pct(*rand_in(self.rng, z))
            delay = self.rng.randint(700, 1600)
        elif st is State.CATCH:
            act = self.ui.click_pct(*center(LAYOUT["btn_left"]))
            delay = self.rng.randint(500, 1200)
        elif st is State.ORDER_DETAIL:
            act = self.ui.click_pct(*center(LAYOUT["close_x"]))
            delay = self.rng.randint(1000, 2000)
        elif st is State.RANDOM_POPUP:
            act = self.ui.click_pct(*center(LAYOUT["ad_close_x"]))
            delay = self.rng.randint(1000, 2000)
        else:  # WAITING
            act = "wait"
        if act != "wait":
            print(f"[demo {m.clock:7.1f}s] {st.name:12s} -> {act}", flush=True)
        self.ui.root.after(delay, self.step)


def main() -> None:
    ap = argparse.ArgumentParser(description="简单钓鱼游戏验证（自动化测试用）")
    ap.add_argument("--demo", action="store_true", help="自动演示模式")
    ap.add_argument("--force-rarity", default="", help="强制出鱼序列，如 白,绿,蓝,紫,黄（循环消耗）")
    ap.add_argument("--force-order", action="store_true", help="强制每次鱼获匹配订单")
    ap.add_argument("--wait-min", type=float, default=6.0)
    ap.add_argument("--wait-max", type=float, default=15.0)
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()

    # Windows 高分屏下保证窗口逻辑像素 == 物理像素（截图检测的前提）
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

    model = GameModel(seed=args.seed, wait_min=args.wait_min, wait_max=args.wait_max,
                      force_rarities=[s for s in args.force_rarity.split(",") if s],
                      force_order=args.force_order)
    ui = GameUI(model)
    ui.root.title(WINDOW_TITLE)
    if args.demo:
        ui.root.after(600, Demo(ui, seed=args.seed).step)
    ui.root.mainloop()


if __name__ == "__main__":
    main()
