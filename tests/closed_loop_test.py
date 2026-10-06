#!/usr/bin/env python
"""闭环自检：多轮驱动游戏本体，校验状态机不变量与「检测视角」一致性。

Part A（无 UI，纯模型压力闭环）：
  - 多随机种子 × 长虚拟时间，策略机自动钓鱼（抛竿/等待/结算/关弹窗/关订单详情）
  - 每次行动前随机"停留"0~3 个 tick —— 自然触发任意阶段弹窗插入
  - 随机全屏模糊点击（含"设"按钮区、订单区、按钮区）
  - 每步校验不变量：
      * WAITING ⇒ 剩余计时 > 0；CATCH ⇒ 鱼获存在；弹窗 ⇒ return_state 合法
      * 弹窗关闭 ⇒ 原样恢复被打断的阶段（READY 则回准备态）
      * 出售/提交订单的金币增量精确匹配（含订单完成 +50 与全部完成刷新）
      * SAFE_CAST 随机点必为抛竿（永不误触订单）
      * 等待期任何点击零副作用（状态/计时/装备面板/事件流水/金币/渔获数全部不变）
      * 事件流水 CATCH 计数 == 已处理渔获数（±当前手中一条）
  - 结束校验覆盖量（循环数/各阶段弹窗打断数/误触数等达到下限，保证测到了）

Part B（UI，模拟未来插件的闭环）：
  - "截屏 → 识别 → 决策 → 点击"循环 6 轮，弹窗在 READY/WAITING/CATCH 轮流注入
  - 每帧核对检测视角与真实状态一致：
      * 钓鱼三态：求福锚点可检（≥0.85），且识别出的具体状态 == 模型真实状态
      * 非钓鱼界面（HOME/订单详情/弹窗）：连续 2 帧锚点缺失 → 触发"自动暂停"链路
      * 人工关弹窗后重新判定：恢复到的是被打断的阶段（可能是 WAITING/CATCH，非 READY）
  - 结算帧核对：名字条带分色 == 真实稀有度；按钮识别 == 真实动作（出售/提交订单）

运行：  python tests/closed_loop_test.py   （Part B 会短暂弹出游戏窗口）
退出码：0 全部通过；1 存在失败项。
"""
from __future__ import annotations

import random
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageGrab

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "game"))
sys.path.insert(0, str(Path(__file__).resolve().parent))    # 复用 smoke_test 的检测函数（单一事实来源）

from config import LAYOUT, SAFE_CAST, WINDOW_H, WINDOW_W    # noqa: E402
import states as states_mod                                  # noqa: E402
from states import SELL_PRICE, GameModel, State             # noqa: E402
from ui import GameUI                                        # noqa: E402
from smoke_test import (OUT, banner_gold_px, button_kind,   # noqa: E402
                        classify_nameband, load_qiufu_template, qiufu_match)

FISHING = (State.READY, State.WAITING, State.CATCH)
FAILS: list[str] = []
_SEEN: set[str] = set()


def check(name: str, ok: bool, detail: str = "") -> bool:
    """记录失败（同名只记第一次，避免压力循环刷屏）。"""
    if not ok and name not in _SEEN:
        _SEEN.add(name)
        FAILS.append(name)
        print(f"  [FAIL] {name}" + (f"  ({detail})" if detail else ""))
    return ok


def ctr(z: dict) -> tuple[float, float]:
    return (z["x0"] + z["x1"]) / 2, (z["y0"] + z["y1"]) / 2


def rand_in(rng: random.Random, z: dict) -> tuple[float, float]:
    return rng.uniform(z["x0"] + .01, z["x1"] - .01), rng.uniform(z["y0"] + .01, z["y1"] - .01)


# ================================================================ Part A
def part_a(n_seeds: int = 30, virtual_secs: float = 240.0) -> dict:
    stats = dict(cycles=0, sells=0, submits=0, pools=0, fuzz_catch=0,
                 order_detail=0, pop_ready=0, pop_waiting=0, pop_catch=0, fuzz_waiting=0)
    for seed in range(n_seeds):
        m = GameModel(seed=seed, wait_min=0.05, wait_max=0.2, ad_rate=0.25)
        rng = random.Random(1000 + seed)
        m.click(*ctr(LAYOUT["home_btn"]))
        check(f"[A] seed{seed} 进入钓鱼", m.state is State.READY, m.state.name)

        last_gold = m.gold
        injected_this_wait = False
        wait_initial = 0.0
        guard = 0
        while m.clock < virtual_secs and guard < 300_000:
            guard += 1
            st = m.state

            # ---- 每步通用不变量 ----
            if st is State.WAITING:
                check(f"[A] seed{seed} WAITING 剩余计时>0", m.wait_left > 0, f"{m.wait_left:.3f}")
            if st is State.CATCH:
                check(f"[A] seed{seed} CATCH 鱼获存在", m.catch is not None)
            if st is State.RANDOM_POPUP:
                check(f"[A] seed{seed} 弹窗 return_state 合法", m.return_state in FISHING,
                      m.return_state.name)

            # ---- 停留 0~3 tick（自然触发任意阶段弹窗 / 等待推进）----
            for _ in range(rng.randint(0, 3)):
                m.tick(0.05)
            if m.state is not st:
                continue                       # 等待走完或弹窗插入 → 重新观察

            if st is State.HOME:
                m.click(*ctr(LAYOUT["home_btn"]))
                continue

            if st is State.RANDOM_POPUP:
                ret = m.return_state
                stats[f"pop_{ret.name.lower()}"] += 1
                if rng.random() < 0.2:         # 弹窗停留期模糊点击（应全部无效）
                    m.click(rng.uniform(0, 1), rng.uniform(0, 1))
                if m.state is State.RANDOM_POPUP:
                    expect = ret if ret in (State.WAITING, State.CATCH) else State.READY
                    m.click(*ctr(LAYOUT["ad_close_x"]))
                    check(f"[A] seed{seed} 弹窗关闭恢复原状态({ret.name})",
                          m.state is expect, f"got {m.state.name}")
                continue

            if st is State.ORDER_DETAIL:
                stats["order_detail"] += 1
                if rng.random() < 0.2:
                    m.click(rng.uniform(0, 1), rng.uniform(0, 1))
                if m.state is State.ORDER_DETAIL:
                    m.click(*ctr(LAYOUT["close_x"]))
                    check(f"[A] seed{seed} 订单详情关闭回 READY", m.state is State.READY,
                          m.state.name)
                continue

            if st is State.READY:
                r = rng.random()
                if r < 0.10:                   # 模拟"点击越界偏高"误触订单
                    m.click(*rand_in(rng, LAYOUT["order_rows"]))
                    check(f"[A] seed{seed} 误触订单条目开详情",
                          m.state is State.ORDER_DETAIL, m.state.name)
                elif r < 0.16:                 # 全屏模糊点击
                    m.click(rng.uniform(0, 1), rng.uniform(0, 1))
                else:                          # 正常抛竿：SAFE_CAST 随机点
                    act = m.click(*rand_in(rng, SAFE_CAST))
                    check(f"[A] seed{seed} SAFE_CAST 随机点必为抛竿",
                          act == "cast" and m.state is State.WAITING, f"act={act}")
                    injected_this_wait = False
                    wait_initial = m.wait_left
                continue

            if st is State.WAITING:
                # 等待期全屏模糊点击必须零副作用（含"设"按钮、订单面板、任何区域）
                if rng.random() < 0.03:
                    stats["fuzz_waiting"] += 1
                    snap = (m.state, round(m.wait_left, 9), m.equip_visible,
                            len(m.events), m.gold, m.total_catch)
                    for _ in range(12):
                        m.click(rng.uniform(0, 1), rng.uniform(0, 1))
                    now = (m.state, round(m.wait_left, 9), m.equip_visible,
                           len(m.events), m.gold, m.total_catch)
                    check(f"[A] seed{seed} 等待期任意点击零副作用", now == snap,
                          f"{snap[0].name}->{now[0].name}")
                # 中途强制插入（保证 WAITING 打断覆盖；短等待可能直接走完）
                if not injected_this_wait and m.wait_left < wait_initial * 0.5:
                    injected_this_wait = True
                    check(f"[A] seed{seed} WAITING 可被强制打断", m.force_random_popup())
                else:
                    m.tick(0.05)
                continue

            if st is State.CATCH:
                c = m.catch
                if rng.random() < 0.08:        # 结算期模糊点击（可能误点按钮）
                    stats["fuzz_catch"] += 1
                    m.click(rng.uniform(0, 1), rng.uniform(0, 1))
                    if m.state in (State.READY, State.RANDOM_POPUP):
                        stats["cycles"] += 1
                        last_gold = m.gold     # 被误点处理掉，跳过精确金币校验
                    continue
                o = m.orders.match(c.name)
                if rng.random() < 0.15:        # 放入瑶池
                    exp = 0
                    stats["pools"] += 1
                    m.click(*ctr(LAYOUT["btn_right"]))
                elif o is None:                # 出售
                    exp = SELL_PRICE[c.rarity]
                    stats["sells"] += 1
                    m.click(*ctr(LAYOUT["btn_left"]))
                else:                          # 提交订单（奖励精确可预期）
                    stats["submits"] += 1
                    will_done = o.got + 1 >= o.need
                    exp = o.reward if will_done else 0
                    if will_done and all(x.done for x in m.orders.orders if x is not o):
                        exp += 50
                    m.click(*ctr(LAYOUT["btn_left"]))
                check(f"[A] seed{seed} 金币增量精确", m.gold - last_gold == exp,
                      f"want={exp} got={m.gold - last_gold}")
                last_gold = m.gold
                stats["cycles"] += 1
                check(f"[A] seed{seed} 处理后鱼获清空",
                      m.catch is None and m.state in (State.READY, State.RANDOM_POPUP),
                      m.state.name)
                continue

        n_catch = sum(1 for _, e in m.events if e.startswith("CATCH "))
        check(f"[A] seed{seed} 事件流水一致",
              n_catch == m.total_catch + (1 if m.catch else 0),
              f"events={n_catch} total={m.total_catch}")
    return stats


def part_a_coverage(stats: dict) -> None:
    """覆盖量下限：保证压力循环真的测到了各条链路（种子固定 → 结果确定）。"""
    print(f"  覆盖统计：{stats}")
    check("[A] 覆盖：完成循环数", stats["cycles"] >= 200, str(stats["cycles"]))
    check("[A] 覆盖：打断 READY 的弹窗", stats["pop_ready"] >= 20, str(stats["pop_ready"]))
    check("[A] 覆盖：打断 WAITING 的弹窗", stats["pop_waiting"] >= 5, str(stats["pop_waiting"]))
    check("[A] 覆盖：打断 CATCH 的弹窗", stats["pop_catch"] >= 20, str(stats["pop_catch"]))
    check("[A] 覆盖：误触订单详情", stats["order_detail"] >= 10, str(stats["order_detail"]))
    check("[A] 覆盖：等待期模糊点击", stats["fuzz_waiting"] >= 10, str(stats["fuzz_waiting"]))
    check("[A] 覆盖：出售次数", stats["sells"] >= 50, str(stats["sells"]))
    check("[A] 覆盖：提交订单次数", stats["submits"] >= 20, str(stats["submits"]))
    check("[A] 覆盖：放入瑶池次数", stats["pools"] >= 5, str(stats["pools"]))


def part_a_dispose_popup() -> None:
    """确定性子项：卖鱼后弹窗链路 + 非钓鱼态下 force_random_popup 必须失败。"""
    states_mod.RANDOM_AD_CHANCE = 1.0          # 每次卖出必弹
    m = GameModel(seed=99, wait_min=0.01, wait_max=0.01, ad_rate=0.0)
    m.click(*ctr(LAYOUT["home_btn"]))
    m.click(*ctr(LAYOUT["cast_zone"]))
    while m.state is State.WAITING:
        m.tick(0.05)
    m.click(*ctr(LAYOUT["btn_left"]))
    check("[A] 卖鱼后必弹活动公告", m.state is State.RANDOM_POPUP, m.state.name)
    m.click(*ctr(LAYOUT["ad_close_x"]))
    check("[A] 卖鱼后弹窗关闭回 READY", m.state is State.READY, m.state.name)
    m.state = State.HOME
    check("[A] HOME 下强制弹窗失败", m.force_random_popup() is False)
    m.click(*ctr(LAYOUT["home_btn"]))
    m.click(*ctr(LAYOUT["order_rows"]))
    check("[A] ORDER_DETAIL 下强制弹窗失败",
          m.state is State.ORDER_DETAIL and m.force_random_popup() is False)
    states_mod.RANDOM_AD_CHANCE = 0.12         # 还原


# ================================================================ Part B
def cast_hint_bright(img: np.ndarray) -> int:
    """抛竿提示字区（x32%~68%, y84.5%~89.5%）的白色亮像素（READY 判别）。
    三套背景实测：READY≈951，WAITING≈167（鱼漂重叠），阈值 500。"""
    h, w = img.shape[:2]
    z = img[int(.845 * h):int(.895 * h), int(.32 * w):int(.68 * w)].astype(int)
    return int(((z.min(2) > 200) & (z.max(2) - z.min(2) < 60)).sum())


def part_b(rounds: int = 6) -> None:
    tpl = load_qiufu_template()
    m = GameModel(seed=11, wait_min=0.06, wait_max=0.14, ad_rate=0.0,
                  force_rarities=["白", "绿", "蓝", "紫", "黄", "白"])
    ui = GameUI(m)
    ui.paused = True                  # 全部由"插件"显式驱动
    ui.root.attributes("-topmost", True)
    ui.root.lift()
    states_mod.RANDOM_AD_CHANCE = 0.0 # 卖鱼后不自然弹（弹窗由脚本按阶段注入，保证确定性）
    rng = random.Random(42)

    def shot() -> np.ndarray:
        ui.render(force=True)
        ui.root.update_idletasks()
        ui.root.update()
        time.sleep(0.05)
        x, y = ui.root.winfo_rootx(), ui.root.winfo_rooty()
        return np.array(ImageGrab.grab(bbox=(x, y, x + WINDOW_W, y + WINDOW_H)).convert("RGB"))

    def detect(img: np.ndarray) -> tuple[str | None, float]:
        """插件视角的状态识别：先锚点（锚点必被弹窗遮挡 → 天然覆盖任意阶段弹窗），
        再用结算横幅 / 抛竿提示字细分三态。"""
        q = qiufu_match(img, tpl)
        if q >= 0.85:
            if banner_gold_px(img) > 4000:
                return "CATCH", q
            if cast_hint_bright(img) > 500:
                return "READY", q
            return "WAITING", q
        return None, q                     # 非钓鱼界面（需连续 2 帧确认）

    miss = 0
    injected_rounds = 0
    for r in range(rounds):
        stage = ["READY", "WAITING", "CATCH"][r % 3]
        injected = False
        done_catch = m.total_catch
        print(f"  [B] 轮次 {r + 1}/{rounds}：注入阶段={stage}，目标稀有度={m.force_rarities[r]}")
        for it in range(120):
            img = shot()
            det, q = detect(img)
            if det is None:
                miss += 1
                if miss >= 2:
                    # 插件视角：连续缺失 → 非钓鱼界面 → 自动暂停，等人工处理
                    check(f"[B{r}] 连续2帧缺失判非钓鱼界面（真实={m.state.name}）",
                          m.state in (State.HOME, State.ORDER_DETAIL, State.RANDOM_POPUP),
                          f"q={q:.2f}")
                    if m.state is State.RANDOM_POPUP:
                        ret = m.return_state.name
                        ui.click_pct(*ctr(LAYOUT["ad_close_x"]))
                        check(f"[B{r}] 人工关弹窗后恢复为{ret}", m.state.name == ret,
                              m.state.name)
                    elif m.state is State.ORDER_DETAIL:
                        ui.click_pct(*ctr(LAYOUT["close_x"]))
                        check(f"[B{r}] 人工关订单详情回 READY", m.state is State.READY,
                              m.state.name)
                    elif m.state is State.HOME:
                        ui.click_pct(*ctr(LAYOUT["home_btn"]))
                        check(f"[B{r}] 人工进入钓鱼", m.state is State.READY, m.state.name)
                continue                   # 重新判定（不得带着旧状态行动）

            miss = 0
            check(f"[B{r}] 检测状态与真实一致（{det}）", det == m.state.name,
                  f"真实={m.state.name} q={q:.2f}")

            if det == "READY":
                if stage == "READY" and not injected:
                    injected, injected_rounds = True, injected_rounds + 1
                    check(f"[B{r}] READY 阶段注入弹窗", m.force_random_popup())
                    continue
                ui.click_pct(*rand_in(rng, SAFE_CAST))
                check(f"[B{r}] SAFE_CAST 点击后进入等待", m.state is State.WAITING,
                      m.state.name)

            elif det == "WAITING":
                m.tick(0.05)               # 等待期插件不操作，仅推进观察
                if stage == "WAITING" and not injected and m.state is State.WAITING:
                    injected, injected_rounds = True, injected_rounds + 1
                    check(f"[B{r}] WAITING 阶段注入弹窗", m.force_random_popup())

            elif det == "CATCH":
                if stage == "CATCH" and not injected:
                    injected, injected_rounds = True, injected_rounds + 1
                    check(f"[B{r}] CATCH 阶段注入弹窗", m.force_random_popup())
                    continue
                got, npx = classify_nameband(img)
                check(f"[B{r}] 分色与稀有度一致", got == m.catch.rarity,
                      f"{got} vs {m.catch.rarity} px={npx}")
                want = "提交订单" if m.orders.match(m.catch.name) else "出售"
                kind = button_kind(img)
                check(f"[B{r}] 按钮识别正确", kind == want, f"{kind} vs {want}")
                if got in ("紫", "黄"):     # 插件策略：暂停+通知 → 人工选"放入瑶池"
                    ui.click_pct(*ctr(LAYOUT["btn_right"]))
                else:
                    ui.click_pct(*ctr(LAYOUT["btn_left"]))
                check(f"[B{r}] 处理鱼获后回 READY", m.state is State.READY, m.state.name)

            if m.total_catch > done_catch and m.state is State.READY:
                Image.fromarray(img).save(OUT / f"b_round{r + 1}_done.png")
                break
        else:
            check(f"[B{r}] 轮次在限步内完成", False, f"iterations={it + 1}")

    check("[B] 每轮都完成了弹窗注入", injected_rounds == rounds, str(injected_rounds))
    ui.root.destroy()


# ================================================================
def main() -> int:
    if sys.platform == "win32":
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

    print(f"[Part A] 模型层压力闭环（多种子×{240.0}s 虚拟时间）")
    stats = part_a()
    part_a_coverage(stats)
    part_a_dispose_popup()

    print("[Part B] 检测层闭环（模拟插件：截屏→识别→决策→点击）")
    part_b()

    print()
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        return 1
    print("结果：闭环自检全部通过 ✔")
    return 0


if __name__ == "__main__":
    sys.exit(main())
