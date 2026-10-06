"""tkinter 渲染层：按状态绘制画面，把点击换算成比例坐标交给 GameModel。

布局比例与真实游戏截图一致（见 config.LAYOUT / docs/layout.md）：
  - 顶部：资源栏(y12%~16.5%) + 装备/属性面板(y15%~44%，可隐藏，辅助锚点)
  - 左侧：垂钓助手/求福(主锚点)/奇异生物 圆形图标列
  - 右侧中部：订单面板(y43%~58%)
  - 等待态：竿尖(49%,59%)垂线至鱼漂(49.5%,84%)
  - 结算态：全屏压暗遮罩 + 悬浮元素（横幅/鱼图/名字条带/左对齐信息行/双按钮）
文字/按钮均用 PIL 预渲染（带描边），PhotoImage 带缓存。
"""
from __future__ import annotations

import math
from pathlib import Path

import tkinter as tk
from PIL import Image, ImageDraw, ImageFont, ImageTk

from config import LAYOUT, WINDOW_H, WINDOW_W
from fish_data import RARITIES
from states import SELL_PRICE, GameModel, State

ASSETS = Path(__file__).resolve().parent / "assets"

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
]

# 结算按钮配色（出售=蓝 / 提交订单=橙金 / 放入瑶池=金）
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
                d.line([(6, y), (w - 7, y)], fill=col)
            d.rounded_rectangle([2, 2, w - 3, h - 3], radius=h // 3,
                                outline=border, width=3)
            d.rounded_rectangle([6, 6, w - 7, h - 7], radius=h // 3 - 2,
                                outline=tuple(min(255, c + 50) for c in c1), width=1)
            f = ImageFont.truetype(_font_path(), int(h * 0.36))
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
        self._last = None            # 状态签名（变化才整帧重绘）
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

    # ---------------------------------------------------------------- 基础绘制
    def _img_at(self, name: str, zone: dict, size: tuple[int, int] | None = None) -> None:
        ph = self.r.img(name, size)
        x0, y0 = px(zone["x0"], WINDOW_W), px(zone["y0"], WINDOW_H)
        x1, y1 = px(zone["x1"], WINDOW_W), px(zone["y1"], WINDOW_H)
        self.canvas.create_image((x0 + x1 - ph.width()) // 2,
                                 (y0 + y1 - ph.height()) // 2, image=ph, anchor="nw")

    def _img_at_ph(self, ph: ImageTk.PhotoImage, zone: dict) -> None:
        x0, y0 = px(zone["x0"], WINDOW_W), px(zone["y0"], WINDOW_H)
        x1, y1 = px(zone["x1"], WINDOW_W), px(zone["y1"], WINDOW_H)
        self.canvas.create_image((x0 + x1 - ph.width()) // 2,
                                 (y0 + y1 - ph.height()) // 2, image=ph, anchor="nw")

    def _text_at(self, s: str, zone: dict, size: int,
                 fill: tuple[int, int, int], stroke=(30, 30, 30), sw: int = 2) -> None:
        ph = self.r.text(s, size, fill, stroke, sw)
        cx = (zone["x0"] + zone["x1"]) / 2 * WINDOW_W - ph.width() / 2
        cy = (zone["y0"] + zone["y1"]) / 2 * WINDOW_H - ph.height() / 2
        self.canvas.create_image(max(cx, 0), max(cy, 0), image=ph, anchor="nw")

    def _text_left(self, s: str, zone: dict, size: int,
                   fill: tuple[int, int, int], stroke=(30, 30, 30), sw: int = 1) -> None:
        """左对齐文字（真实结算信息行为左对齐 x≈11%）。"""
        ph = self.r.text(s, size, fill, stroke, sw)
        cy = (zone["y0"] + zone["y1"]) / 2 * WINDOW_H - ph.height() / 2
        self.canvas.create_image(px(zone["x0"], WINDOW_W), cy, image=ph, anchor="nw")

    def _panel(self, zone: dict, fill: str, outline: str, width: int = 2) -> None:
        self.canvas.create_rectangle(px(zone["x0"], WINDOW_W), px(zone["y0"], WINDOW_H),
                                     px(zone["x1"], WINDOW_W), px(zone["y1"], WINDOW_H),
                                     fill=fill, outline=outline, width=width)

    # ---------------------------------------------------------------- 钓鱼界面通用
    def _draw_fishing_chrome(self) -> None:
        m = self.model
        self.canvas.create_image(0, 0, image=self.r.img(f"bg_{m.theme}"), anchor="nw")
        # —— 顶部资源栏（体力/金币/珍珠/渔获）——
        self._panel(LAYOUT["resource_bar"], "#2c2418", "#8a6a3a", 2)
        res = f"体力 103/180   金币 {m.gold}   珍珠 273   渔获 {m.total_catch}"
        self._text_at(res, LAYOUT["resource_bar"], 13, (255, 232, 170))
        # —— 装备/属性面板（辅助锚点，可隐藏）——
        if m.equip_visible:
            self._panel(LAYOUT["equip_panel"], "#261f16", "#8a6a3a", 3)
            z = LAYOUT["equip_small"]
            for i, icon in enumerate(["eq_bait", "eq_line", "eq_hook"]):
                y0 = z["y0"] + i * (z["y1"] - z["y0"]) / 3
                self._img_at(icon, {"x0": z["x0"], "y0": y0, "x1": z["x1"],
                                    "y1": y0 + (z["y1"] - z["y0"]) / 3}, (30, 30))
            self._img_at("eq_rod", LAYOUT["equip_big"], (96, 96))
            self._text_at("Lv.3", {"x0": .44, "y0": .40, "x1": .52, "y1": .44}, 13, (255, 226, 130))
            za = LAYOUT["equip_attr"]
            for i, line in enumerate(["属性", "概率 12.4%", "强度 15.0", "钓鱼速度 12.0", "渔夫 Lv.6"]):
                y0 = za["y0"] + i * (za["y1"] - za["y0"]) / 5
                fill = (255, 246, 220) if i else (255, 214, 92)
                self._text_left(line, {"x0": za["x0"], "y0": y0, "x1": za["x1"],
                                       "y1": y0 + (za["y1"] - za["y0"]) / 5}, 13, fill)
        # —— 左侧功能图标列（垂钓助手/求福主锚点/奇异生物，圆形）——
        for key, icon, label, lab_fill in [
            ("assist", "icon_assist", "垂钓助手", (235, 230, 215)),
            ("qiufu", "qiufu", "求福", (255, 214, 92)),     # 真实：金色文字
            ("strange", "icon_strange", "奇异生物", (235, 230, 215)),
        ]:
            z = LAYOUT[key]
            icon_h = 0.050
            self._img_at(icon, {"x0": z["x0"], "y0": z["y0"], "x1": z["x1"],
                                "y1": z["y0"] + icon_h}, (48, 48))
            self._text_at(label, {"x0": z["x0"], "y0": z["y0"] + icon_h, "x1": z["x1"],
                                  "y1": z["y1"]}, 13, lab_fill)
        # —— 设置按钮（隐藏/显示装备面板）——
        self._panel(LAYOUT["settings"], "#3a332a", "#c9b47a")
        self._text_at("设", LAYOUT["settings"], 15, (240, 228, 190))

    # ---------------------------------------------------------------- 订单面板（右侧中部）
    def _draw_order_panel(self, highlight_idx: int | None = None) -> None:
        z = LAYOUT["order_panel"]
        m = self.model
        self._panel(z, "#241d2e", "#b79ae0", 2)
        # 竖排标题"今日订单"
        tz = LAYOUT["order_title"]
        for i, ch in enumerate("今日订单"):
            y0 = tz["y0"] + i * (tz["y1"] - tz["y0"]) / 4
            self._text_at(ch, {"x0": tz["x0"], "y0": y0, "x1": tz["x1"],
                               "y1": y0 + (tz["y1"] - tz["y0"]) / 4}, 14, (240, 226, 255))
        # 订单条目
        rz = LAYOUT["order_rows"]
        rows = max(len(m.orders.orders), 1)
        row_h = (rz["y1"] - rz["y0"]) / rows
        for i, o in enumerate(m.orders.orders):
            y0 = rz["y0"] + i * row_h
            row = {"x0": rz["x0"], "y0": y0, "x1": rz["x1"], "y1": y0 + row_h - 0.004}
            if highlight_idx == i:
                self._panel(row, "#4a3b66", "#e8d9ff")
            rar = RARITIES[o.rarity]
            self._img_at(f"fish_{o.fish}", {"x0": row["x0"], "y0": row["y0"],
                                            "x1": row["x0"] + 0.055, "y1": row["y1"]}, (30, 18))
            self._text_at(o.fish, {"x0": row["x0"] + 0.058, "y0": row["y0"],
                                   "x1": row["x1"] - 0.06, "y1": row["y1"]},
                          12, rar.rgb, rar.stroke, 1)
            prog = f"{min(o.got, o.need)}/{o.need}"
            label = "完成" if o.done else prog
            color = (150, 235, 130) if o.done else (245, 245, 245)
            self._text_at(label, {"x0": row["x1"] - 0.055, "y0": row["y0"],
                                  "x1": row["x1"], "y1": row["y1"]}, 12, color)
        # "订单详情"链接（点击任意订单条目同样打开详情）
        self._text_at("订单详情 ▸", LAYOUT["order_link"], 12, (200, 190, 255))

    # ---------------------------------------------------------------- 各状态
    def render(self, force: bool = False) -> None:
        m = self.model
        st = m.state
        self.canvas.delete("all")
        if st is State.HOME:
            self.canvas.create_image(0, 0, image=self.r.img("bg_taolin"), anchor="nw")
            self._text_at("渔樵 · 验证", {"x0": .1, "y0": .22, "x1": .9, "y1": .30}, 52, (255, 226, 130), (110, 60, 20), 4)
            self._text_at("简单钓鱼游戏验证 v0.1（自动化测试用）", {"x0": .1, "y0": .31, "x1": .9, "y1": .34}, 15, (245, 240, 225))
            self._img_at_ph(self.r.button("进入钓鱼", 200, 64), LAYOUT["home_btn"])
            self._text_at("点击进入钓鱼", {"x0": .1, "y0": .70, "x1": .9, "y1": .74}, 13, (235, 230, 215))
            return

        if st in (State.READY, State.WAITING, State.CATCH):
            self._draw_fishing_chrome()

        if st is State.READY:
            self._draw_order_panel()
            self._text_at("点击水面开始钓鱼", LAYOUT["cast_hint"], 24, (240, 250, 255), (30, 50, 70), 3)
        elif st is State.WAITING:
            self._draw_order_panel()
            self._draw_waiting_scene()
        elif st is State.CATCH:
            self._draw_catch()
        elif st is State.ORDER_DETAIL:
            self._draw_fishing_chrome()
            self._draw_order_panel(highlight_idx=m.order_detail_idx)
            self._draw_order_detail()
        elif st is State.RANDOM_POPUP:
            # 弹窗盖在被打断的场景之上（真实游戏：公告随时可能盖住等待/结算画面）
            self._draw_fishing_chrome()
            if m.return_state is State.WAITING:
                self._draw_order_panel()
                self._draw_waiting_scene()
            elif m.return_state is State.CATCH:
                self._draw_catch()
            self._draw_ad()

    def _draw_waiting_scene(self) -> None:
        """竿尖(49%,59%)垂线至鱼漂(49.5%,84%) + 涟漪动画（真实 waiting 布局）。"""
        tip = ((LAYOUT["rod_tip"]["x0"] + LAYOUT["rod_tip"]["x1"]) / 2,
               (LAYOUT["rod_tip"]["y0"] + LAYOUT["rod_tip"]["y1"]) / 2)
        bob = math.sin(self._anim_i * 0.25) * 0.004
        bx = (LAYOUT["bobber"]["x0"] + LAYOUT["bobber"]["x1"]) / 2
        by = (LAYOUT["bobber"]["y0"] + LAYOUT["bobber"]["y1"]) / 2 + bob
        # 鱼线
        self.canvas.create_line(px(tip[0], WINDOW_W), px(tip[1], WINDOW_H),
                                px(bx, WINDOW_W), px(by - 0.008, WINDOW_H),
                                fill="#e8f2f0", width=1)
        # 竿尖小段
        self.canvas.create_line(px(tip[0] - 0.05, WINDOW_W), px(tip[1] - 0.03, WINDOW_H),
                                px(tip[0], WINDOW_W), px(tip[1], WINDOW_H),
                                fill="#7a5a38", width=3)
        # 鱼漂（30px）+ 涟漪
        ph = self.r.img("bobber", (30, 27))
        cx, cy = px(bx, WINDOW_W), px(by, WINDOW_H)
        self.canvas.create_image(cx - ph.width() // 2, cy - ph.height() // 2, image=ph, anchor="nw")
        for k in range(3):
            phase = ((self._anim_i * 0.02 + k / 3) % 1.0)
            rad = 8 + phase * 30
            self.canvas.create_oval(cx - rad, cy - rad * 0.4, cx + rad, cy + rad * 0.4,
                                    outline="#d8f0ee", width=2)

    # ---------------------------------------------------------------- 结算（全屏压暗+悬浮元素）
    def _draw_catch(self) -> None:
        m = self.model
        c = m.catch
        assert c is not None
        rar = RARITIES[c.rarity]
        # 全屏压暗遮罩（真实游戏为半透明暗罩，图标列透出但变暗）
        self.canvas.create_image(0, 0, image=self.r.img("scrim",
                                                        (WINDOW_W, WINDOW_H)), anchor="nw")
        # 金色横幅条 + "恭喜获得！！"
        self._img_at("banner_strip", LAYOUT["banner_strip"])
        self._text_at("恭喜获得！！", LAYOUT["banner_text"], 36, (255, 218, 92), (110, 60, 10), 3)
        # 鱼图
        self._img_at(f"fish_{c.name}", LAYOUT["fish_img"], (130, 76))
        # 名字条带：左右金色纹样 + 中央稀有度颜色名字（★检测目标）
        zs = LAYOUT["name_strip"]
        yc = (zs["y0"] + zs["y1"]) / 2
        for x0, x1 in [((zs["x0"]), (LAYOUT["name_band"]["x0"] - 0.01)),
                       ((LAYOUT["name_band"]["x1"] + 0.01), (zs["x1"]))]:
            self.canvas.create_line(px(x0, WINDOW_W), px(yc, WINDOW_H),
                                    px(x1, WINDOW_W), px(yc, WINDOW_H),
                                    fill="#d9b96a", width=3)
            self.canvas.create_polygon(px((x0 + x1) / 2, WINDOW_W) - 5, px(yc, WINDOW_H) - 7,
                                       px((x0 + x1) / 2, WINDOW_W) + 5, px(yc, WINDOW_H),
                                       px((x0 + x1) / 2, WINDOW_W) - 5, px(yc, WINDOW_H) + 7,
                                       fill="#d9b96a")
        self._text_at(c.name, LAYOUT["name_band"], 44, rar.rgb, rar.stroke, 3)
        # 信息行（左对齐 x≈11%，真实样式：长度红字）
        self._text_left(f"长度：{c.length} 米", LAYOUT["stat_len"], 16, (226, 96, 84), (60, 20, 16))
        self._text_left(f"稀有度 · {rar.label}     重量：{c.weight} 公斤", LAYOUT["stat_power"], 15, (245, 245, 245))
        self._text_at(f"来自验证渔场的{c.name}，等一个有缘人。", LAYOUT["stat_desc"], 13, (205, 205, 205))
        # 双按钮 + 价格行
        left_label = m.catch_action_label()
        self._img_at_ph(self.r.button(left_label, 152, 64), LAYOUT["btn_left"])
        self._img_at_ph(self.r.button("放入瑶池", 152, 64), LAYOUT["btn_right"])
        price = "订单进度 +1" if left_label == "提交订单" else f"金币 +{SELL_PRICE[c.rarity]}"
        self._text_at(price, LAYOUT["btn_price"], 13, (255, 214, 92))

    # ---------------------------------------------------------------- 干扰弹窗
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
