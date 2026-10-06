#!/usr/bin/env python
"""冒烟测试：以"将来的检测程序"的方式（纯截屏 + 图像识别）验证游戏。

布局与真实游戏截图比例一致（config.LAYOUT / docs/layout.md）。覆盖：
  1. 求福主锚点：钓鱼三态可检（模板匹配≥0.85），HOME/订单详情/活动公告不可检
  2. 装备面板辅助锚点可隐藏，隐藏后求福仍可检（检测不得依赖装备面板）
  3. 五种稀有度名字颜色分类全部正确（名字条带内 HSV 分类）
  4. 出售(蓝)/提交订单(橙金)两种按钮均出现且可区分；提交订单推进订单进度
  5. 误触链路：点击订单面板（模拟检测程序点击越界偏高）→ 订单详情弹出
     → 求福不可检 → 关闭恢复
  6. 等待期任何点击无效；结算横幅（金色）可检
  7. 三套背景不影响以上全部判定

运行：  python tests/smoke_test.py   （会短暂弹出游戏窗口）
退出码：0 全部通过；1 存在失败项。截图存于 tests/__screenshots__/。
"""
from __future__ import annotations

import colorsys
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageGrab

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "game"))

from config import LAYOUT, WINDOW_H, WINDOW_W  # noqa: E402
from orders import Order  # noqa: E402
from states import Catch, GameModel, State  # noqa: E402
import states as states_mod  # noqa: E402
from ui import GameUI  # noqa: E402

OUT = Path(__file__).parent / "__screenshots__"
OUT.mkdir(exist_ok=True)

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
    if not ok:
        FAILS.append(name)


def ctr(z: dict) -> tuple[float, float]:
    return (z["x0"] + z["x1"]) / 2, (z["y0"] + z["y1"]) / 2


# ---------------------------------------------------------------- 检测函数（模拟将来插件）
def load_qiufu_template() -> np.ndarray:
    """圆形求福图标：缩放到绘制尺寸 48px，取圆心附近 28px 完全不透明区域做模板
    （避开透明角，避免模板与截图背景不匹配）。"""
    img = Image.open(ROOT / "game" / "assets" / "qiufu.png").convert("RGBA")
    img = img.resize((48, 48), Image.LANCZOS)
    arr = np.array(img).astype(np.uint8)
    return arr[10:38, 10:38, :3]      # 28x28 圆内不透明区


def qiufu_match(shot: np.ndarray, tpl: np.ndarray) -> float:
    """求福图标区域（左侧 y66.5%~71.5% 圆形图标）模板匹配。"""
    import cv2
    h, w = shot.shape[:2]
    crop = shot[int(.655 * h):int(.730 * h), int(.010 * w):int(.170 * w)]
    res = cv2.matchTemplate(crop.astype(np.uint8), tpl, cv2.TM_CCOEFF_NORMED)
    return float(res.max())


def classify_nameband(shot: np.ndarray) -> tuple[str, int]:
    """名字条带（x38%~62%, y49.5%~56.5%，排除左右金色纹样）内色相分类。"""
    h, w = shot.shape[:2]
    band = shot[int(.495 * h):int(.565 * h), int(.38 * w):int(.62 * w)].reshape(-1, 3)
    mx, mn = band.max(1).astype(int), band.min(1).astype(int)
    sel = band[((mx - mn) > 60) & (mx > 90)]
    n = len(sel)
    if n < 100:
        return "白", n        # 无饱和彩色文字 → 白色（普通）
    hues = np.array([colorsys.rgb_to_hsv(*p / 255)[0] * 360 for p in sel])
    mean_hue = hues.mean()
    for lo, hi, name in [(100, 160, "绿"), (195, 235, "蓝"), (255, 320, "紫"), (42, 65, "黄")]:
        if lo <= mean_hue <= hi:
            return name, n
    return f"未知(hue={mean_hue:.0f})", n


def button_kind(shot: np.ndarray) -> str:
    """识别左下按钮（x14%~43%, y79%~86%）：蓝=出售 / 橙金=提交订单。"""
    h, w = shot.shape[:2]
    z = LAYOUT["btn_left"]
    px_ = shot[int(z["y0"] * h):int(z["y1"] * h),
               int(z["x0"] * w):int(z["x1"] * w)].reshape(-1, 3).astype(int)
    blue = ((px_[:, 2] > px_[:, 0] + 40) & (px_[:, 2] > px_[:, 1] + 30) & (px_[:, 2] > 140)).sum()
    orange = ((px_[:, 0] > 200) & (px_[:, 1] > 130) & (px_[:, 1] < 210) & (px_[:, 2] < 120)).sum()
    if blue > 1500 and blue > orange:
        return "出售"
    if orange > 1500 and orange > blue:
        return "提交订单"
    return "未识别"


def equip_dark_px(shot: np.ndarray) -> int:
    """装备面板区域（x15%~90%, y15%~44%）的深色面板像素数。"""
    h, w = shot.shape[:2]
    z = LAYOUT["equip_panel"]
    px_ = shot[int(z["y0"] * h):int(z["y1"] * h), int(z["x0"] * w):int(z["x1"] * w)]
    return int((px_.max(2).astype(int) < 90).sum())


def banner_gold_px(shot: np.ndarray) -> int:
    """结算金色横幅条（x2%~98%, y20%~23%+文字区）像素数。"""
    h, w = shot.shape[:2]
    px_ = shot[int(.19 * h):int(.30 * h), int(.02 * w):int(.98 * w)].reshape(-1, 3).astype(int)
    return int(((px_[:, 0] > 190) & (px_[:, 1] > 140) & (px_[:, 2] < 130)).sum())


# ---------------------------------------------------------------- 截屏/驱动
def shot(ui: GameUI, name: str) -> np.ndarray:
    import time
    ui.render(force=True)          # 同步完整重绘，避免抓到半帧/上一帧
    ui.root.update_idletasks()
    ui.root.update()
    time.sleep(0.06)               # 等待窗口把画面上屏
    x, y = ui.root.winfo_rootx(), ui.root.winfo_rooty()
    img = np.array(ImageGrab.grab(bbox=(x, y, x + WINDOW_W, y + WINDOW_H)).convert("RGB"))
    Image.fromarray(img).save(OUT / f"{name}.png")
    return img


def drive_to_catch(ui: GameUI) -> None:
    """从 READY/WAITING 推进到 CATCH。"""
    if ui.model.state is State.READY:
        ui.click_pct(*ctr(LAYOUT["cast_zone"]))
    while ui.model.state is State.WAITING:
        ui.model.tick(0.05)
        ui.root.update()
    ui.root.update()


def main() -> int:
    if sys.platform == "win32":
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

    tpl = load_qiufu_template()
    m = GameModel(seed=7, wait_min=0.02, wait_max=0.05,
                  force_rarities=["白", "绿", "蓝", "紫", "黄"])
    ui = GameUI(m)
    ui.paused = True     # 暂停自动推进，全部由测试显式驱动（消除异步竞态）

    # ---- 1. HOME：非钓鱼界面 ----
    print("[1] HOME")
    img = shot(ui, "01_home")
    check("HOME 无求福锚点（应触发自动暂停）", qiufu_match(img, tpl) < 0.30,
          f"match={qiufu_match(img, tpl):.2f}")

    # ---- 2. READY：主锚点 + 辅助锚点（装备面板）+ 可隐藏 ----
    print("[2] READY 双锚点")
    ui.click_pct(*ctr(LAYOUT["home_btn"]))
    img = shot(ui, f"02_ready_{m.theme}")
    check("READY 求福可检", qiufu_match(img, tpl) >= 0.85, f"match={qiufu_match(img, tpl):.2f}")
    shown = equip_dark_px(img)
    check("READY 装备面板存在", shown > 30000, f"darkpx={shown}")
    ui.click_pct(*ctr(LAYOUT["settings"]))            # 隐藏装备面板
    img = shot(ui, f"03_ready_noequip_{m.theme}")
    hidden = equip_dark_px(img)
    check("装备面板已隐藏", hidden < 20000, f"darkpx={hidden}")
    check("隐藏装备面板后求福仍可检（不得依赖辅助锚点）", qiufu_match(img, tpl) >= 0.85,
          f"match={qiufu_match(img, tpl):.2f}")
    ui.click_pct(*ctr(LAYOUT["settings"]))            # 恢复

    # ---- 3. 等待期点击无效 ----
    print("[3] WAITING 点击无效")
    ui.click_pct(*ctr(LAYOUT["cast_zone"]))
    for xy in [ctr(LAYOUT["order_panel"]), (0.5, 0.9), ctr(LAYOUT["qiufu"])]:
        ui.click_pct(*xy)
    check("等待期点击不改变状态", m.state is State.WAITING, m.state.name)
    img = shot(ui, "04_waiting")
    bz = LAYOUT["bobber"]
    bobber = img[int((bz["y0"] - .01) * WINDOW_H):int((bz["y1"] + .01) * WINDOW_H),
                 int((bz["x0"] - .01) * WINDOW_W):int((bz["x1"] + .01) * WINDOW_W)]
    check("鱼漂可见（真实位置 x49.5%,y84%）", (bobber.min(2) > 190).sum() > 150)
    check("WAITING 求福可检", qiufu_match(img, tpl) >= 0.85, f"match={qiufu_match(img, tpl):.2f}")

    # ---- 4. 五色鱼：名字分类 + 按钮区分 + 订单推进 + 横幅可检 ----
    print("[4] 五色鱼获")
    yellow_orders = [Order(fish=f, need=1, reward=66) for f in ("霓虹鱼", "鳟鱼", "骨舌鱼")]
    m.orders.orders = yellow_orders
    themes_seen: set[str] = set()
    for expect in ["白", "绿", "蓝", "紫", "黄"]:
        drive_to_catch(ui)
        assert m.state is State.CATCH and m.catch is not None, m.state
        img = shot(ui, f"05_catch_{m.catch.rarity}_{m.catch.name}")
        themes_seen.add(m.theme)
        got_name, npx = classify_nameband(img)
        check(f"名字颜色分类 {m.catch.name}({m.catch.rarity}) -> {got_name}",
              got_name == expect, f"饱和px={npx}")
        want_kind = "提交订单" if m.catch.rarity == "黄" else "出售"
        kind = button_kind(img)
        check(f"按钮识别 {m.catch.name} -> {kind}", kind == want_kind, f"want={want_kind}")
        bg = banner_gold_px(img)
        check(f"结算金色横幅可检", bg > 4000, f"goldpx={bg}")
        ui.click_pct(*ctr(LAYOUT["btn_left"]))
        ui.root.update()
        if m.state is State.RANDOM_POPUP:
            ui.click_pct(*ctr(LAYOUT["ad_close_x"]))
            ui.root.update()
        themes_seen.add(m.theme)
    done_orders = [o.fish for o in yellow_orders if o.done]
    check("提交订单推进订单（黄鱼订单已达成）", len(done_orders) == 1, str(done_orders))
    check("三套背景至少出现两套（跨背景判定）", len(themes_seen) >= 2, ",".join(sorted(themes_seen)))

    # ---- 5. 误触链路：点击订单面板（模拟点击越界偏高）→ 订单详情 → 求福不可检 → 关闭 ----
    print("[5] 误触链路")
    assert m.state is State.READY, m.state
    m.orders.orders = [Order(fish="海星", need=2, reward=40)]
    act = ui.click_pct(*ctr(LAYOUT["order_rows"]))
    img = shot(ui, "06_order_detail")
    check("点击订单条目弹出订单详情", act == "open_detail" and m.state is State.ORDER_DETAIL)
    check("订单详情下求福不可检（自动暂停链路）", qiufu_match(img, tpl) < 0.30,
          f"match={qiufu_match(img, tpl):.2f}")
    ui.click_pct(*ctr(LAYOUT["close_x"]))
    ui.root.update()
    img = shot(ui, "07_back_ready")
    check("关闭后回到钓鱼界面", m.state is State.READY and qiufu_match(img, tpl) >= 0.85,
          f"match={qiufu_match(img, tpl):.2f}")

    # ---- 6. 随机活动弹窗：求福不可检 + 可关闭 ----
    print("[6] 活动公告弹窗")
    states_mod.RANDOM_AD_CHANCE = 1.0            # 强制下一次卖出弹公告
    m.catch = Catch("海星", "白", 0.3, 0.2)
    m.state = State.CATCH
    ui.click_pct(*ctr(LAYOUT["btn_left"]))
    ui.root.update()
    img = shot(ui, "08_random_popup")
    check("活动公告弹出", m.state is State.RANDOM_POPUP)
    check("活动公告下求福不可检", qiufu_match(img, tpl) < 0.30, f"match={qiufu_match(img, tpl):.2f}")
    ui.click_pct(*ctr(LAYOUT["ad_close_x"]))
    ui.root.update()
    check("公告关闭回到 READY", m.state is State.READY)

    ui.root.destroy()
    print()
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        return 1
    print("结果：全部通过 ✔")
    return 0


if __name__ == "__main__":
    sys.exit(main())
