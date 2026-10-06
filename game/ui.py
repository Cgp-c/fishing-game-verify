"""tkinter 渲染层：按状态绘制画面，把点击换算成比例坐标交给 GameModel。

文字/按钮均用 PIL 预渲染（带描边，与真实游戏"彩字+深描边"一致），PhotoImage 带缓存。
"""
from __future__ import annotations

import math
from pathlib import Path

import tkinter as tk
from PIL import Image, ImageDraw, ImageFont, ImageTk

from config import LAYOUT, WINDOW_H, WINDOW_W
from fish_data import RARITIES
from states import GameModel, State

ASSETS = Path(__file__).resolve().parent / "assets"

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
]

# 按钮配色（出售=蓝 / 提交订单=橙金 / 放入瑶池=金 / 进入钓鱼=蓝）
BTN_STYLE = {
    "出售":   ((96, 168, 236), (54, 110, 190), (24, 62, 120)),
    "提交订单": ((244, 176, 82), (208, 128, 40), (120, 70, 16)),
    "放入瑶池": ((240, 214, 120), (206, 168, 66), (122, 92, 26)),
    "进入钓鱼": ((96, 168, 236), (54, 110, 190), (24, 62, 120)),
}


def _font_path() -> str:
    for p in FONT_CANDIDATES:
        if Path(p).exists():
            return p
    raise FileNotFoundError("未找到中文字体")


class Renderer:
    """PIL 预渲染缓存：图片/描边文字/按钮。"""

    def __init__(self) -> None:
        self._imgs: dict[str, ImageTk.PhotoImage] = {}
        self._texts: dict[tuple, ImageTk.PhotoImage] = {}
        self._btns: dict[tuple, ImageTk.PhotoImage] = {}

    def img(self, name: str, size: tuple[int, int] | None = None) -> ImageTk.PhotoImage:
        key = f"{name}@{size}"
        if key not in self._imgs:
            im = Image.open(ASSETS / f"{name}.png").convert("RGBA")
            if size:
                im = im.resize(size, Image.LANCZOS)
            self._imgs[key] = ImageTk.PhotoImage(im)
        return self._imgs[key]

    def text(self, s: str, size: int, fill: tuple[int, int, int],
             stroke: tuple[int, int, int] = (30, 30, 30), sw: int = 2) -> ImageTk.PhotoImage:
        key = (s, size, fill, stroke, sw)
        if key not in self._texts:
            f = ImageFont.truetype(_font_path(), size)
            tmp = Image.new("RGBA", (10, 10))
            d = ImageDraw.Draw(tmp)
            bbox = d.textbbox((0, 0), s, font=f, stroke_width=sw)
            w, h = bbox[2] - bbox[0] + 4, bbox[3] - bbox[1] + 4
            im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            d = ImageDraw.Draw(im)
            d.text((2 - bbox[0], 2 - bbox[1]), s, font=f, fill=fill,
                   stroke_width=sw, stroke_fill=stroke)
            self._texts[key] = ImageTk.PhotoImage(im)
        return self._texts[key]

    def button(self, label: str, w: int, h: int) -> ImageTk.PhotoImage:
        c1, c2, border = BTN_STYLE[label]
        key = (label, w, h)
        if key not in self._btns:
            im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            d = ImageDraw.Draw(im)
            for y in range(h):     # 竖向渐变
                t = y / max(h - 1, 1)
                col = tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))
                d.line([(4, y), (w - 5, y)], fill=col)
            d.rounded_rectangle([1, 1, w - 2, h - 2], radius=h // 3,
                                outline=border, width=3)
            d.rounded_rectangle([5, 5, w - 6, h - 6], radius=h // 3 - 2,
                                outline=tuple(min(255, c + 50) for c in c1), width=1)
            f = ImageFont.truetype(_font_path(), int(h * 0.38))
            bb = d.textbbox((0, 0), label, font=f)
            d.text(((w - bb[2] - bb[0]) / 2, (h - bb[3] - bb[1]) / 2 - 1), label,
                   font=f, fill=(255, 252, 240), stroke_width=1,
                   stroke_fill=tuple(max(0, c - 60) for c in border))
            self._btns[key] = ImageTk.PhotoImage(im)
        return self._btns[key]


def px(v: float, total: int) -> int:
    return int(v * total)


class GameUI:
    def __init__(self, model: GameModel) -> None:
        self.model = model
        self.root = tk.Tk()
        self.root.title("简单钓鱼游戏验证")
        self.root.geometry(f"{WINDOW_W}x{WINDOW_H}+60+10")
        self.canvas = tk.Canvas(self.root, width=WINDOW_W, height=WINDOW_H,
                                highlightthickness=0, bg="#20303a")
        self.canvas.pack()
        self.r = Renderer()
        self.canvas.bind("<Button-1>", self._on_click)
        self._last = None            # (state, theme, equip, catch签名) 变化检测
        self._anim_i = 0
        self.paused = False          # 测试用：暂停自动 tick/动画，由外部显式驱动
        self.root.after(50, self._frame)

    # ---------------------------------------------------------------- 事件
    def _on_click(self, e: tk.Event) -> str:
        act = self.model.click(e.x / WINDOW_W, e.y / WINDOW_H)
        self.render()
        return act

    def click_pct(self, x: float, y: float) -> str:
        """测试钩子：按比例坐标点击。"""
        act = self.model.click(x, y)
        self.render()
        return act

    # ---------------------------------------------------------------- 主循环
    def _frame(self) -> None:
        if not self.paused:
            self.model.tick(0.05)
            self._anim_i += 1
            self.render(force=self._needs_full_redraw())
        self.root.after(50, self._frame)

    def _needs_full_redraw(self) -> bool:
        m = self.model
        sig = (m.state, m.theme, m.equip_visible, id(m.catch),
               m.gold, m.total_catch,
               tuple((o.fish, o.got, o.done) for o in m.orders.orders),
               m.order_detail_idx)
        if sig != self._last:
            self._last = sig
            return True
        return False

    # ---------------------------------------------------------------- 绘制
    def _img_at(self, name: str, zone: dict, size: tuple[int, int] | None = None) -> None:
        ph = self.r.img(name, size)
        x0, y0 = px(zone["x0"], WINDOW_W), px(zone["y0"], WINDOW_H)
        x1, y1 = px(zone["x1"], WINDOW_W), px(zone["y1"], WINDOW_H)
        self.canvas.create_image((x0 + x1 - ph.width()) // 2,
                                 (y0 + y1 - ph.height()) // 2, image=ph, anchor="nw")

    def _text_at(self, s: str, zone: dict, size: int,
                 fill: tuple[int, int, int], stroke=(30, 30, 30), sw=2) -> None:
        ph = self.r.text(s, size, fill, stroke, sw)
        cx = (zone["x0"] + zone["x1"]) / 2 * WINDOW_W - ph.width() / 2
        cy = (zone["y0"] + zone["y1"]) / 2 * WINDOW_H - ph.height() / 2
        self.canvas.create_image(max(cx, 0), max(cy, 0), image=ph, anchor="nw")

    def _panel(self, zone: dict, fill: str, outline: str, width: int = 2) -> None:
        self.canvas.create_rectangle(px(zone["x0"], WINDOW_W), px(zone["y0"], WINDOW_H),
                                     px(zone["x1"], WINDOW_W), px(zone["y1"], WINDOW_H),
                                     fill=fill, outline=outline, width=width)

    def _draw_fishing_chrome(self) -> None:
        """三个钓鱼态共通：背景/左侧图标列/装备栏/HUD/设置。"""
        m = self.model
        self.canvas.create_image(0, 0, image=self.r.img(f"bg_{m.theme}"), anchor="nw")
        # 左侧功能列（求福为主锚点，始终可见于钓鱼三态）
        self._img_at("qiufu", {"x0": .030, "y0": .700, "x1": .165, "y1": .798})
        self._text_at("求福", {"x0": .030, "y0": .798, "x1": .165, "y1": .826}, 13, (255, 246, 220))
        self._img_at("icon_assist", {"x0": .030, "y0": .838, "x1": .165, "y1": .936})
        self._text_at("垂钓助手", {"x0": .015, "y0": .936, "x1": .180, "y1": .958}, 11, (235, 230, 215))
        # 顶部装备栏（辅助锚点，可隐藏）
        if m.equip_visible:
            self._panel(LAYOUT["equip_bar"], "#2c2418", "#8a6a3a")
            for i, (icon, label) in enumerate([("eq_bait", "鱼饵 Lv.1"), ("eq_rod", "鱼竿 Lv.3"),
                                               ("eq_line", "鱼线 Lv.16"), ("eq_hook", "鱼钩 Lv.9")]):
                x = 0.04 + i * 0.115
                self._img_at(icon, {"x0": x, "y0": .014, "x1": x + .08, "y1": .048}, (26, 26))
                self._text_at(label, {"x0": x - .01, "y0": .048, "x1": x + .09, "y1": .062}, 9, (240, 230, 205))
        # HUD
        self._text_at(f"金币 {m.gold}", {"x0": .03, "y0": .072, "x1": .24, "y1": .10}, 16, (255, 214, 92))
        self._text_at(f"渔获 {m.total_catch}", {"x0": .24, "y0": .072, "x1": .45, "y1": .10}, 16, (235, 235, 235))
        # 设置按钮
        self._panel(LAYOUT["settings"], "#3a332a", "#c9b47a")
        self._text_at("设", LAYOUT["settings"], 18, (240, 228, 190))

    def _draw_order_panel(self, highlight_idx: int | None = None) -> None:
        z = LAYOUT["order_panel"]
        m = self.model
        self._panel(z, "#241d2e", "#b79ae0", 3)
        self._text_at("订单", {"x0": z["x0"], "y0": z["y0"] + .004, "x1": z["x1"], "y1": z["y0"] + .034}, 15, (240, 226, 255))
        rows = len(m.orders.orders)
        row_h = (z["y1"] - z["y0"] - 0.036) / rows
        for i, o in enumerate(m.orders.orders):
            y0 = z["y0"] + 0.036 + i * row_h
            row = {"x0": z["x0"] + .008, "y0": y0, "x1": z["x1"] - .008, "y1": y0 + row_h - .006}
            if highlight_idx == i:
                self._panel(row, "#4a3b66", "#e8d9ff")
            rar = RARITIES[o.rarity]
            self._img_at(f"fish_{o.fish}", {"x0": row["x0"], "y0": row["y0"], "x1": row["x0"] + .075, "y1": row["y1"]}, (44, 26))
            self._text_at(o.fish, {"x0": row["x0"] + .08, "y0": row["y0"], "x1": row["x1"] - .09, "y1": row["y0"] + row_h * .55},
                          14, rar.rgb, rar.stroke, 1)
            prog = f"{min(o.got, o.need)}/{o.need}"
            label = "完成" if o.done else prog
            color = (150, 235, 130) if o.done else (245, 245, 245)
            self._text_at(label, {"x0": row["x1"] - .085, "y0": row["y0"], "x1": row["x1"], "y1": row["y0"] + row_h * .55}, 13, color)

    def render(self, force: bool = False) -> None:
        m = self.model
        st = m.state
        self.canvas.delete("all")
        if st is State.HOME:
            self.canvas.create_image(0, 0, image=self.r.img("bg_taolin"), anchor="nw")
            self._text_at("渔樵 · 验证", {"x0": .1, "y0": .22, "x1": .9, "y1": .30}, 52, (255, 226, 130), (110, 60, 20), 4)
            self._text_at("简单钓鱼游戏验证 v0.1（自动化测试用）", {"x0": .1, "y0": .31, "x1": .9, "y1": .34}, 15, (245, 240, 225))
            ph = self.r.button("进入钓鱼", 200, 64)
            self._img_at_ph(ph, LAYOUT["home_btn"])
            self._text_at("点击进入钓鱼", {"x0": .1, "y0": .70, "x1": .9, "y1": .74}, 13, (235, 230, 215))
            return

        if st in (State.READY, State.WAITING, State.CATCH):
            self._draw_fishing_chrome()

        if st is State.READY:
            self._draw_order_panel()
            self._text_at("点击水面开始钓鱼", LAYOUT["cast_hint"], 26, (255, 255, 255), (40, 60, 80), 3)
        elif st is State.WAITING:
            self._draw_order_panel()
            # 鱼漂 + 涟漪动画
            bob = math.sin(self._anim_i * 0.25) * 4
            cx, cy = int(0.47 * WINDOW_W), int(0.71 * WINDOW_H + bob)
            ph = self.r.img("bobber")
            self.canvas.create_image(cx - ph.width() // 2, cy - ph.height() // 2, image=ph, anchor="nw")
            for k in range(3):
                phase = ((self._anim_i * 0.02 + k / 3) % 1.0)
                rad = 14 + phase * 46
                self.canvas.create_oval(cx - rad, cy - rad * 0.4, cx + rad, cy + rad * 0.4,
                                        outline="#d8f0ee", width=2)
        elif st is State.CATCH:
            self._draw_catch()
        elif st is State.ORDER_DETAIL:
            # 底层仍是来源画面（READY），再盖详情卡
            self._draw_fishing_chrome()
            self._draw_order_panel(highlight_idx=m.order_detail_idx)
            self._draw_order_detail()
        elif st is State.RANDOM_POPUP:
            self._draw_fishing_chrome()
            self._draw_ad()

    def _img_at_ph(self, ph: ImageTk.PhotoImage, zone: dict) -> None:
        x0, y0 = px(zone["x0"], WINDOW_W), px(zone["y0"], WINDOW_H)
        x1, y1 = px(zone["x1"], WINDOW_W), px(zone["y1"], WINDOW_H)
        self.canvas.create_image((x0 + x1 - ph.width()) // 2,
                                 (y0 + y1 - ph.height()) // 2, image=ph, anchor="nw")

    # ---------------------------------------------------------------- 结算弹窗
    def _draw_catch(self) -> None:
        m = self.model
        c = m.catch
        assert c is not None
        rar = RARITIES[c.rarity]
        z = LAYOUT["popup_card"]
        # 卡片：羊皮纸底 + 金边（金色装饰干扰保留）
        self._panel(z, "#f2e7c9", "#c9a24a", 6)
        x0, y0 = px(z["x0"], WINDOW_W), px(z["y0"], WINDOW_H)
        x1, y1 = px(z["x1"], WINDOW_W), px(z["y1"], WINDOW_H)
        self.canvas.create_line(x0 + 16, y0 + 40, x1 - 16, y0 + 40, fill="#d9b96a", width=2)
        self.canvas.create_line(x0 + 16, y1 - 46, x1 - 16, y1 - 46, fill="#d9b96a", width=2)
        # 金横幅 + 恭喜获得
        self._img_at("banner_gold", LAYOUT["banner"])
        self._text_at("恭喜获得！！", LAYOUT["banner"], 26, (120, 72, 20), (255, 238, 180), 1)
        # 鱼图 + 名字（稀有度颜色+描边，检测目标）
        self._img_at(f"fish_{c.name}", LAYOUT["fish_img"])
        self._text_at(c.name, LAYOUT["name_band"], 46, rar.rgb, rar.stroke, 3)
        self._text_at(f"稀有度 · {rar.label}", {"x0": .30, "y0": .555, "x1": .70, "y1": .585}, 13, (110, 90, 60))
        self._text_at(f"长度 {c.length} 米    重量 {c.weight} 公斤",
                      {"x0": .20, "y0": .60, "x1": .80, "y1": .64}, 17, (90, 72, 48))
        # 双按钮：出售/提交订单（按订单匹配切换）+ 放入瑶池
        left_label = m.catch_action_label()
        self._img_at_ph(self.r.button(left_label, 154, 62), LAYOUT["btn_left"])
        self._img_at_ph(self.r.button("放入瑶池", 154, 62), LAYOUT["btn_right"])

    # ---------------------------------------------------------------- 弹窗
    def _draw_order_detail(self) -> None:
        m = self.model
        z = LAYOUT["order_card"]
        self._panel(z, "#efe6cd", "#a98bd2", 5)
        self._text_at("订单详情", {"x0": z["x0"], "y0": z["y0"] + .012, "x1": z["x1"] - .06, "y1": z["y0"] + .06}, 22, (96, 66, 140))
        o = m.orders.orders[m.order_detail_idx or 0]
        rar = RARITIES[o.rarity]
        self._img_at(f"fish_{o.fish}", {"x0": .06, "y0": .42, "x1": .30, "y1": .56})
        self._text_at(o.fish, {"x0": .30, "y0": .44, "x1": .58, "y1": .50}, 30, rar.rgb, rar.stroke, 2)
        self._text_at(f"提交 {min(o.got, o.need)}/{o.need} 条即可完成", {"x0": .30, "y0": .50, "x1": .60, "y1": .545}, 14, (90, 72, 48))
        self._text_at(f"奖励金币 {o.reward}", {"x0": .30, "y0": .55, "x1": .60, "y1": .59}, 14, (188, 140, 40))
        # 关闭 X
        xz = LAYOUT["close_x"]
        self.canvas.create_text((xz["x0"] + xz["x1"]) / 2 * WINDOW_W,
                                (xz["y0"] + xz["y1"]) / 2 * WINDOW_H,
                                text="✕", font=("msyh", 20, "bold"), fill="#8c3c3c")

    def _draw_ad(self) -> None:
        z = LAYOUT["ad_card"]
        self._panel(z, "#f5efdc", "#d08a4a", 5)
        self._text_at("活动公告", {"x0": z["x0"], "y0": z["y0"] + .02, "x1": z["x1"] - .07, "y1": z["y0"] + .08}, 24, (170, 90, 40))
        self._text_at("渔樵大会即将开始，诚邀各位渔友参加～", {"x0": z["x0"] + .05, "y0": .40, "x1": z["x1"] - .05, "y1": .46}, 16, (96, 78, 52))
        self._text_at("（此弹窗用于测试：非钓鱼界面应触发自动暂停）", {"x0": z["x0"] + .05, "y0": .48, "x1": z["x1"] - .05, "y1": .53}, 13, (140, 120, 90))
        xz = LAYOUT["ad_close_x"]
        self.canvas.create_text((xz["x0"] + xz["x1"]) / 2 * WINDOW_W,
                                (xz["y0"] + xz["y1"]) / 2 * WINDOW_H,
                                text="✕", font=("msyh", 20, "bold"), fill="#8c3c3c")
