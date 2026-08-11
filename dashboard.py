"""
dashboard.py - 업무시간 현황 GUI (tkinter, 추가 설치 불필요)

py dashboard.py        # 콘솔과 함께 실행 (디버그)
pythonw dashboard.py   # 콘솔 없이 GUI 만 (트레이 메뉴가 이 방식으로 실행)

다크 테마 카드 UI + 주간 막대그래프 + 5초 자동 새로고침.
위젯은 한 번만 생성하고 값만 갱신하므로 새로고침 시 깜빡임이 없다.
"""

import os
import subprocess
import tkinter as tk
import tkinter.font as tkfont
import tkinter.ttk as ttk
from tkinter import filedialog, messagebox
import ctypes
from ctypes import wintypes
from datetime import date, datetime, timedelta

from PIL import Image, ImageDraw, ImageTk

import storage as S
import export as EXP

# ----- 색상/폰트 테마 -----
# 톤앤매너는 같은 폴더의 "주간 업무 보드"(todo_list) 앱에서 가져왔다:
# '유칼립투스 어스톤' = 그린그레이 중성색 배경 + 흰 카드 + 틸 액센트,
# 경고는 클레이 레드/오커. 저 앱의 라이트 테마 토큰과 값이 1:1로 대응한다.
BG = "#EDF0ED"          # --bg      창 배경 (연회색-그린)
CARD = "#FFFFFF"        # --surface 카드
CARD2 = "#F5F7F5"       # --surface-2 입력란/보조 면
LINE = "#D9E0DA"        # --line    1px 테두리
HOVER = "#E7ECE8"       # 버튼/바 마우스 오버 (surface-2 보다 살짝 진하게)
FG = "#253430"          # --ink
SUB = "#68776F"         # --muted
ACCENT = "#17766B"      # --accent  틸
ACCENT_SOFT = "#E1EFEA"  # --accent-soft (칩 배경)
ACCENT_INK = "#0F5A4E"  # --accent-ink  (칩 글자)
ON_ACCENT = "#FFFFFF"   # --on-accent
TODAY = "#C0913B"       # --warn    오커 (오늘/일시정지 강조)
GOOD = "#2E6B5C"        # 저장됨 등 성공 표시 (태그 팔레트의 진한 그린)
WARN = "#BF5B4B"        # --danger  삭제 등 되돌릴 수 없는 동작
GRID = "#B4C1B7"        # 차트 8시간 기준선 (LINE 보다 진한 점선)

# 태그 파스텔 8색 (todo 앱의 --t{0-7}b/t). (배경, 글자) 쌍.
TAG_COLORS = [
    ("#DFEBDC", "#4A6B44"), ("#D8EBE4", "#2E6B5C"),
    ("#DCE7EE", "#40667F"), ("#E1E2F0", "#585A8C"),
    ("#EADFE9", "#7A5276"), ("#F0DFDD", "#8C5450"),
    ("#EFE6D6", "#85683B"), ("#E3E8E3", "#5A695F"),
]

# 토글 스위치 색
TOGGLE_ON = ACCENT       # 켜짐 트랙
TOGGLE_OFF = "#C9D2CB"   # 꺼짐 트랙
TOGGLE_KNOB = "#FFFFFF"  # knob
# 비활성(편집 잠금) 상태 색 - 흐리게
TOGGLE_ON_DIS = "#A6C6BF"
TOGGLE_OFF_DIS = "#E2E7E3"
TOGGLE_KNOB_DIS = "#F4F6F4"

# 근무/출장/휴가/반차 색 (막대·요일 버튼 공용).
# 넷이 한눈에 구분되도록 색상(hue)을 일부러 벌려 놓았다: 근무=틸, 출장=파랑,
# 휴가=앰버, 반차=마젠타. 파스텔 톤은 유지하되 채도를 조금 올려 구분을 살린다.
# (예전엔 청회색/인디고/자주라 셋 다 비슷해 보였다.)
BAR_WORK = "#7FA79B"     # 근무 (지난 날) - 가라앉은 틸
BAR_TODAY = ACCENT       # 근무 (오늘) - 액센트 틸
TRIP = "#3D6E96"         # 출장 - 파랑
VAC = "#B07C22"          # 휴가 - 앰버
HALF = "#9B4F80"         # 반차 - 마젠타
LEAVE_COLORS = {"trip": TRIP, "vacation": VAC, "halfday": HALF}
# 요일 버튼용 연한 배경 (같은 색상의 파스텔)
LEAVE_SOFT = {"trip": "#D5E5F3", "vacation": "#F7E7C4", "halfday": "#F5DCEC"}

# 비업무 목록의 방식별 색 (태그 팔레트와 같은 톤)
NW_PAUSE = "#4A6B44"     # 수동 일시정지 - 그린
NW_MANUAL = "#5A695F"    # 수기 추가 - 그레이그린

WEEKDAYS_SHOWN = 5       # 주간 표시 일수 (월~금, 토·일 제외)

FONT = "맑은 고딕"
WEEKDAY = ["월", "화", "수", "목", "금", "토", "일"]

REFRESH_MS = 5000
WORKDAY_SCALE_SEC = 8 * 3600  # 막대 길이 기준 (8시간)

BAR_X0 = 60       # 막대 시작 x (요일 라벨 영역 다음)
BAR_MAX = 300     # 막대 최대 길이
BAR_H = 14        # 막대/트랙 높이
BAR_R = 5         # 막대 모서리 라운드
VAL_W = 96        # 막대 오른쪽 시간 숫자 영역
CHART_W = BAR_X0 + BAR_MAX + VAL_W
ROW_H = 26

NW_LIST_MAX_H = 300     # 비업무 목록 최대 표시 높이(px). 넘으면 스크롤(행 약 9개 분량)

# 카운팅 중인데 하트비트(last_active)가 이보다 오래됐으면 트레이 앱이 멈춘 것으로 본다.
# 트레이 앱은 HEARTBEAT_SEC(10초)마다 기록하므로 넉넉한 여유를 둔 값.
STALE_SEC = 120

# 창을 화면(작업 영역) 안에 붙잡아 두기 위한 어림값(px).
# 창 바깥 높이 = 내용 높이 + 타이틀바 + 테두리 이므로, 내용 높이 상한은
# 화면 높이 − (타이틀바+테두리+작업표시줄) = screenheight − MAX_H_MARGIN.
TITLEBAR_H = 39          # 타이틀바 + 테두리
TASKBAR_H = 48
MAX_H_MARGIN = TITLEBAR_H + TASKBAR_H + 1


class _LOGFONTW(ctypes.Structure):
    _fields_ = [
        ("lfHeight", wintypes.LONG), ("lfWidth", wintypes.LONG),
        ("lfEscapement", wintypes.LONG), ("lfOrientation", wintypes.LONG),
        ("lfWeight", wintypes.LONG), ("lfItalic", wintypes.BYTE),
        ("lfUnderline", wintypes.BYTE), ("lfStrikeOut", wintypes.BYTE),
        ("lfCharSet", wintypes.BYTE), ("lfOutPrecision", wintypes.BYTE),
        ("lfClipPrecision", wintypes.BYTE), ("lfQuality", wintypes.BYTE),
        ("lfPitchAndFamily", wintypes.BYTE), ("lfFaceName", ctypes.c_wchar * 32),
    ]


try:
    _IMM32 = ctypes.windll.imm32
    _USER32 = ctypes.windll.user32
    _IMM32.ImmGetContext.restype = wintypes.HANDLE
    _IMM32.ImmGetContext.argtypes = [wintypes.HWND]
    _IMM32.ImmReleaseContext.argtypes = [wintypes.HWND, wintypes.HANDLE]
    _IMM32.ImmSetCompositionFontW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_LOGFONTW)]
    _USER32.GetFocus.restype = wintypes.HWND
except Exception:
    _IMM32 = None
    _USER32 = None


def set_ime_composition_font(family: str, px: int):
    """현재 키보드 포커스를 가진 창의 IME 조합 글자 폰트를 맞춘다.

    Tk 는 Windows 에서 위젯마다 자식 HWND 를 만들고 IME 조합은 그 '포커스 창'에
    붙으므로, 최상위 창이 아니라 GetFocus() 로 얻은 실제 포커스 창에 적용해야 한다.
    한글 조합 글자가 거대하게 그려졌다 확정되면 작아지는 증상을 막는다. 실패는 무시.
    """
    if _IMM32 is None or _USER32 is None:
        return
    try:
        hwnd = _USER32.GetFocus()
        if not hwnd:
            return
        himc = _IMM32.ImmGetContext(hwnd)
        if not himc:
            return
        try:
            lf = _LOGFONTW()
            lf.lfHeight = -abs(int(px))   # 음수 = 문자 높이(px)
            lf.lfWeight = 400
            lf.lfCharSet = 129            # HANGEUL_CHARSET
            lf.lfFaceName = family[:31]
            _IMM32.ImmSetCompositionFontW(himc, ctypes.byref(lf))
        finally:
            _IMM32.ImmReleaseContext(hwnd, himc)
    except Exception:
        pass


_ROUND_CACHE = {}
_FONT_CACHE = {}
ROUND_CACHE_MAX = 600


def _font(spec):
    """폰트 튜플 → 측정용 tkfont.Font (캐시)."""
    f = _FONT_CACHE.get(spec)
    if f is None:
        f = tkfont.Font(font=spec)
        _FONT_CACHE[spec] = f
    return f


def round_img(w, h, radius, fill, outline=None, bg=BG, bw=1):
    """모서리가 둥근 사각형 이미지 (버튼/칩 배경용, 캐시).

    tk 위젯에는 radius 가 없어서, todo 앱의 8~99px 둥근 버튼/알약 칩을 흉내내려면
    배경을 이미지로 깔고 그 위에 글자를 얹어야 한다(Label 의 compound='center').
    Canvas 는 안티앨리어싱이 없으므로 4배로 그린 뒤 LANCZOS 로 줄인다.
    """
    key = (w, h, radius, fill, outline, bg, bw)
    img = _ROUND_CACHE.get(key)
    if img is None:
        # 주간 차트 막대는 길이가 바뀔 때마다 새 이미지가 되므로 캐시가 계속 는다.
        # 한도를 넘으면 통째로 비운다 — 화면에 떠 있는 이미지는 위젯 쪽에서
        # 따로 참조를 붙들고 있어(Pill._img, Dashboard._bar_imgs) 안전하다.
        if len(_ROUND_CACHE) > ROUND_CACHE_MAX:
            _ROUND_CACHE.clear()
        ss = 4
        im = Image.new("RGB", (w * ss, h * ss), bg)
        dr = ImageDraw.Draw(im)
        r = min(radius, min(w, h) / 2) * ss
        dr.rounded_rectangle(
            [0, 0, w * ss - 1, h * ss - 1], radius=r, fill=fill,
            outline=outline, width=(bw * ss if outline else 0),
        )
        img = ImageTk.PhotoImage(im.resize((w, h), Image.LANCZOS))
        _ROUND_CACHE[key] = img
    return img


class Pill(tk.Label):
    """둥근 버튼 / 알약 칩 (todo 앱의 `.btn`·`.tag` 대응).

    tk.Label 을 상속하므로 pack/grid/bind/state 는 기존 버튼과 똑같이 쓴다.
    배경(둥근 사각형)은 이미지, 글자는 tk 가 그 위에 그린다.
    """

    def __init__(self, parent, text="", *, font=(FONT, 9, "bold"), fg=FG,
                 fill=CARD, outline=LINE, radius=8, padx=12, pady=5,
                 bg=BG, cmd=None, hover_fill=HOVER, min_w=0):
        super().__init__(
            parent, bg=bg, bd=0, highlightthickness=0, compound="center",
            font=font, fg=fg, disabledforeground=SUB,
            cursor=("hand2" if cmd else "arrow"),
        )
        self._font_spec = font
        self._fg, self._fill, self._outline = fg, fill, outline
        self._radius, self._padx, self._pady = radius, padx, pady
        self._bg, self._hover_fill, self._min_w = bg, hover_fill, min_w
        self._text = text
        self._cmd = cmd
        if cmd:
            self.bind("<Button-1>", self._on_click)
        self.bind("<Enter>", lambda e: self._paint(True))
        self.bind("<Leave>", lambda e: self._paint(False))
        self._paint(False)

    # ----- 내부 -----
    def _disabled(self):
        return str(self["state"]) == "disabled"

    def _on_click(self, _e):
        if self._cmd and not self._disabled():
            self._cmd()

    def _paint(self, hover: bool):
        f = _font(self._font_spec)
        lines = str(self._text).split("\n")
        w = max(self._min_w, max(f.measure(t) for t in lines) + 2 * self._padx)
        h = f.metrics("linespace") * len(lines) + 2 * self._pady
        fill = self._hover_fill if (hover and self._hover_fill and
                                    self._cmd and not self._disabled()) else self._fill
        self._img = round_img(w, h, self._radius, fill, self._outline, self._bg)
        self.config(image=self._img, text=self._text, fg=self._fg)

    # ----- 외부 -----
    def set_text(self, text):
        self._text = text
        self._paint(False)

    def set_style(self, *, fg=None, fill=None, outline=False, text=None):
        """색만 바꿔 다시 그린다 (탭 선택, 태그 선택 등). outline=False 는 '유지'."""
        if fg is not None:
            self._fg = fg
        if fill is not None:
            self._fill = fill
        if outline is not False:
            self._outline = outline
        if text is not None:
            self._text = text
        self._paint(False)


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
            bg=CARD2, fg=FG, disabledbackground=CARD2, disabledforeground=SUB,
            relief="flat", bd=0, insertbackground=FG,
            insertofftime=0,   # 커서 깜박임 제거 (고정 커서)
            highlightthickness=1, highlightbackground=LINE, highlightcolor=ACCENT,
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
            self.frame, text=text, command=cmd, font=(FONT, 10, "bold"),
            width=1, bg=CARD2, fg=SUB,
            activebackground=HOVER, activeforeground=ACCENT,
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
        # 스위치 이미지 + 추가로 등록된 클릭 영역(제목/설명 등)을 모두 클릭 대상으로
        self._targets = [self.widget]
        self.widget.bind("<Button-1>", self._toggle)
        self.var.trace_add("write", lambda *a: self._render())
        self._render()

    def add_target(self, widget):
        """제목/설명 같은 위젯도 눌러서 토글할 수 있게 클릭 영역으로 등록한다.

        작은 스위치 이미지만 누를 수 있어 끄려다 빗나가는 문제를 막는다.
        """
        widget.bind("<Button-1>", self._toggle)
        widget.config(cursor=("hand2" if self.enabled else "arrow"))
        self._targets.append(widget)

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
        cursor = "hand2" if on else "arrow"
        for w in self._targets:
            w.config(cursor=cursor)
        self._render()

    def _toggle(self, e):
        if self.enabled:
            self.var.set(not bool(self.var.get()))


class Dashboard:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("업무시간 현황")
        self.root.configure(bg=BG)
        self._set_window_icon()

        self._build_tabs()
        self._build_dashboard(self.dash_frame)
        self._build_nonwork(self.nonwork_frame)
        self._build_settings(self.settings_frame)
        self._show_tab("dash")
        self._refresh()
        self._refresh_nonwork()

        # 내용에 맞춰 창 크기를 자동 산정 (글자 잘림 방지)
        self.root.update_idletasks()
        w = max(540, self.root.winfo_reqwidth())
        # 화면(작업 영역) 밖으로 나가지 않게 높이 상한
        h = min(self.root.winfo_reqheight(),
                self.root.winfo_screenheight() - MAX_H_MARGIN)
        self.root.geometry(f"{w}x{h}")
        self.root.minsize(w, h)

        # 화면 중앙에 배치
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.root.geometry(f"+{(sw - w) // 2}+{max(0, (sh - h) // 2 - 40)}")

        # 다크 테마와 어울리도록 타이틀바도 어둡게
        self._apply_dark_titlebar()

        # 열릴 때 잠깐 맨 앞으로
        self.root.attributes("-topmost", True)
        self.root.after(800, lambda: self.root.attributes("-topmost", False))

        self.root.after(REFRESH_MS, self._tick)

    # ----- 창 아이콘 / 타이틀바 (Windows) -----
    def _set_window_icon(self):
        """창 아이콘: 라이트 테마에 맞춘 틸 원 + 흰 시계 바늘."""
        try:
            img = Image.new("RGB", (64, 64), (237, 240, 237))   # BG
            d = ImageDraw.Draw(img)
            d.ellipse((4, 4, 60, 60), fill=(23, 118, 107))      # ACCENT
            d.line((32, 32, 32, 15), fill=(255, 255, 255), width=4)   # 시계 바늘
            d.line((32, 32, 45, 39), fill=(255, 255, 255), width=4)
            self._icon_img = ImageTk.PhotoImage(img)   # GC 방지용 참조 보관
            self.root.iconphoto(True, self._icon_img)
        except Exception:
            pass

    def _apply_dark_titlebar(self):
        """타이틀바를 라이트로 고정 (Win11 22621: 속성 20 = 다크모드 on/off).

        본문이 밝은 테마이므로, OS 가 다크 모드여도 타이틀바만 어둡게 뜨지
        않도록 0(=off)을 명시한다.
        """
        try:
            self.root.update_idletasks()
            # tk 위젯 HWND 의 부모가 실제 최상위 창
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            val = ctypes.c_int(0)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 20, ctypes.byref(val), ctypes.sizeof(val)
            )
            # 적용이 즉시 반영 안 되는 경우가 있어 한 번 다시 그리게 한다
            self.root.withdraw()
            self.root.deiconify()
        except Exception:
            pass

    # ----- 위젯 헬퍼 -----
    def _label(self, parent, text="", *, fg=FG, size=11, bold=False, bg=CARD):
        f = (FONT, size, "bold") if bold else (FONT, size)
        return tk.Label(parent, text=text, fg=fg, bg=bg, font=f, anchor="w")

    def _card(self, parent, pad=10):
        """흰 면 + 1px 테두리 카드 (todo 앱의 `.col`/`.card` 대응)."""
        c = tk.Frame(
            parent, bg=CARD, highlightthickness=1,
            highlightbackground=LINE, highlightcolor=LINE,
        )
        c.pack(fill="x", pady=(0, 8))
        inner = tk.Frame(c, bg=CARD)
        inner.pack(fill="x", padx=pad, pady=pad)
        return inner

    # ----- 탭바 (현황 / 설정) -----
    def _build_tabs(self):
        bar = tk.Frame(self.root, bg=BG)
        bar.pack(fill="x", padx=18, pady=(14, 2))
        self._tab_btns = {}
        for key, label in [("dash", "현황"), ("nonwork", "비업무"), ("settings", "설정")]:
            b = Pill(
                bar, label, font=(FONT, 11, "bold"), fg=SUB,
                fill=BG, outline=None, radius=8, padx=14, pady=6,
                cmd=lambda k=key: self._show_tab(k), hover_fill=HOVER,
            )
            b.pack(side="left", padx=(0, 6))
            self._tab_btns[key] = b

        # 탭 내용 컨테이너 + 두 프레임 (한 번만 생성, pack/forget 로 전환)
        self.container = tk.Frame(self.root, bg=BG)
        self.container.pack(fill="both", expand=True)
        self.dash_frame = tk.Frame(self.container, bg=BG)
        self.nonwork_frame = tk.Frame(self.container, bg=BG)
        self.settings_frame = tk.Frame(self.container, bg=BG)

    def _show_tab(self, key):
        self.dash_frame.pack_forget()
        self.nonwork_frame.pack_forget()
        self.settings_frame.pack_forget()
        frame = {
            "dash": self.dash_frame,
            "nonwork": self.nonwork_frame,
            "settings": self.settings_frame,
        }[key]
        frame.pack(fill="both", expand=True)
        for k, b in self._tab_btns.items():
            active = (k == key)
            b.set_style(
                fg=(ACCENT_INK if active else SUB),
                fill=(ACCENT_SOFT if active else BG),
            )
        self._active_tab = key
        if key == "nonwork":
            self._refresh_nonwork()   # 탭이 보이는 순간 최신화
        # 탭마다 내용 높이가 다르므로 전환할 때마다 창 높이를 다시 맞춘다
        # (비업무 탭이 비어 줄어든 뒤 현황으로 돌아오면 잘리던 문제 해결)
        self._refit_height()

    # ----- 현황 레이아웃 1회 생성 -----
    def _build_dashboard(self, parent):
        root = tk.Frame(parent, bg=BG)
        root.pack(fill="both", expand=True, padx=16, pady=10)

        # 헤더
        head = tk.Frame(root, bg=BG)
        head.pack(fill="x", pady=(0, 8))
        self.lbl_date = self._label(head, fg=FG, size=13, bold=True, bg=BG)
        self.lbl_date.pack(side="left")
        # 상태는 todo 앱의 `.chip-now` 처럼 둥근 칩으로
        self.lbl_status = Pill(
            head, "", font=(FONT, 9, "bold"), fg=ACCENT_INK, fill=ACCENT_SOFT,
            outline=None, radius=99, padx=11, pady=3, bg=BG,
        )
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
            # nw = 위쪽 정렬. 최근 활동 칸만 상태 줄이 붙어 한 줄 더 높은데,
            # 세로 가운데 정렬('w')이면 나머지 칸이 그만큼 아래로 밀려 어긋난다.
            cell.grid(row=0, column=i, sticky="nw", padx=(0, 18))
            self._label(cell, key, fg=SUB, size=9).pack(anchor="w")
            col = SUB if key == "비업무" else FG
            val = self._label(cell, fg=col, size=12, bold=True)
            val.pack(anchor="w")
            self.today_cells[key] = val
            if key == "최근 활동":
                # 일시정지 중이면 최근 활동은 원래 멈춰 있는 값이라 '안 갱신되는'
                # 것처럼 보인다. 그 이유(또는 트레이 앱이 멈춘 상태)를 바로 아래에
                # 적어 준다. 내용이 비어도 한 줄 높이는 유지해 레이아웃이 안 흔들린다.
                self.lbl_last_note = self._label(cell, fg=SUB, size=8)
                self.lbl_last_note.config(height=1)
                self.lbl_last_note.pack(anchor="w")

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
        # 막대는 Canvas 사각형 대신 둥근 이미지로 (Canvas 에는 radius 도
        # 안티앨리어싱도 없다). 트랙 이미지는 하나를 다섯 줄이 함께 쓴다.
        self._track_img = round_img(BAR_MAX, BAR_H, BAR_R, CARD2, LINE, bg=CARD)
        self._bar_imgs = [None] * WEEKDAYS_SHOWN   # 막대 이미지 참조 유지용
        self.bars = []
        for i in range(WEEKDAYS_SHOWN):
            y = i * ROW_H + 14
            day_id = self.chart.create_text(
                4, y, text="", fill=SUB, font=(FONT, 9), anchor="w"
            )
            self.chart.create_image(
                BAR_X0, y, image=self._track_img, anchor="w"
            )
            bar_id = self.chart.create_image(BAR_X0, y, anchor="w")
            val_id = self.chart.create_text(
                BAR_X0 + BAR_MAX + 6, y, text="", fill=FG, font=(FONT, 9), anchor="w"
            )
            self.bars.append((day_id, bar_id, val_id, y))

        # 8시간 기준 세로 점선 (막대 위에 보이도록 막대 아이템 다음에 생성).
        # x 좌표는 _refresh 에서 현재 스케일에 맞춰 갱신한다.
        self.chart_baseline = self.chart.create_line(
            BAR_X0, 2, BAR_X0, WEEKDAYS_SHOWN * ROW_H + 4,
            fill=GRID, dash=(2, 3),
        )

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
        sep = tk.Frame(card, bg=LINE, height=1)
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

    # ----- 비업무시간 수기 보정 (비업무 탭) -----
    def _build_adjust(self, parent):
        """비업무 탭 상단의 보정 카드 (접기/펴기 없이 항상 펼쳐진 상태)."""
        card = self._card(parent)
        head = tk.Frame(card, bg=CARD)
        head.pack(fill="x")
        self._label(
            head, "비업무시간 수기 보정", fg=FG, size=10, bold=True
        ).pack(side="left")
        self.lbl_adjust = self._label(head, fg=TODAY, size=9, bold=True)
        self.lbl_adjust.pack(side="right")

        ctl = tk.Frame(card, bg=CARD)
        ctl.pack(fill="x", pady=(8, 0))
        self.adjust_stepper = Stepper(ctl, value=10, lo=1, hi=600)
        self.adjust_stepper.frame.pack(side="left")
        self._label(ctl, "분", fg=SUB, size=9).pack(side="left", padx=(6, 12))
        # 글자 없이 기호만 (크고 굵게) - 왼쪽 － 빼기, 오른쪽 ＋ 추가
        self._sym_btn(ctl, "－", lambda: self._apply_adjust(-1), ACCENT)
        self._sym_btn(ctl, "＋", lambda: self._apply_adjust(+1), TODAY)
        self._adj_btn(
            ctl, "초기화", self._reset_adjust, SUB
        ).pack_configure(padx=(12, 6))
        # 한도에 걸려 적용하지 못했을 때 이유를 알려 주는 자리 (잠시 후 사라짐)
        self.lbl_adj_msg = self._label(ctl, fg=WARN, size=9)
        self.lbl_adj_msg.pack(side="left")
        self._adj_msg_after = None

        self._build_tags(card)

    # ----- 사유 태그 (＋ 로 추가할 때 그대로 사유가 된다) -----
    def _build_tags(self, card):
        row = tk.Frame(card, bg=CARD)
        row.pack(fill="x", pady=(8, 0))
        self._label(row, "사유 태그", fg=SUB, size=9).pack(side="left", padx=(0, 8))
        self.tag_box = tk.Frame(row, bg=CARD)
        self.tag_box.pack(side="left")
        self._label(
            row, "우클릭으로 태그 삭제", fg=SUB, size=8
        ).pack(side="right")

        # 새 태그 입력줄 - ＋ 칩을 누를 때만 보인다
        self.tag_new = tk.Frame(card, bg=CARD)
        self.tag_var = tk.StringVar()
        self.tag_entry = tk.Entry(
            self.tag_new, textvariable=self.tag_var, bg=CARD2, fg=FG,
            insertbackground=FG, relief="flat", bd=0, font=self.nw_font, width=14,
            highlightthickness=1, highlightbackground=LINE, highlightcolor=ACCENT,
        )
        self.tag_entry.pack(side="left", ipady=3)
        self.tag_entry.bind("<Return>", lambda e: self._add_tag())
        self.tag_entry.bind("<Escape>", lambda e: self._toggle_tag_entry(False))
        # 한글 조합 폰트를 입력란 폰트에 맞춘다 (사유 입력란과 같은 처리)
        self.tag_entry.bind("<FocusIn>", lambda e: self._nw_focus_in(self.tag_entry))
        self.tag_entry.bind("<Key>", lambda e: self._nw_focus_in(self.tag_entry))
        self._adj_btn(self.tag_new, "추가", self._add_tag, GOOD).pack_configure(
            padx=(6, 6)
        )
        self._adj_btn(self.tag_new, "취소", lambda: self._toggle_tag_entry(False), SUB)

        self._nw_tag = None      # 선택된 태그 (None = 사유 없이 추가)
        self._tags = []
        self._render_tags()

    def _render_tags(self, tags=None):
        if tags is None:
            st = S.Storage()
            try:
                tags = st.get_nonwork_tags()
            finally:
                st.close()
        self._tags = tags
        if self._nw_tag not in tags:
            self._nw_tag = None
        for w in self.tag_box.winfo_children():
            w.destroy()
        for t in tags:
            self._tag_chip(t)
        plus = Pill(
            self.tag_box, "＋", font=(FONT, 10, "bold"), fg=ACCENT,
            fill=CARD, outline=LINE, radius=99, padx=8, pady=1, bg=CARD,
            cmd=self._toggle_tag_entry, hover_fill=ACCENT_SOFT,
        )
        plus.pack(side="left", padx=(0, 4))
        if getattr(self, "_active_tab", None) == "nonwork":
            self._refit_height()   # 태그가 늘어 줄 폭/높이가 바뀌면 창도 맞춘다

    @staticmethod
    def _tag_color(tag):
        """태그 이름으로 파스텔 색 한 쌍을 정한다 (목록이 바뀌어도 색은 그대로)."""
        return TAG_COLORS[sum(map(ord, tag)) % len(TAG_COLORS)]

    def _tag_chip(self, tag):
        """todo 앱의 `.tag` 처럼 파스텔 알약. 선택된 칩은 액센트 테두리."""
        sel = (tag == self._nw_tag)
        fill, fg = self._tag_color(tag)
        lb = Pill(
            self.tag_box, tag, font=(FONT, 9, "bold"), fg=fg,
            fill=fill, outline=(ACCENT if sel else fill), radius=99,
            padx=10, pady=2, bg=CARD,
            cmd=lambda t=tag: self._select_tag(t), hover_fill=None,
        )
        lb.pack(side="left", padx=(0, 4))
        lb.bind("<Button-3>", lambda e, t=tag: self._delete_tag(t))

    def _select_tag(self, tag):
        """같은 태그를 다시 누르면 선택 해제 (사유 없이 추가)."""
        self._nw_tag = None if self._nw_tag == tag else tag
        self._render_tags(self._tags)

    def _toggle_tag_entry(self, show=None):
        if show is None:
            show = not self.tag_new.winfo_ismapped()
        if show:
            self.tag_new.pack(fill="x", pady=(6, 0))
            self.tag_entry.focus_set()
        else:
            self.tag_var.set("")
            self.tag_new.pack_forget()
            self.root.focus()
        if getattr(self, "_active_tab", None) == "nonwork":
            self._refit_height()

    def _add_tag(self):
        tag = self.tag_var.get().strip()
        if not tag:
            self._toggle_tag_entry(False)
            return
        st = S.Storage()
        try:
            tags = st.add_nonwork_tag(tag)
        finally:
            st.close()
        self._nw_tag = tag[:S.TAG_MAX_LEN]   # 새로 만든 태그를 바로 선택
        self._toggle_tag_entry(False)
        self._render_tags(tags)

    def _delete_tag(self, tag):
        if not messagebox.askyesno(
            "태그 삭제",
            f"'{tag}' 태그를 목록에서 지울까요?\n\n"
            "이미 입력된 사유는 그대로 남습니다.",
            parent=self.root,
        ):
            return
        st = S.Storage()
        try:
            tags = st.remove_nonwork_tag(tag)
        finally:
            st.close()
        self._render_tags(tags)

    # ----- 출장 · 휴가 · 반차 표시 -----
    def _build_leave(self, card):
        _, self._leave_toggle = self._collapsible(
            card, "출장 · 휴가 · 반차 표시", self._build_leave_body
        )

    def _build_leave_body(self, body):
        self._label(
            body, "근무 → 출장 → 휴가 → 반차", fg=SUB, size=8,
        ).pack(anchor="w", pady=(10, 6))
        row = tk.Frame(body, bg=CARD)
        row.pack(fill="x")
        self.leave_btns = []
        for i in range(WEEKDAYS_SHOWN):
            b = Pill(
                row, "", font=(FONT, 9, "bold"), fg=SUB,
                fill=CARD2, outline=LINE, radius=8, padx=10, pady=5, bg=CARD,
                cmd=lambda i=i: self._cycle_leave(i), min_w=86,
            )
            b.pack(side="left", padx=(0, 6))
            self.leave_btns.append(b)

    def _cycle_leave(self, i):
        monday, _ = S.week_range(date.today())
        d = monday + timedelta(days=i)
        order = [None, "trip", "vacation", "halfday"]
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
        # 비업무 구간이 많아도 창이 화면 밖으로 나가지 않게 상한을 둔다
        sh = self.root.winfo_screenheight()
        h = min(self.root.winfo_reqheight(), sh - MAX_H_MARGIN)
        self.root.geometry(f"{w}x{h}")
        self.root.minsize(rw, h)
        # 창은 아래로 자라므로, 짧은 탭에서 긴 탭(설정)으로 옮기면 아랫부분이
        # 화면 밖으로 밀려난다. 그럴 때만 창을 위로 끌어올린다.
        y_max = max(0, sh - TASKBAR_H - TITLEBAR_H - h)
        if self.root.winfo_y() > y_max:
            self.root.geometry(f"+{self.root.winfo_x()}+{y_max}")

    def _adj_btn(self, parent, text, cmd, fg, bg=None):
        """기본 버튼 (todo 앱 `.btn`: 흰 면 + 1px 테두리 + 8px 라운드)."""
        b = Pill(
            parent, text, font=(FONT, 9, "bold"), fg=fg,
            fill=CARD, outline=LINE, radius=8, padx=11, pady=4,
            bg=(bg or parent["bg"]), cmd=cmd,
        )
        b.pack(side="left", padx=(0, 6))
        return b

    def _sym_btn(self, parent, text, cmd, fg):
        """기호만 있는 버튼 (－ / ＋).

        버튼 크기는 다른 글자 버튼(`_adj_btn`)과 같게 두고, 기호만 조금 키워
        (pady 를 줄여 높이를 맞춘다) 눈에 띄게 한다.
        """
        b = Pill(
            parent, text, font=(FONT, 11, "bold"), fg=fg,
            fill=CARD, outline=LINE, radius=8, padx=11, pady=1,
            bg=parent["bg"], cmd=cmd,
        )
        b.pack(side="left", padx=(0, 6))
        return b

    @staticmethod
    def _fmt_adjust(sec: int) -> str:
        if sec == 0:
            return "없음"
        sign = "＋" if sec > 0 else "−"
        return f"{sign}{S.fmt_hm(abs(sec))}"

    def _apply_adjust(self, sign: int):
        """지금 보고 있는 날짜의 비업무 보정.

        추가분은 목록에 한 줄로 보이도록 수기 구간으로 남기고, 선택한 사유
        태그가 있으면 그 구간의 사유로 함께 저장한다.
        """
        minutes = self.adjust_stepper.value()
        delta = sign * minutes * 60
        day = self._nw_day
        tag = self._nw_tag or ""
        msg = ""
        st = S.Storage()
        try:
            ivs = st.intervals()
            base_work = S.seconds_for_day(ivs, day)
            stay = S.stay_seconds(ivs, day, st.ongoing_pause_now(day))
            base_nonwork = max(0.0, stay - base_work)
            # 비업무 = base_nonwork + 보정 이 [0, 체류] 안에 머물도록 총 보정을 제한.
            #   ⇒ 보정 ∈ [-비업무(다 뺄 수 있는 한도), +실업무(다 더할 수 있는 한도)]
            lo = -int(round(base_nonwork))
            hi = int(round(base_work))
            total = st.total_adjust_seconds(day)
            if not lo <= total + delta <= hi:
                # 한도를 넘으면 남은 만큼만 슬쩍 넣지 않는다. 예전에는 자투리가
                # 그대로 적용돼 10분을 눌렀는데 '4분'·'10초' 짜리 구간이 생겼다.
                msg = self._adjust_limit_msg(delta, hi - total if delta > 0
                                             else total - lo)
            elif delta > 0:
                # 추가는 목록에 한 줄로 남겨 사유(태그)를 붙일 수 있게 한다
                st.add_manual_nonwork(day, delta, tag)
            elif delta < 0:
                # 빼기는 최근 수기 구간부터 지우고, 모자란 만큼만 음수 보정으로
                left = st.reduce_manual_nonwork(day, -delta)
                if left:
                    st.add_adjust_seconds(day, -left)
        finally:
            st.close()
        self._adj_flash(msg)
        self._refresh()
        self._refresh_nonwork()

    @staticmethod
    def _adjust_limit_msg(delta: int, room: int) -> str:
        room = max(0, int(room))
        if delta > 0:
            return ("더 옮길 업무시간이 없습니다" if room == 0 else
                    f"남은 업무시간 {S.fmt_dur(room)}까지만 추가할 수 있어요")
        return ("뺄 비업무시간이 없습니다" if room == 0 else
                f"남은 비업무 {S.fmt_dur(room)}까지만 뺄 수 있어요")

    def _adj_flash(self, text: str):
        """보정 한도 안내를 잠깐 띄운다 (빈 문자열이면 즉시 지움)."""
        self.lbl_adj_msg.config(text=text)
        if self._adj_msg_after:
            self.root.after_cancel(self._adj_msg_after)
            self._adj_msg_after = None
        if text:
            self._adj_msg_after = self.root.after(
                4000, lambda: self.lbl_adj_msg.config(text="")
            )

    def _reset_adjust(self):
        day = self._nw_day
        st = S.Storage()
        try:
            has_manual = st.manual_nonwork_seconds(day) > 0
        finally:
            st.close()
        if has_manual and not messagebox.askyesno(
            "보정 초기화",
            f"{day:%m월 %d일} 보정을 모두 되돌릴까요?\n\n"
            "수기로 추가한 비업무 구간과 그 사유도 함께 지워집니다.",
            parent=self.root,
        ):
            return
        st = S.Storage()
        try:
            st.set_adjust_seconds(day, 0)
            st.clear_manual_nonwork(day)
        finally:
            st.close()
        self._adj_flash("")
        self._refresh()
        self._refresh_nonwork()

    # ----- 비업무(일시정지) 기록 탭 -----
    # 방식 라벨은 태그와 같은 파스텔 알약 (배경, 글자) 으로 그린다.
    NW_METHOD_COLORS = {
        "idle": TAG_COLORS[6],          # 자리비움 - 오커
        "lock": TAG_COLORS[2],          # 화면잠금 - 청회색
        "screensaver": TAG_COLORS[3],   # 화면보호기 - 인디고
        "manual_pause": TAG_COLORS[0],  # 수동 일시정지 - 그린
        "manual": TAG_COLORS[7],        # 수기 추가 - 그레이그린
        "settings_change": TAG_COLORS[7],
    }

    def _build_nonwork(self, parent):
        root = tk.Frame(parent, bg=BG)
        root.pack(fill="both", expand=True, padx=16, pady=10)

        # 조회 날짜 (기본 오늘). ◀/▶ 로 이동, 오늘 이후로는 못 감.
        self._nw_day = date.today()

        # 사유/태그 입력란 전용 폰트(명시적 객체) — 한글 조합 폰트 지정에도 쓴다.
        # (보정 카드의 태그 입력란도 같은 폰트를 쓰므로 먼저 만든다)
        self.nw_font = tkfont.Font(family=FONT, size=10)
        self._nw_ime_px = self.nw_font.metrics("linespace")  # 조합 폰트 높이(px)

        head = tk.Frame(root, bg=BG)
        head.pack(fill="x", pady=(0, 10))
        nav = tk.Frame(head, bg=BG)
        nav.pack(side="left")
        self.btn_nw_prev = self._adj_btn(nav, "◀", lambda: self._nw_shift(-1), FG)
        self.lbl_nw_date = self._label(nav, fg=FG, size=13, bold=True, bg=BG)
        self.lbl_nw_date.pack(side="left", padx=(2, 2))
        self.btn_nw_next = self._adj_btn(nav, "▶", lambda: self._nw_shift(1), FG)
        self.btn_nw_next.config(disabledforeground=SUB)
        # 오늘이 아닐 때만 보이는 "오늘" 복귀 버튼 (pack/forget)
        self.btn_nw_today = self._adj_btn(nav, "오늘", self._nw_goto_today, ACCENT)
        self.btn_nw_today.pack_forget()

        self.lbl_nw_total = self._label(head, fg=SUB, size=11, bold=True, bg=BG)
        self.lbl_nw_total.pack(side="right")
        # 사유 저장 피드백 ("사유 저장됨"; 값이 실제로 바뀐 저장에서만 잠깐 표시)
        self.lbl_nw_saved = self._label(head, fg=GOOD, size=9, bold=True, bg=BG)
        self.lbl_nw_saved.pack(side="right", padx=(0, 12))
        self._nw_saved_after = None

        # 수기 보정 (＋ 추가분은 아래 목록에 한 줄로 나타난다)
        self._build_adjust(root)

        # 스크롤 영역: 캔버스 + 내부 frame(=nw_list). 목록 높이가 상한을 넘을 때만
        # 스크롤하고 스크롤바를 보인다. 그 이하면 기존처럼 내용 높이 그대로.
        wrap = tk.Frame(root, bg=BG)
        wrap.pack(fill="x")
        self.nw_canvas = tk.Canvas(wrap, bg=BG, highlightthickness=0, height=1)
        self.nw_canvas.pack(side="left", fill="x", expand=True)
        style = ttk.Style()
        try:
            style.theme_use("clam")   # 색을 존중하는 테마 (기본 win 테마는 무시)
        except tk.TclError:
            pass
        style.configure(
            "NW.Vertical.TScrollbar", background=GRID, troughcolor=BG,
            bordercolor=BG, arrowcolor=SUB, relief="flat",
        )
        style.map(
            "NW.Vertical.TScrollbar",
            background=[("active", SUB)], arrowcolor=[("active", FG)],
        )
        self.nw_scroll = ttk.Scrollbar(
            wrap, orient="vertical", command=self.nw_canvas.yview,
            style="NW.Vertical.TScrollbar",
        )
        self.nw_canvas.configure(yscrollcommand=self.nw_scroll.set)
        self._nw_scroll_shown = False

        self.nw_list = tk.Frame(self.nw_canvas, bg=BG)
        self._nw_win = self.nw_canvas.create_window(
            (0, 0), window=self.nw_list, anchor="nw"
        )
        self.nw_list.bind("<Configure>", self._on_nw_frame_configure)
        self.nw_canvas.bind("<Configure>", self._on_nw_canvas_configure)
        # 마우스 휠은 커서가 목록 위에 있을 때만 (bind_all/unbind_all)
        self.nw_canvas.bind(
            "<Enter>", lambda e: self.nw_canvas.bind_all("<MouseWheel>", self._nw_wheel)
        )
        self.nw_canvas.bind(
            "<Leave>", lambda e: self.nw_canvas.unbind_all("<MouseWheel>")
        )

        # stop_id 별 위젯/값 추적 (사유 메모 보존 + 진행 중 구간 제자리 갱신)
        self.nw_notes = {}       # stop_id -> StringVar
        self.nw_entries = {}     # stop_id -> Entry
        self.nw_rows = {}        # stop_id -> {"time":Label, "dur":Label}
        self.nw_placeholder = {} # stop_id -> bool (placeholder 표시 중 여부)
        self.nw_saved = {}       # stop_id -> 마지막 저장된 사유(피드백 판정용)
        self._nw_sig = None      # 행 구조가 바뀔 때만 다시 그리기 위한 시그니처

    # ----- 비업무 목록 스크롤 처리 -----
    def _on_nw_frame_configure(self, _e=None):
        content_h = self.nw_list.winfo_reqheight()
        view_h = min(content_h, NW_LIST_MAX_H)
        self.nw_canvas.configure(
            height=view_h, scrollregion=(0, 0, 0, content_h)
        )
        if content_h > NW_LIST_MAX_H:
            if not self._nw_scroll_shown:
                self.nw_scroll.pack(side="right", fill="y")
                self._nw_scroll_shown = True
        else:
            if self._nw_scroll_shown:
                self.nw_scroll.pack_forget()
                self._nw_scroll_shown = False
            self.nw_canvas.yview_moveto(0)

    def _on_nw_canvas_configure(self, e):
        # 내부 frame 너비를 캔버스 너비에 맞춰 사유 입력란이 늘어나게
        self.nw_canvas.itemconfigure(self._nw_win, width=e.width)

    def _nw_wheel(self, e):
        if self._nw_scroll_shown:
            self.nw_canvas.yview_scroll(int(-e.delta / 120), "units")

    # ----- 비업무 날짜 이동 -----
    def _nw_shift(self, delta):
        nd = self._nw_day + timedelta(days=delta)
        if nd > date.today():
            return   # 오늘 이후로는 이동 금지
        self._nw_day = nd
        self._refresh_nonwork()

    def _nw_goto_today(self):
        self._nw_day = date.today()
        self._refresh_nonwork()

    def _nw_flash_saved(self):
        """사유가 실제로 바뀌어 저장됐을 때만 잠깐 '사유 저장됨' 표시."""
        self.lbl_nw_saved.config(text="사유 저장됨")
        if self._nw_saved_after:
            self.root.after_cancel(self._nw_saved_after)
        self._nw_saved_after = self.root.after(
            2000, lambda: self.lbl_nw_saved.config(text="")
        )

    def _nw_focus_in(self, entry):
        """사유 입력란에서 한글 조합 폰트를 입력란 폰트에 맞춘다.

        Tk 가 조합 시작 시 폰트를 되돌리므로 즉시 + 다음 idle(after 0) 두 번 적용해
        Tk 의 재설정 뒤에 우리 값이 남도록 한다.
        """
        set_ime_composition_font(FONT, self._nw_ime_px)
        self.root.after(0, lambda: set_ime_composition_font(FONT, self._nw_ime_px))

    def _nw_entry_focus_in(self, stop_id, entry):
        """포커스가 들어오면 placeholder 를 지우고 입력 색으로. 이어서 IME 폰트 처리."""
        if self.nw_placeholder.get(stop_id):
            self.nw_placeholder[stop_id] = False
            var = self.nw_notes.get(stop_id)
            if var is not None:
                var.set("")
            entry.config(fg=FG)
        self._nw_focus_in(entry)

    def _nw_method(self, reason):
        """(라벨, (칩 배경, 글자색))."""
        label = S.NONWORK_REASON_LABELS.get(reason, "기타")
        return label, self.NW_METHOD_COLORS.get(reason, TAG_COLORS[7])

    def _nw_note_text(self, stop_id) -> str:
        """placeholder 표시 중이면 실제 값이 아니므로 빈 문자열로 취급한다."""
        if self.nw_placeholder.get(stop_id):
            return ""
        var = self.nw_notes.get(stop_id)
        return var.get() if var is not None else ""

    def _save_nw_note(self, stop_id):
        if stop_id not in self.nw_notes:
            return
        text = self._nw_note_text(stop_id).strip()
        prev = self.nw_saved.get(stop_id)
        st = S.Storage()
        try:
            st.set_nonwork_note(stop_id, text)
        finally:
            st.close()
        self.nw_saved[stop_id] = text
        # 값이 실제로 바뀌었을 때만 피드백 (FocusOut/재구성 flush 소음 방지)
        if prev is not None and prev != text:
            self._nw_flash_saved()

    def _nw_focus_out(self, stop_id, entry):
        """포커스가 빠지면: 비어 있으면 placeholder 복원 후 저장."""
        var = self.nw_notes.get(stop_id)
        if var is not None and not var.get().strip():
            self.nw_placeholder[stop_id] = True
            var.set("사유 입력…")
            entry.config(fg=SUB)
        self._save_nw_note(stop_id)

    def _flush_nw_notes(self):
        """행을 다시 그리기 전에 입력 중이던 사유를 모두 저장(유실 방지)."""
        for sid in list(self.nw_notes):
            self._save_nw_note(sid)

    def _build_nw_row(self, r, p, note):
        # 한 구간 = 한 줄(grid). 열 너비는 각 열의 가장 넓은 칸에 자동으로 맞춰져
        # 행끼리 정렬되며, 한글이라도 잘리지 않는다. 사유 입력란(열 3)만 늘어난다.
        sid = p["stop_id"]
        label, (chip_bg, chip_fg) = self._nw_method(p["reason"])
        Pill(
            self.nw_list, label, font=(FONT, 9, "bold"), fg=chip_fg,
            fill=chip_bg, outline=chip_bg, radius=99, padx=10, pady=2, bg=BG,
        ).grid(row=r, column=0, sticky="w", padx=(0, 12), pady=3)
        tlbl = self._label(self.nw_list, fg=FG, size=10, bg=BG)
        tlbl.grid(row=r, column=1, sticky="w", padx=(0, 12), pady=3)
        dlbl = self._label(self.nw_list, fg=SUB, size=10, bold=True, bg=BG)
        dlbl.grid(row=r, column=2, sticky="w", padx=(0, 12), pady=3)
        self.nw_rows[sid] = {"time": tlbl, "dur": dlbl}

        # 사유가 비어 있으면 placeholder("사유 입력…", SUB 색)를 표시한다.
        is_ph = not note
        var = tk.StringVar(value=("사유 입력…" if is_ph else note))
        self.nw_placeholder[sid] = is_ph
        self.nw_saved[sid] = note   # 로드된 값 = 마지막 저장값(피드백 판정 기준)
        ent = tk.Entry(
            self.nw_list, textvariable=var, bg=CARD,
            fg=(SUB if is_ph else FG), insertbackground=FG,
            relief="flat", bd=0, font=self.nw_font,
            highlightthickness=1, highlightbackground=LINE, highlightcolor=ACCENT,
        )
        ent.grid(row=r, column=3, sticky="ew", pady=3, ipady=3)
        ent.bind("<FocusIn>", lambda e, s=sid, en=ent: self._nw_entry_focus_in(s, en))
        # 조합 시작 때 Tk 가 폰트를 되돌리므로 키 입력마다 다시 적용
        ent.bind("<Key>", lambda e, en=ent: self._nw_focus_in(en))
        ent.bind("<Return>", lambda e, s=sid: (self._save_nw_note(s), self.root.focus()))
        ent.bind("<FocusOut>", lambda e, s=sid, en=ent: self._nw_focus_out(s, en))
        self.nw_notes[sid] = var
        self.nw_entries[sid] = ent

        # 진행 중 구간은 이을 상대(재개 start)가 아직 없어 삭제할 수 없다
        if not p["ongoing"]:
            self._nw_del_btn(r, sid)

    def _nw_del_btn(self, r, sid):
        """todo 앱의 `.btn.danger-ghost`: 테두리 없이 흐리게, 올리면 클레이 레드."""
        b = Pill(
            self.nw_list, "삭제", font=(FONT, 9), fg=SUB,
            fill=BG, outline=None, radius=8, padx=9, pady=3, bg=BG,
            cmd=lambda: self._delete_nw(sid), hover_fill="#F0DFDD",
        )
        b.grid(row=r, column=4, sticky="e", padx=(10, 0), pady=3)
        b.bind("<Enter>", lambda e: b.config(fg=WARN), add="+")
        b.bind("<Leave>", lambda e: b.config(fg=SUB), add="+")

    def _delete_nw(self, stop_id):
        """비업무 구간을 지워 그 시간을 업무시간으로 되돌린다 (현황에도 반영)."""
        if S.is_manual_key(stop_id):
            detail = "수기로 추가한 구간이 사라져 비업무 보정이 그만큼 줄어들고,"
        else:
            detail = "앞뒤 활동이 하나로 이어져 해당 시간이 업무시간에 포함되고,"
        if not messagebox.askyesno(
            "비업무 구간 삭제",
            "이 비업무 구간을 삭제할까요?\n\n"
            f"{detail}\n입력한 사유도 함께 지워집니다. 되돌릴 수 없습니다.",
            parent=self.root,
        ):
            return
        st = S.Storage()
        try:
            ok = st.delete_nonwork_period(stop_id)
        finally:
            st.close()
        if not ok:
            return
        # 재구성 전 flush 가 지운 사유를 되살리지 않도록 추적 정보를 먼저 제거
        for d in (self.nw_notes, self.nw_entries, self.nw_rows,
                  self.nw_placeholder, self.nw_saved):
            d.pop(stop_id, None)
        self._nw_sig = None      # 행 구조가 바뀌었으므로 강제 재구성
        self._refresh_nonwork()
        self._refresh()

    def _rebuild_nw_rows(self, periods, notes):
        self._flush_nw_notes()
        for w in self.nw_list.winfo_children():
            w.destroy()
        self.nw_notes.clear()
        self.nw_entries.clear()
        self.nw_rows.clear()
        self.nw_placeholder.clear()
        self.nw_saved.clear()
        if not periods:
            self._label(
                self.nw_list, "기록된 비업무 구간이 없습니다.",
                fg=SUB, size=10, bg=BG,
            ).grid(row=0, column=0, sticky="w", pady=8)
            return
        self.nw_list.columnconfigure(3, weight=1)   # 사유 입력란이 남는 폭을 채움
        for i, p in enumerate(periods):
            self._build_nw_row(i, p, notes.get(p["stop_id"], ""))

    def _refresh_nonwork(self):
        day = self._nw_day
        is_today = (day == date.today())
        self.lbl_nw_date.config(
            text=f"{day:%Y년 %m월 %d일} ({WEEKDAY[day.weekday()]}) 비업무 기록"
        )
        # ▶ 는 오늘 이후로 못 가게 비활성, "오늘" 버튼은 오늘이 아닐 때만 노출
        self.btn_nw_next.config(state=("disabled" if is_today else "normal"))
        if is_today:
            self.btn_nw_today.pack_forget()
        else:
            self.btn_nw_today.pack(side="left", padx=(0, 6))

        st = S.Storage()
        try:
            periods = st.nonwork_periods(day)
            notes = {p["stop_id"]: st.get_nonwork_note(p["stop_id"]) for p in periods}
            adj = st.total_adjust_seconds(day)
        finally:
            st.close()

        # 보정 표시는 보고 있는 날짜 기준 (보정 버튼도 그 날짜에 적용된다)
        self.lbl_adjust.config(
            text="" if adj == 0 else f"보정 {self._fmt_adjust(adj)}"
        )

        total = sum(p["seconds"] for p in periods)
        self.lbl_nw_total.config(text=f"합계 {S.fmt_dur(total)}" if periods else "")

        # day 를 시그니처에 포함 → 날짜를 바꾸면 행이 재구성된다
        # (재구성 경로가 먼저 _flush_nw_notes 를 호출하므로 입력 중 사유는 유실되지 않음)
        sig = (day, tuple((p["stop_id"], p["ongoing"]) for p in periods))
        if sig != self._nw_sig:
            self._rebuild_nw_rows(periods, notes)
            self._nw_sig = sig
            self._on_nw_frame_configure()   # 스크롤 영역/높이 재계산
            if getattr(self, "_active_tab", None) == "nonwork":
                self._refit_height()

        # 시각/길이는 매번 제자리 갱신 (진행 중 구간이 실시간으로 늘어남)
        for p in periods:
            r = self.nw_rows.get(p["stop_id"])
            if not r:
                continue
            if p["start"] is None:      # 수기 추가 구간 - 시각 없음
                r["time"].config(text="—")
            else:
                end_txt = "진행 중" if p["ongoing"] else f"{p['end']:%H:%M}"
                r["time"].config(text=f"{p['start']:%H:%M} → {end_txt}")
            r["dur"].config(text=S.fmt_dur(p["seconds"]))

    # ----- 설정 레이아웃 -----
    def _build_settings(self, parent):
        # 설정 탭은 세 탭 중 가장 길어서 화면 높이 상한(screenheight-80)에 아슬아슬하다.
        # 위아래 여백을 조금 줄여 내보내기 카드까지 화면 안에 들어오게 한다.
        root = tk.Frame(parent, bg=BG)
        root.pack(fill="both", expand=True, padx=16, pady=7)

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
        self.var_goal = tk.BooleanVar(value=cur["goal_alarm_enabled"])
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

        # 알림 (카운팅 방식은 아니지만 같은 편집 버튼으로 저장한다)
        self._label(root, "알림", fg=FG, size=13, bold=True, bg=BG).pack(
            anchor="w", pady=(4, 4)
        )
        goal_card = self._card(root)
        self._setting_check(
            goal_card, self.var_goal, "목표 시간 달성 알림",
            "오늘 실 업무시간이 목표를 넘으면 팝업으로 알립니다 (하루 한 번).",
        )
        grow = tk.Frame(goal_card, bg=CARD)
        grow.pack(fill="x", pady=(8, 0))
        self._label(grow, "목표 시간", fg=SUB, size=10).pack(side="left", padx=(0, 10))
        self.goal_stepper = Stepper(
            grow, value=max(1, round(cur["goal_sec"] / 3600)), lo=1, hi=24,
        )
        self.goal_stepper.frame.pack(side="left")
        self._label(grow, "시간", fg=SUB, size=10).pack(side="left", padx=(8, 0))

        # 편집 / 저장 / 취소 버튼 바
        btnbar = tk.Frame(root, bg=BG)
        btnbar.pack(fill="x", pady=(6, 0))
        self.btn_edit = self._settings_btn(
            btnbar, "편집", self._enter_edit, ACCENT, primary=True
        )
        self.btn_save = self._settings_btn(
            btnbar, "저장", self._save_edit, GOOD, primary=True
        )
        self.btn_cancel = self._settings_btn(btnbar, "취소", self._cancel_edit, SUB)
        self.lbl_saved = self._label(btnbar, fg=SUB, size=9, bg=BG)
        self.lbl_saved.pack(side="right")

        # 토글을 끄면 딸린 시간 입력칸도 같이 비활성화 (편집 중에만 의미)
        self.var_idle.trace_add("write", lambda *a: self._sync_idle_state())
        self.var_goal.trace_add("write", lambda *a: self._sync_goal_state())
        self._set_edit_mode(False)   # 시작은 잠금 상태

        # ----- 데이터 내보내기 -----
        self._label(
            root, "데이터 내보내기", fg=FG, size=13, bold=True, bg=BG
        ).pack(anchor="w", pady=(11, 3))
        self._label(
            root, "선택한 달의 평일(월~금) 기록만 CSV(엑셀)로 저장합니다. 토·일과 기록 없는 날은 제외됩니다.",
            fg=SUB, size=9, bg=BG,
        ).pack(anchor="w", pady=(0, 8))

        exp_card = self._card(root)
        exrow = tk.Frame(exp_card, bg=CARD)
        exrow.pack(fill="x")
        today = date.today()
        self._export_ym = [today.year, today.month]
        self._adj_btn(exrow, "◀", lambda: self._export_change_month(-1), FG)
        self.lbl_export_month = self._label(exrow, fg=FG, size=12, bold=True)
        self.lbl_export_month.pack(side="left", padx=(2, 2))
        self.btn_export_next = self._adj_btn(exrow, "▶", lambda: self._export_change_month(1), FG)
        self.btn_export = self._settings_btn(
            exrow, "내보내기", self._do_export, ACCENT, primary=True
        )
        self.btn_export.pack(side="left", padx=(12, 0))

        # 저장 위치: meta 'export_dir' 에 유지, 없으면 기본 폴더
        st = S.Storage()
        try:
            saved_dir = st.get_meta("export_dir")
        finally:
            st.close()
        self._export_dir = saved_dir or EXP.default_out_dir()
        dirrow = tk.Frame(exp_card, bg=CARD)
        dirrow.pack(fill="x", pady=(8, 0))
        self._adj_btn(dirrow, "위치 변경", self._export_pick_dir, FG)
        self.lbl_export_dir = self._label(dirrow, fg=SUB, size=9)
        self.lbl_export_dir.pack(side="left")
        self._update_export_dir()

        self.lbl_export_done = self._label(exp_card, fg=SUB, size=9)
        self.lbl_export_done.pack(anchor="w", pady=(8, 0))
        self._update_export_month()

    def _update_export_month(self):
        y, m = self._export_ym
        self.lbl_export_month.config(text=f"{y:04d}-{m:02d}")
        # 현재 달 이상이면 ▶ 비활성화(미래로 이동 차단)
        today = date.today()
        if (y, m) >= (today.year, today.month):
            self.btn_export_next.config(state="disabled", disabledforeground=SUB)
        else:
            self.btn_export_next.config(state="normal")

    def _export_change_month(self, delta: int):
        y, m = self._export_ym
        m += delta
        if m < 1:
            y -= 1
            m = 12
        elif m > 12:
            y += 1
            m = 1
        # 현재 달보다 미래면 클램프(이동 취소)
        today = date.today()
        if (y, m) > (today.year, today.month):
            return
        self._export_ym = [y, m]
        self._update_export_month()
        self.lbl_export_done.config(text="", fg=SUB)

    def _update_export_dir(self):
        path = self._export_dir
        if len(path) > 46:   # 창이 옆으로 늘어나지 않게 가운데를 줄임
            path = path[:20] + "…" + path[-25:]
        self.lbl_export_dir.config(text=f"저장 위치: {path}")

    def _export_pick_dir(self):
        initial = self._export_dir if os.path.isdir(self._export_dir) else os.path.expanduser("~")
        chosen = filedialog.askdirectory(
            parent=self.root, title="내보내기 폴더 선택", initialdir=initial
        )
        if not chosen:
            return
        self._export_dir = os.path.normpath(chosen)
        st = S.Storage()
        try:
            st.set_meta("export_dir", self._export_dir)
        finally:
            st.close()
        self._update_export_dir()
        self.lbl_export_done.config(text="", fg=SUB)

    def _do_export(self):
        y, m = self._export_ym
        try:
            paths = EXP.export_month(y, m, self._export_dir)
        except Exception as e:
            self.lbl_export_done.config(text=f"내보내기 실패: {e}", fg=TODAY)
            return
        self.lbl_export_done.config(
            text=f"저장됨 · {os.path.dirname(paths['daily'])}", fg=GOOD
        )
        # 탐색기로 폴더 열고 daily 파일 선택
        daily = paths["daily"]
        try:
            if os.path.exists(daily):
                subprocess.Popen(f'explorer /select,"{os.path.normpath(daily)}"')
            else:
                os.startfile(os.path.dirname(daily))
        except Exception:
            pass

    def _settings_btn(self, parent, text, cmd, fg, primary=False):
        """설정/내보내기용 버튼. primary 는 todo 앱 `.btn.primary`(틸 채움)."""
        if primary:
            return Pill(
                parent, text, font=(FONT, 10, "bold"), fg=ON_ACCENT,
                fill=ACCENT, outline=ACCENT, radius=8, padx=16, pady=5,
                bg=parent["bg"], cmd=cmd, hover_fill=ACCENT_INK,
            )
        return Pill(
            parent, text, font=(FONT, 10, "bold"), fg=fg,
            fill=CARD, outline=LINE, radius=8, padx=16, pady=5,
            bg=parent["bg"], cmd=cmd,
        )

    def _setting_check(self, card, var, title, desc):
        top = tk.Frame(card, bg=CARD)
        top.pack(fill="x")
        title_lbl = self._label(top, title, fg=FG, size=11, bold=True)
        title_lbl.pack(side="left")
        sw = ToggleSwitch(top, var, bg=CARD)
        sw.widget.pack(side="right")
        self.toggles.append(sw)
        desc_lbl = self._label(card, desc, fg=SUB, size=9)
        desc_lbl.pack(anchor="w", pady=(2, 0))
        # 제목/설명/행 빈 곳 어디를 눌러도 토글 (작은 스위치만 누르기 어려운 문제 방지)
        for w in (top, title_lbl, desc_lbl):
            sw.add_target(w)

    # ----- 편집 모드 제어 -----
    def _set_edit_mode(self, editing: bool):
        self._editing = editing
        for sw in self.toggles:
            sw.set_enabled(editing)
        self._sync_idle_state()
        self._sync_goal_state()
        if editing:
            self.btn_edit.pack_forget()
            self.btn_save.pack(side="left", padx=(0, 6))
            self.btn_cancel.pack(side="left")
        else:
            self.btn_save.pack_forget()
            self.btn_cancel.pack_forget()
            self.btn_edit.pack(side="left")

    def _enter_edit(self):
        # 취소 대비 현재(저장된) 값 스냅샷
        self._snapshot = {
            "idle": self.var_idle.get(),
            "lock": self.var_lock.get(),
            "ss": self.var_ss.get(),
            "goal": self.var_goal.get(),
            "min": self.idle_stepper.value(),
            "goalh": self.goal_stepper.value(),
        }
        self._set_edit_mode(True)
        self.lbl_saved.config(text="편집 중…", fg=ACCENT)

    def _cancel_edit(self):
        s = self._snapshot
        self.var_idle.set(s["idle"])
        self.var_lock.set(s["lock"])
        self.var_ss.set(s["ss"])
        self.var_goal.set(s["goal"])
        self.idle_stepper.set(s["min"])
        self.goal_stepper.set(s["goalh"])
        self._set_edit_mode(False)
        self.lbl_saved.config(text="변경 취소됨", fg=SUB)

    def _save_edit(self):
        self._save_settings()
        self._set_edit_mode(False)

    def _sync_idle_state(self):
        """편집 중이고 자리비움이 켜져 있을 때만 기준 시간 입력칸 활성화."""
        self.idle_stepper.set_enabled(self._editing and bool(self.var_idle.get()))

    def _sync_goal_state(self):
        """편집 중이고 알림이 켜져 있을 때만 목표 시간 입력칸 활성화."""
        self.goal_stepper.set_enabled(self._editing and bool(self.var_goal.get()))

    def _read_settings(self):
        st = S.Storage()
        try:
            return st.get_settings()
        finally:
            st.close()

    def _save_settings(self):
        minutes = self.idle_stepper.value()   # 이미 [1, 600] 으로 클램프됨
        goal_sec = self.goal_stepper.value() * 3600   # [1, 24] 시간
        st = S.Storage()
        try:
            st.set_setting("idle_enabled", bool(self.var_idle.get()))
            st.set_setting("idle_threshold_sec", minutes * 60)
            st.set_setting("lock_enabled", bool(self.var_lock.get()))
            st.set_setting("screensaver_enabled", bool(self.var_ss.get()))
            st.set_setting("goal_alarm_enabled", bool(self.var_goal.get()))
            # 목표 시간을 바꿨으면 오늘 이미 알린 표식을 지워 새 목표로 다시 알리게 한다
            if st.get_settings()["goal_sec"] != goal_sec:
                st.clear_goal_notified()
            st.set_setting("goal_sec", goal_sec)
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
            adjusts = {d: st.total_adjust_seconds(d) for d in days}
            leaves = {d: st.get_leave(d) for d in days}
            # 오늘이 주말이면 days 에 없으므로 오늘 값도 따로 챙긴다 (오늘 카드용)
            adjusts.setdefault(today, st.total_adjust_seconds(today))
            leaves.setdefault(today, st.get_leave(today))
            pause_until = st.ongoing_pause_now(today)
            last_active = st.last_active()
            return ivs, last, adjusts, leaves, pause_until, last_active
        finally:
            st.close()

    def _activity_state(self, last, last_active):
        """현재 기록 상태를 판정해 (상태, 사유 라벨) 로 반환.

        상태: none(기록 없음) | active(카운팅 중) | paused(일시정지)
              | ended(퇴근/종료) | stale(카운팅 중인데 하트비트가 끊김)

        stale 은 트레이 앱이 죽었거나 폴링이 멈춘 경우다. 이때 '최근 활동'은
        더 이상 갱신되지 않는데 화면의 나머지는 계속 도니까, 따로 알려 준다.
        """
        if last is None:
            return "none", ""
        if last["kind"] == "stop":
            label = S.NONWORK_REASON_LABELS.get(last["reason"])
            return ("paused", label) if label else ("ended", "")
        if (last_active is None
                or (datetime.now() - last_active).total_seconds() > STALE_SEC):
            return "stale", ""
        return "active", ""

    def _status(self, state, label):
        """상태 칩의 (글자, 글자색, 칩 배경). 색은 태그 파스텔과 같은 계열."""
        # '수동 일시정지'처럼 라벨에 이미 일시정지가 들어있으면 덧붙이지 않는다
        paused = f"■ {label}" if label.endswith("일시정지") else f"■ {label} (일시정지)"
        return {
            "none": ("기록 없음", SUB, CARD2),
            "active": ("● 업무 중", ACCENT_INK, ACCENT_SOFT),
            "paused": (paused, "#85683B", "#EFE6D6"),
            "ended": ("■ 퇴근 / 종료", "#5A695F", "#E3E8E3"),
            "stale": ("■ 기록 멈춤 · 트레이 앱 확인", "#8C5450", "#F0DFDD"),
        }[state]

    # ----- 값만 갱신 (깜빡임 없음) -----
    def _refresh(self):
        ivs, last, adjusts, leaves, pause_until, last_active = self._load()
        today = date.today()

        self.lbl_date.config(
            text=f"{today:%Y년 %m월 %d일} ({WEEKDAY[today.weekday()]})"
        )
        state, state_label = self._activity_state(last, last_active)
        stxt, scol, sfill = self._status(state, state_label)
        self.lbl_status.set_style(text=stxt, fg=scol, fill=sfill, outline=None)

        today_adj = adjusts.get(today, 0)
        today_leave = leaves.get(today)
        today_work, today_nonwork = S.split_for_day(
            ivs, today, today_adj, today_leave, pause_until
        )
        first, lastt = S.day_bounds(ivs, today)
        today_stay = S.stay_seconds(ivs, today, pause_until)
        self.lbl_today.config(text=S.fmt_hm(today_work))
        self.today_cells["출근"].config(text=f"{first:%H:%M}" if first else "--:--")
        # 최근 활동: 값 자체는 마지막 활동 시각(일시정지 중엔 멈춰 있는 게 정상).
        # 왜 안 움직이는지를 아래 줄과 색으로 같이 보여 준다.
        note, ncol = {
            "paused": (f"{state_label} 중", TODAY),
            "stale": ("기록 멈춤", WARN),
        }.get(state, ("", SUB))
        self.today_cells["최근 활동"].config(
            text=f"{lastt:%H:%M}" if lastt else "--:--",
            fg=(WARN if state == "stale" else FG),
        )
        self.lbl_last_note.config(text=note, fg=ncol)
        self.today_cells["체류시간"].config(
            text=S.fmt_hm(today_stay) if first else "-"
        )
        self.today_cells["비업무"].config(
            text=S.fmt_hm(today_nonwork) if first else "-"
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

        # 8시간 기준선을 현재 스케일 위치로 이동 (차트 세로 전체 관통)
        bx = BAR_X0 + BAR_MAX * (WORKDAY_SCALE_SEC / scale)
        self.chart.coords(
            self.chart_baseline, bx, 2, bx, WEEKDAYS_SHOWN * ROW_H + 4
        )

        for i, (d, sec) in enumerate(zip(days, day_secs)):
            leave = leaves.get(d)
            is_today = d == today
            day_id, bar_id, val_id, y = self.bars[i]
            self.chart.itemconfig(
                day_id, text=f"{WEEKDAY[d.weekday()]} {d:%m.%d}",
                fill=(TODAY if is_today else SUB),
            )
            w = int(BAR_MAX * min(1.0, sec / scale))
            bar_fill = LEAVE_COLORS.get(leave) or (BAR_TODAY if is_today else BAR_WORK)
            # 폭이 바뀔 때마다 그 폭의 둥근 막대 이미지를 만든다(캐시됨).
            # itemconfig 는 이미지 이름만 들고 있으므로 파이썬 참조를 따로 붙든다.
            self._bar_imgs[i] = round_img(max(w, 1), BAR_H, BAR_R, bar_fill, bg=CARD)
            self.chart.itemconfig(
                bar_id, image=self._bar_imgs[i],
                state=("normal" if sec > 0 else "hidden"),
            )
            if leave:
                vtext, vcol = f"{S.LEAVE_LABELS[leave]} {S.fmt_hm(sec)}", bar_fill
            else:
                vtext, vcol = ("-" if sec == 0 else S.fmt_hm(sec)), (FG if sec else SUB)
            self.chart.itemconfig(val_id, text=vtext, fill=vcol)

            # 휴가/출장/반차 버튼 라벨·색 갱신
            btn = self.leave_btns[i]
            label = f"{WEEKDAY[d.weekday()]} {d:%m.%d}"
            if leave:
                btn.set_style(
                    text=f"{label}\n{S.LEAVE_LABELS[leave]}",
                    fg=LEAVE_COLORS[leave], fill=LEAVE_SOFT[leave],
                    outline=LEAVE_COLORS[leave],
                )
            else:
                btn.set_style(
                    text=f"{label}\n근무", fg=SUB, fill=CARD2, outline=LINE,
                )

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
            self._refresh_nonwork()
        finally:
            self.root.after(REFRESH_MS, self._tick)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    Dashboard().run()
