"""
dashboard.py - 업무시간 현황 GUI (tkinter, 추가 설치 불필요)

py dashboard.py        # 콘솔과 함께 실행 (디버그)
pythonw dashboard.py   # 콘솔 없이 GUI 만 (트레이 메뉴가 이 방식으로 실행)

따뜻한 라이트(미니멀) 테마 카드 UI + 주간 막대그래프 + 5초 자동 새로고침.
위젯은 한 번만 생성하고 값만 갱신하므로 새로고침 시 깜빡임이 없다.
"""

import tkinter as tk
from tkinter import font as tkfont
from datetime import date, datetime, timedelta

from PIL import Image, ImageDraw, ImageTk

import storage as S

# ----- 색상/폰트 테마 (Manus 풍 따뜻한 라이트 미니멀) -----
BG = "#F4F1EA"      # 따뜻한 크림 배경
CARD = "#FFFFFF"    # 카드 표면
CARD2 = "#EFEBE0"   # 보조 표면 / 트랙 / 칩
HOVER = "#E7E1D2"   # 마우스 오버
BORDER = "#E6E1D4"  # 카드/구분 테두리
FG = "#26282E"      # 본문 (따뜻한 차콜)
SUB = "#8C887E"     # 보조 텍스트
ACCENT = "#5B5BD6"  # 포인트 (바이올렛/인디고)
TODAY = "#D98E4A"   # 오늘 강조 (테라코타)
GOOD = "#2F9E6B"    # 양호 / 업무중 / 저장 (세이지)

# 토글 스위치 색
TOGGLE_ON = "#3FA06B"    # 켜짐 트랙 - 세이지 그린
TOGGLE_OFF = "#CFC9BB"   # 꺼짐 트랙 - 웜 그레이
TOGGLE_KNOB = "#FFFFFF"  # knob
# 비활성(편집 잠금) 상태 색 - 흐리게
TOGGLE_ON_DIS = "#BBD7C6"
TOGGLE_OFF_DIS = "#E2DCCF"
TOGGLE_KNOB_DIS = "#F6F3EC"

# 휴가/출장 색
VAC = "#7C6CE0"          # 휴가 - 라벤더
TRIP = "#2FA08A"         # 출장 - 청록

WEEKDAYS_SHOWN = 5       # 주간 표시 일수 (월~금, 토·일 제외)

FONT = "맑은 고딕"
WEEKDAY = ["월", "화", "수", "목", "금", "토", "일"]

REFRESH_MS = 5000
WORKDAY_SCALE_SEC = 8 * 3600  # 막대 길이 기준 (8시간)

BAR_X0 = 60       # 막대 시작 x (요일 라벨 영역 다음)
BAR_MAX = 300     # 막대 최대 길이
VAL_W = 96        # 막대 오른쪽 시간 숫자 영역
CHART_W = BAR_X0 + BAR_MAX + VAL_W
ROW_H = 26


class Stepper:
    """`−  [숫자]  +` 형태의 숫자 입력 위젯 (tk.Spinbox 대체).

    사용성 개선 포인트:
      - 입력란을 클릭/포커스하면 **전체 선택** → 숫자를 한 번에 교체.
      - 편집 중 커서는 **깜박이지 않고** 고정(insertofftime=0).
      - Enter / 좌우 버튼 / 다른 곳 클릭으로 **확정하면 포커스가 빠져 커서가 사라짐**.
      - 좌우 −/+ 는 작고 깔끔한 플랫 버튼.
    """

    def __init__(self, parent, value, lo, hi, on_commit=None, width=3):
        self.lo, self.hi = lo, hi
        self.on_commit = on_commit
        self.enabled = True
        self.var = tk.StringVar(value=str(int(value)))

        self.frame = tk.Frame(parent, bg=CARD)
        self.minus = self._btn("−", lambda: self._step(-1))
        self.minus.pack(side="left")
        self.entry = tk.Entry(
            self.frame, textvariable=self.var, width=width, justify="center",
            font=(FONT, 11, "bold"),
            bg=CARD2, fg=FG, disabledbackground=CARD, disabledforeground=SUB,
            relief="flat", bd=0, insertbackground=FG,
            insertofftime=0,   # 커서 깜박임 제거 (고정 커서)
            highlightthickness=1, highlightbackground=CARD2, highlightcolor=ACCENT,
        )
        self.entry.pack(side="left", padx=3, ipady=2)
        self.plus = self._btn("+", lambda: self._step(1))
        self.plus.pack(side="left")

        self.entry.bind("<FocusIn>", lambda e: self.entry.after(1, self._select_all))
        self.entry.bind("<Button-1>", self._on_click)
        self.entry.bind("<Return>", self._on_return)
        self.entry.bind("<KP_Enter>", self._on_return)
        self.entry.bind("<FocusOut>", lambda e: self._commit())

    def _btn(self, text, cmd):
        return tk.Button(
            self.frame, text=text, command=cmd, font=(FONT, 11, "bold"),
            width=1, bg=CARD2, fg=ACCENT,
            activebackground=ACCENT, activeforeground="#FFFFFF",
            relief="flat", bd=0, padx=2, pady=0, cursor="hand2", takefocus=0,
        )

    def value(self) -> int:
        try:
            v = int(float(self.var.get()))
        except (ValueError, TypeError):
            v = self.lo
        return max(self.lo, min(self.hi, v))

    def set(self, v):
        self.var.set(str(max(self.lo, min(self.hi, int(v)))))

    def set_enabled(self, on: bool):
        self.enabled = bool(on)
        state = "normal" if on else "disabled"
        self.entry.config(state=state)
        for b in (self.minus, self.plus):
            b.config(state=state, fg=(ACCENT if on else SUB))

    def _select_all(self):
        if self.enabled:
            self.entry.select_range(0, "end")
            self.entry.icursor("end")

    def _on_click(self, e):
        if not self.enabled:
            return "break"
        self.entry.focus_set()
        self._select_all()
        return "break"   # 기본 클릭 처리(선택 해제)를 막아 항상 전체 선택

    def _commit(self):
        self.set(self.value())          # 입력 텍스트 정규화 + 범위 클램프
        if self.on_commit:
            self.on_commit()

    def _defocus(self):
        self.entry.selection_clear()
        self.frame.focus_set()          # 입력란에서 포커스 제거 → 커서 사라짐

    def _on_return(self, e):
        self._commit()
        self._defocus()
        return "break"

    def _step(self, d):
        if not self.enabled:
            return
        self.set(self.value() + d)
        self._commit()
        self._defocus()


class ToggleSwitch:
    """둥근 on/off 토글 스위치 (밋밋한 tk.Checkbutton 대체).

    tkinter Canvas 는 안티앨리어싱이 없어 원이 계단처럼 깨진다. 그래서 Pillow 로
    4배 크게 그린 뒤 LANCZOS 로 줄여(슈퍼샘플링) 매끈한 이미지를 만들어 Label 에 띄운다.
    클릭하면 BooleanVar 를 뒤집고, var 에 trace 를 걸어 값이 바뀌면 다시 그린다.
    """

    W, H = 48, 26     # 표시 크기(px)
    SS = 4            # 슈퍼샘플링 배율

    def __init__(self, parent, variable, bg=CARD):
        self.var = variable
        self.bg = bg
        self.enabled = True
        self._imgs = {}   # (on, enabled) 이미지 캐시 (PhotoImage 참조 유지용)
        self.widget = tk.Label(parent, bg=bg, bd=0, cursor="hand2")
        self.widget.bind("<Button-1>", self._toggle)
        self.var.trace_add("write", lambda *a: self._render())
        self._render()

    def _build_image(self, on: bool, enabled: bool) -> ImageTk.PhotoImage:
        ss = self.SS
        W, H = self.W * ss, self.H * ss
        if enabled:
            track, knob = (TOGGLE_ON if on else TOGGLE_OFF), TOGGLE_KNOB
        else:
            track, knob = (TOGGLE_ON_DIS if on else TOGGLE_OFF_DIS), TOGGLE_KNOB_DIS
        img = Image.new("RGB", (W, H), self.bg)   # 배경을 카드색으로 채워 가장자리 자연스럽게
        dr = ImageDraw.Draw(img)
        dr.rounded_rectangle([0, 0, W - 1, H - 1], radius=(H - 1) / 2, fill=track)
        m = 3 * ss                       # knob 여백
        d = H - 2 * m                    # knob 지름
        x = (W - m - d) if on else m     # 켜지면 오른쪽, 꺼지면 왼쪽
        dr.ellipse([x, m, x + d, m + d], fill=knob)
        img = img.resize((self.W, self.H), Image.LANCZOS)
        return ImageTk.PhotoImage(img)

    def _render(self):
        key = (bool(self.var.get()), self.enabled)
        if key not in self._imgs:
            self._imgs[key] = self._build_image(*key)
        self.widget.config(image=self._imgs[key])

    def set_enabled(self, on: bool):
        self.enabled = bool(on)
        self.widget.config(cursor=("hand2" if on else "arrow"))
        self._render()

    def _toggle(self, e):
        if self.enabled:
            self.var.set(not bool(self.var.get()))


class RoundButton:
    """둥근(pill) 모서리의 플랫 버튼. Canvas 에 라운드 사각형 + 네이티브 텍스트.

    tk.Button 은 모서리를 둥글릴 수 없어, 라운드 배경은 Canvas 로 그리고
    한글 텍스트는 Canvas text 로(선명) 올린다. 호버 시 배경색만 바뀐다.
    set_text / set_state 로 라벨·색을 나중에 바꿀 수 있다(요일 버튼 등).
    """

    def __init__(self, parent, text, command, *, fg, fill, hover, bg,
                 font=(FONT, 10, "bold"), padx=16, pady=7, radius=11):
        self.command = command
        self.fg, self.fill, self.hover, self.bg = fg, fill, hover, bg
        self.padx, self.pady, self.radius = padx, pady, radius
        self.font = font
        self._text = text
        weight = "bold" if (len(font) > 2 and font[2] == "bold") else "normal"
        self._fnt = tkfont.Font(family=font[0], size=font[1], weight=weight)
        self.canvas = tk.Canvas(parent, bg=bg, highlightthickness=0, bd=0, cursor="hand2")
        self._draw(self.fill)
        self.canvas.bind("<Button-1>", lambda e: self.command() if self.command else None)
        self.canvas.bind("<Enter>", lambda e: self._draw(self.hover))
        self.canvas.bind("<Leave>", lambda e: self._draw(self.fill))

    def _round(self, x0, y0, x1, y1, r, **kw):
        pts = [
            x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r,
            x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1,
            x0, y1, x0, y1 - r, x0, y0 + r, x0, y0,
        ]
        return self.canvas.create_polygon(pts, smooth=True, **kw)

    def _draw(self, fill):
        c = self.canvas
        c.delete("all")
        lines = self._text.split("\n")
        tw = max(self._fnt.measure(ln) for ln in lines)
        lh = self._fnt.metrics("linespace")
        w = tw + self.padx * 2
        h = lh * len(lines) + self.pady * 2
        c.configure(width=w, height=h)
        self._round(0, 0, w, h, self.radius, fill=fill, outline="")
        c.create_text(
            w / 2, h / 2, text=self._text, fill=self.fg,
            font=self.font, justify="center",
        )

    def set_text(self, text):
        if text != self._text:
            self._text = text
            self._draw(self.fill)

    def set_state(self, *, fill, fg, hover):
        self.fill, self.fg, self.hover = fill, fg, hover
        self._draw(fill)


class Dashboard:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("업무시간 현황")
        self.root.configure(bg=BG)

        self._build_tabs()
        self._build_dashboard(self.dash_frame)
        self._build_settings(self.settings_frame)
        self._show_tab("dash")
        self._refresh()

        # 내용에 맞춰 창 크기를 자동 산정 (글자 잘림 방지)
        self.root.update_idletasks()
        w = max(540, self.root.winfo_reqwidth())
        h = self.root.winfo_reqheight()
        self.root.geometry(f"{w}x{h}")
        self.root.minsize(w, h)

        # 화면 중앙에 배치
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.root.geometry(f"+{(sw - w) // 2}+{max(0, (sh - h) // 2 - 40)}")

        # 열릴 때 잠깐 맨 앞으로
        self.root.attributes("-topmost", True)
        self.root.after(800, lambda: self.root.attributes("-topmost", False))

        self.root.after(REFRESH_MS, self._tick)

    # ----- 위젯 헬퍼 -----
    def _label(self, parent, text="", *, fg=FG, size=11, bold=False, bg=CARD):
        f = (FONT, size, "bold") if bold else (FONT, size)
        return tk.Label(parent, text=text, fg=fg, bg=bg, font=f, anchor="w")

    def _card(self, parent, pad=12):
        c = tk.Frame(
            parent, bg=CARD,
            highlightthickness=1, highlightbackground=BORDER, highlightcolor=BORDER,
        )
        c.pack(fill="x", pady=(0, 10))
        inner = tk.Frame(c, bg=CARD)
        inner.pack(fill="x", padx=pad, pady=pad)
        return inner

    # ----- 탭바 (현황 / 설정) : 라운드 세그먼트 -----
    def _build_tabs(self):
        bar = tk.Frame(self.root, bg=BG)
        bar.pack(fill="x", padx=18, pady=(16, 2))
        self._tab_btns = {}
        for key, label in [("dash", "현황"), ("settings", "설정")]:
            rb = RoundButton(
                bar, label, lambda k=key: self._show_tab(k),
                fg=SUB, fill=BG, hover=HOVER, bg=BG,
                font=(FONT, 11, "bold"), padx=18, pady=7, radius=13,
            )
            rb.canvas.pack(side="left", padx=(0, 4))
            self._tab_btns[key] = rb

        # 탭 내용 컨테이너 + 두 프레임 (한 번만 생성, pack/forget 로 전환)
        self.container = tk.Frame(self.root, bg=BG)
        self.container.pack(fill="both", expand=True)
        self.dash_frame = tk.Frame(self.container, bg=BG)
        self.settings_frame = tk.Frame(self.container, bg=BG)

    def _show_tab(self, key):
        self.dash_frame.pack_forget()
        self.settings_frame.pack_forget()
        frame = self.dash_frame if key == "dash" else self.settings_frame
        frame.pack(fill="both", expand=True)
        for k, rb in self._tab_btns.items():
            if k == key:
                rb.set_state(fill=CARD, fg=ACCENT, hover=CARD)
            else:
                rb.set_state(fill=BG, fg=SUB, hover=HOVER)

    # ----- 현황 레이아웃 1회 생성 -----
    def _build_dashboard(self, parent):
        root = tk.Frame(parent, bg=BG)
        root.pack(fill="both", expand=True, padx=16, pady=10)

        # 헤더
        head = tk.Frame(root, bg=BG)
        head.pack(fill="x", pady=(0, 8))
        self.lbl_date = self._label(head, fg=FG, size=13, bold=True, bg=BG)
        self.lbl_date.pack(side="left")
        self.lbl_status = self._label(head, fg=GOOD, size=10, bold=True, bg=BG)
        self.lbl_status.pack(side="right")

        # 오늘 카드
        card = self._card(root)
        self._label(card, "오늘 실 업무시간", fg=SUB, size=9).pack(anchor="w")
        self.lbl_today = self._label(card, fg=ACCENT, size=22, bold=True)
        self.lbl_today.pack(anchor="w", pady=(1, 6))

        row = tk.Frame(card, bg=CARD)
        row.pack(fill="x")
        self.today_cells = {}
        for i, key in enumerate(["출근", "최근 활동", "체류시간", "비업무"]):
            cell = tk.Frame(row, bg=CARD)
            cell.grid(row=0, column=i, sticky="w", padx=(0, 18))
            self._label(cell, key, fg=SUB, size=9).pack(anchor="w")
            col = SUB if key == "비업무" else FG
            val = self._label(cell, fg=col, size=12, bold=True)
            val.pack(anchor="w")
            self.today_cells[key] = val

        # 비업무시간 수기 보정 (오늘)
        self._build_adjust(card)

        # 주간 카드
        wcard = self._card(root)
        self.lbl_week_range = self._label(wcard, fg=SUB, size=10)
        self.lbl_week_range.pack(anchor="w", pady=(0, 8))

        self.chart = tk.Canvas(
            wcard, bg=CARD, highlightthickness=0,
            width=CHART_W, height=WEEKDAYS_SHOWN * ROW_H + 6,
        )
        self.chart.pack(fill="x")
        # 평일(월~금)치 캔버스 아이템을 미리 생성하고 id 보관 → 갱신 시 좌표/텍스트만 수정
        self.bars = []
        for i in range(WEEKDAYS_SHOWN):
            y = i * ROW_H + 14
            day_id = self.chart.create_text(
                4, y, text="", fill=SUB, font=(FONT, 9), anchor="w"
            )
            self.chart.create_rectangle(
                BAR_X0, y - 8, BAR_X0 + BAR_MAX, y + 8, fill=CARD2, outline=""
            )
            bar_id = self.chart.create_rectangle(
                BAR_X0, y - 8, BAR_X0, y + 8, fill=ACCENT, outline=""
            )
            val_id = self.chart.create_text(
                BAR_X0 + BAR_MAX + 6, y, text="", fill=FG, font=(FONT, 9), anchor="w"
            )
            self.bars.append((day_id, bar_id, val_id, y))

        # 휴가 · 출장 표시 (접기/펴기)
        self._build_leave(wcard)

        # 합계 카드
        foot = self._card(root)
        frow = tk.Frame(foot, bg=CARD)
        frow.pack(fill="x")
        self.foot_cells = {}
        for i, (key, col) in enumerate([("주간 합계", GOOD), ("근무일 평균", FG)]):
            cell = tk.Frame(frow, bg=CARD)
            cell.grid(row=0, column=i, sticky="w", padx=(0, 40))
            self._label(cell, key, fg=SUB, size=9).pack(anchor="w")
            val = self._label(cell, fg=col, size=13, bold=True)
            val.pack(anchor="w")
            self.foot_cells[key] = val

        self.lbl_refresh = self._label(root, fg=SUB, size=8, bg=BG)
        self.lbl_refresh.pack(anchor="e", pady=(4, 0))

    # ----- 접었다 폈다 하는 섹션 공통 헬퍼 -----
    def _collapsible(self, card, title, build_body):
        """버튼처럼 보이는 토글 바 + 접히는 본문을 만든다.

        build_body(body) 로 본문을 채우고, 바 오른쪽 값 라벨(extra)을 돌려준다.
        """
        sep = tk.Frame(card, bg=CARD2, height=1)
        sep.pack(fill="x", pady=(8, 8))

        bar = tk.Frame(card, bg=CARD2, cursor="hand2")
        bar.pack(fill="x")
        inner = tk.Frame(bar, bg=CARD2)
        inner.pack(fill="x", padx=12, pady=8)
        caret = tk.Label(inner, text="▼", font=(FONT, 11, "bold"), bg=CARD2, fg=ACCENT)
        caret.pack(side="left", padx=(0, 9))
        tk.Label(
            inner, text=title, font=(FONT, 10, "bold"), bg=CARD2, fg=FG
        ).pack(side="left")
        action = tk.Label(
            inner, text="펼치기", font=(FONT, 9, "bold"), bg=CARD2, fg=ACCENT
        )
        action.pack(side="right")
        extra = tk.Label(inner, text="", font=(FONT, 9, "bold"), bg=CARD2, fg=TODAY)
        extra.pack(side="right", padx=(0, 12))

        body = tk.Frame(card, bg=CARD)
        build_body(body)

        widgets = [bar, inner] + list(inner.winfo_children())
        state = {"open": False}

        def toggle(_e=None):
            state["open"] = not state["open"]
            if state["open"]:
                body.pack(fill="x")
                caret.config(text="▲")
                action.config(text="접기")
            else:
                body.pack_forget()
                caret.config(text="▼")
                action.config(text="펼치기")
            self._refit_height()

        def hover(on):
            c = HOVER if on else CARD2
            for w in widgets:
                try:
                    w.config(bg=c)
                except tk.TclError:
                    pass

        for w in widgets:
            w.bind("<Button-1>", toggle)
            w.bind("<Enter>", lambda e: hover(True))
            w.bind("<Leave>", lambda e: hover(False))
        return extra, toggle

    # ----- 비업무시간 수기 보정 -----
    def _build_adjust(self, card):
        self.lbl_adjust, self._adjust_toggle = self._collapsible(
            card, "비업무시간 수기 보정", self._build_adjust_body
        )

    def _build_adjust_body(self, body):
        ctl = tk.Frame(body, bg=CARD)
        ctl.pack(fill="x", pady=(10, 0))
        self.adjust_stepper = Stepper(ctl, value=10, lo=1, hi=600)
        self.adjust_stepper.frame.pack(side="left")
        self._label(ctl, "분", fg=SUB, size=9).pack(side="left", padx=(6, 10))
        self._adj_btn(ctl, "− 비업무 빼기", lambda: self._apply_adjust(-1), ACCENT)
        self._adj_btn(ctl, "＋ 비업무 추가", lambda: self._apply_adjust(+1), TODAY)
        self._adj_btn(ctl, "초기화", self._reset_adjust, SUB)
        self._label(
            body, "뺄 수 있는 한도 = 비업무 시간, 더할 수 있는 한도 = 실 업무 시간.",
            fg=SUB, size=8,
        ).pack(anchor="w", pady=(6, 0))

    # ----- 휴가 · 출장 표시 -----
    def _build_leave(self, card):
        _, self._leave_toggle = self._collapsible(
            card, "휴가 · 출장 표시", self._build_leave_body
        )

    def _build_leave_body(self, body):
        self._label(
            body, "요일을 누를 때마다  근무 → 휴가 → 출장  순으로 바뀝니다. "
            "표시한 날은 8시간으로 채워집니다.",
            fg=SUB, size=8,
        ).pack(anchor="w", pady=(10, 6))
        row = tk.Frame(body, bg=CARD)
        row.pack(fill="x")
        self.leave_btns = []
        for i in range(WEEKDAYS_SHOWN):
            rb = RoundButton(
                row, " ", lambda i=i: self._cycle_leave(i),
                fg=FG, fill=CARD2, hover=HOVER, bg=CARD,
                font=(FONT, 9, "bold"), padx=10, pady=7, radius=10,
            )
            rb.canvas.pack(side="left", padx=(0, 6))
            self.leave_btns.append(rb)

    def _cycle_leave(self, i):
        monday, _ = S.week_range(date.today())
        d = monday + timedelta(days=i)
        order = [None, "vacation", "trip"]
        st = S.Storage()
        try:
            cur = st.get_leave(d)
            nxt = order[(order.index(cur) + 1) % len(order)]
            st.set_leave(d, nxt)
        finally:
            st.close()
        self._refresh()

    def _refit_height(self):
        """접기/펴기로 내용 높이가 바뀌면 창 높이를 다시 맞춘다."""
        self.root.update_idletasks()
        rw = max(540, self.root.winfo_reqwidth())
        w = max(self.root.winfo_width(), rw)
        h = self.root.winfo_reqheight()
        self.root.geometry(f"{w}x{h}")
        self.root.minsize(rw, h)

    def _adj_btn(self, parent, text, cmd, fg):
        rb = RoundButton(
            parent, text, cmd, fg=fg, fill=CARD2, hover=HOVER, bg=CARD,
            font=(FONT, 9, "bold"), padx=13, pady=5, radius=9,
        )
        rb.canvas.pack(side="left", padx=(0, 6))
        return rb

    @staticmethod
    def _fmt_adjust(sec: int) -> str:
        if sec == 0:
            return "없음"
        sign = "＋" if sec > 0 else "−"
        return f"{sign}{S.fmt_hm(abs(sec))}"

    def _apply_adjust(self, sign: int):
        minutes = self.adjust_stepper.value()
        delta = sign * minutes * 60
        today = date.today()
        st = S.Storage()
        try:
            ivs = st.intervals()
            base_work = S.seconds_for_day(ivs, today)
            stay = S.stay_seconds(ivs, today)
            base_nonwork = max(0.0, stay - base_work)
            # 비업무 = base_nonwork + adjust 가 [0, 체류] 안에 머물도록 보정값 제한.
            #   ⇒ adjust ∈ [-비업무(다 뺄 수 있는 한도), +실업무(다 더할 수 있는 한도)]
            lo = -int(round(base_nonwork))
            hi = int(round(base_work))
            new = max(lo, min(hi, st.get_adjust_seconds(today) + delta))
            st.set_adjust_seconds(today, new)
        finally:
            st.close()
        self._refresh()

    def _reset_adjust(self):
        st = S.Storage()
        try:
            st.set_adjust_seconds(date.today(), 0)
        finally:
            st.close()
        self._refresh()

    # ----- 설정 레이아웃 -----
    def _build_settings(self, parent):
        root = tk.Frame(parent, bg=BG)
        root.pack(fill="both", expand=True, padx=16, pady=10)

        self._label(
            root, "시간 카운팅 방식", fg=FG, size=13, bold=True, bg=BG
        ).pack(anchor="w", pady=(0, 3))
        self._label(
            root, "각 방식을 켜면 해당 상황에서 업무시간 카운팅을 멈춥니다.",
            fg=SUB, size=9, bg=BG,
        ).pack(anchor="w", pady=(0, 8))

        cur = self._read_settings()
        self.var_idle = tk.BooleanVar(value=cur["idle_enabled"])
        self.var_lock = tk.BooleanVar(value=cur["lock_enabled"])
        self.var_ss = tk.BooleanVar(value=cur["screensaver_enabled"])
        self._editing = False
        self.toggles = []

        # 자리비움 카드 (체크 + 시간 조절)
        idle_card = self._card(root)
        self._setting_check(
            idle_card, self.var_idle, "자리비움(미입력) 감지",
            "키보드/마우스 입력이 일정 시간 없으면 자리비움으로 보고 멈춥니다.",
        )
        trow = tk.Frame(idle_card, bg=CARD)
        trow.pack(fill="x", pady=(8, 0))
        self._label(trow, "기준 시간", fg=SUB, size=10).pack(side="left", padx=(0, 10))
        self.idle_stepper = Stepper(
            trow, value=max(1, round(cur["idle_threshold_sec"] / 60)),
            lo=1, hi=600,
        )
        self.idle_stepper.frame.pack(side="left")
        self._label(
            trow, "분 동안 입력 없으면 멈춤", fg=SUB, size=10
        ).pack(side="left", padx=(8, 0))

        # 화면 잠금 카드
        lock_card = self._card(root)
        self._setting_check(
            lock_card, self.var_lock, "화면 잠금 감지",
            "Win+L 등으로 화면을 잠그면 멈춥니다.",
        )

        # 화면보호기 카드
        ss_card = self._card(root)
        self._setting_check(
            ss_card, self.var_ss, "화면보호기 감지",
            "화면보호기가 작동하면 멈춥니다.",
        )

        # 편집 / 저장 / 취소 버튼 바
        btnbar = tk.Frame(root, bg=BG)
        btnbar.pack(fill="x", pady=(6, 0))
        self.btn_edit = self._settings_btn(
            btnbar, "편집", self._enter_edit, fill=ACCENT, fg="#FFFFFF", hover="#4A4AC4"
        )
        self.btn_save = self._settings_btn(
            btnbar, "저장", self._save_edit, fill=GOOD, fg="#FFFFFF", hover="#27875B"
        )
        self.btn_cancel = self._settings_btn(
            btnbar, "취소", self._cancel_edit, fill=CARD2, fg=SUB, hover=HOVER
        )
        self.lbl_saved = self._label(btnbar, fg=SUB, size=9, bg=BG)
        self.lbl_saved.pack(side="right")

        # 자리비움 토글을 끄면 기준 시간 입력칸도 같이 비활성화 (편집 중에만 의미)
        self.var_idle.trace_add("write", lambda *a: self._sync_idle_state())
        self._set_edit_mode(False)   # 시작은 잠금 상태

    def _settings_btn(self, parent, text, cmd, *, fill, fg, hover):
        return RoundButton(
            parent, text, cmd, fg=fg, fill=fill, hover=hover, bg=BG,
            font=(FONT, 10, "bold"), padx=18, pady=6, radius=11,
        )

    def _setting_check(self, card, var, title, desc):
        top = tk.Frame(card, bg=CARD)
        top.pack(fill="x")
        self._label(top, title, fg=FG, size=11, bold=True).pack(side="left")
        sw = ToggleSwitch(top, var, bg=CARD)
        sw.widget.pack(side="right")
        self.toggles.append(sw)
        self._label(card, desc, fg=SUB, size=9).pack(anchor="w", pady=(2, 0))

    # ----- 편집 모드 제어 -----
    def _set_edit_mode(self, editing: bool):
        self._editing = editing
        for sw in self.toggles:
            sw.set_enabled(editing)
        self._sync_idle_state()
        if editing:
            self.btn_edit.canvas.pack_forget()
            self.btn_save.canvas.pack(side="left", padx=(0, 6))
            self.btn_cancel.canvas.pack(side="left")
        else:
            self.btn_save.canvas.pack_forget()
            self.btn_cancel.canvas.pack_forget()
            self.btn_edit.canvas.pack(side="left")

    def _enter_edit(self):
        # 취소 대비 현재(저장된) 값 스냅샷
        self._snapshot = {
            "idle": self.var_idle.get(),
            "lock": self.var_lock.get(),
            "ss": self.var_ss.get(),
            "min": self.idle_stepper.value(),
        }
        self._set_edit_mode(True)
        self.lbl_saved.config(text="편집 중…", fg=ACCENT)

    def _cancel_edit(self):
        s = self._snapshot
        self.var_idle.set(s["idle"])
        self.var_lock.set(s["lock"])
        self.var_ss.set(s["ss"])
        self.idle_stepper.set(s["min"])
        self._set_edit_mode(False)
        self.lbl_saved.config(text="변경 취소됨", fg=SUB)

    def _save_edit(self):
        self._save_settings()
        self._set_edit_mode(False)

    def _sync_idle_state(self):
        """편집 중이고 자리비움이 켜져 있을 때만 기준 시간 입력칸 활성화."""
        self.idle_stepper.set_enabled(self._editing and bool(self.var_idle.get()))

    def _read_settings(self):
        st = S.Storage()
        try:
            return st.get_settings()
        finally:
            st.close()

    def _save_settings(self):
        minutes = self.idle_stepper.value()   # 이미 [1, 600] 으로 클램프됨
        st = S.Storage()
        try:
            st.set_setting("idle_enabled", bool(self.var_idle.get()))
            st.set_setting("idle_threshold_sec", minutes * 60)
            st.set_setting("lock_enabled", bool(self.var_lock.get()))
            st.set_setting("screensaver_enabled", bool(self.var_ss.get()))
        finally:
            st.close()
        self.lbl_saved.config(text=f"저장됨 · {datetime.now():%H:%M:%S}", fg=GOOD)

    # ----- 데이터 -----
    def _load(self):
        st = S.Storage()
        try:
            ivs = st.intervals()
            last = st.last_event()
            today = date.today()
            monday, _ = S.week_range(today)
            days = [monday + timedelta(days=i) for i in range(WEEKDAYS_SHOWN)]
            adjusts = {d: st.get_adjust_seconds(d) for d in days}
            leaves = {d: st.get_leave(d) for d in days}
            # 오늘이 주말이면 days 에 없으므로 오늘 값도 따로 챙긴다 (오늘 카드용)
            adjusts.setdefault(today, st.get_adjust_seconds(today))
            leaves.setdefault(today, st.get_leave(today))
            return ivs, last, adjusts, leaves
        finally:
            st.close()

    def _status(self, last):
        if last is None:
            return "기록 없음", SUB
        if last["kind"] == "start":
            return "● 업무 중", GOOD
        return "■ 일시정지 / 종료", SUB

    # ----- 값만 갱신 (깜빡임 없음) -----
    def _refresh(self):
        ivs, last, adjusts, leaves = self._load()
        today = date.today()

        self.lbl_date.config(
            text=f"{today:%Y년 %m월 %d일} ({WEEKDAY[today.weekday()]})"
        )
        stxt, scol = self._status(last)
        self.lbl_status.config(text=stxt, fg=scol)

        today_adj = adjusts.get(today, 0)
        today_leave = leaves.get(today)
        today_work, today_nonwork = S.split_for_day(ivs, today, today_adj, today_leave)
        first, lastt = S.day_bounds(ivs, today)
        self.lbl_today.config(text=S.fmt_hm(today_work))
        self.today_cells["출근"].config(text=f"{first:%H:%M}" if first else "--:--")
        self.today_cells["최근 활동"].config(text=f"{lastt:%H:%M}" if lastt else "--:--")
        self.today_cells["체류시간"].config(
            text=S.fmt_hm((lastt - first).total_seconds()) if first else "-"
        )
        self.today_cells["비업무"].config(
            text=S.fmt_hm(today_nonwork) if first else "-"
        )
        self.lbl_adjust.config(
            text="" if today_adj == 0 else f"보정 {self._fmt_adjust(today_adj)}"
        )

        monday, _ = S.week_range(today)
        friday = monday + timedelta(days=WEEKDAYS_SHOWN - 1)
        self.lbl_week_range.config(text=f"이번 주  ({monday:%m.%d} ~ {friday:%m.%d})")

        days = [monday + timedelta(days=i) for i in range(WEEKDAYS_SHOWN)]
        day_secs = [
            S.split_for_day(ivs, d, adjusts.get(d, 0), leaves.get(d))[0]
            for d in days
        ]
        week_total = sum(day_secs)
        scale = max(WORKDAY_SCALE_SEC, max(day_secs) if day_secs else 0, 1)

        for i, (d, sec) in enumerate(zip(days, day_secs)):
            leave = leaves.get(d)
            is_today = d == today
            day_id, bar_id, val_id, y = self.bars[i]
            self.chart.itemconfig(
                day_id, text=f"{WEEKDAY[d.weekday()]} {d:%m.%d}",
                fill=(TODAY if is_today else SUB),
            )
            w = int(BAR_MAX * min(1.0, sec / scale))
            self.chart.coords(bar_id, BAR_X0, y - 8, BAR_X0 + max(w, 0), y + 8)
            if leave == "vacation":
                bar_fill = VAC
            elif leave == "trip":
                bar_fill = TRIP
            else:
                bar_fill = TODAY if is_today else ACCENT
            self.chart.itemconfig(
                bar_id, fill=bar_fill, state=("normal" if sec > 0 else "hidden"),
            )
            if leave:
                vtext, vcol = f"{S.LEAVE_LABELS[leave]} {S.fmt_hm(sec)}", bar_fill
            else:
                vtext, vcol = ("-" if sec == 0 else S.fmt_hm(sec)), (FG if sec else SUB)
            self.chart.itemconfig(val_id, text=vtext, fill=vcol)

            # 휴가/출장 버튼 라벨·색 갱신
            btn = self.leave_btns[i]
            label = f"{WEEKDAY[d.weekday()]} {d:%m.%d}"
            if leave == "vacation":
                btn.set_text(f"{label}\n휴가")
                btn.set_state(fill=VAC, fg="#FFFFFF", hover=VAC)
            elif leave == "trip":
                btn.set_text(f"{label}\n출장")
                btn.set_state(fill=TRIP, fg="#FFFFFF", hover=TRIP)
            else:
                btn.set_text(f"{label}\n근무")
                btn.set_state(fill=CARD2, fg=FG, hover=HOVER)

        worked_days = sum(1 for s in day_secs if s > 0)
        avg = week_total / worked_days if worked_days else 0
        self.foot_cells["주간 합계"].config(text=S.fmt_hm(week_total))
        self.foot_cells["근무일 평균"].config(text=S.fmt_hm(avg))

        self.lbl_refresh.config(
            text=f"자동 새로고침 · 마지막 {datetime.now():%H:%M:%S}"
        )

    def _tick(self):
        try:
            self._refresh()
        finally:
            self.root.after(REFRESH_MS, self._tick)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    Dashboard().run()
