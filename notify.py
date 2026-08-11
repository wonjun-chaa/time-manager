"""notify.py - 목표 시간 달성 알림 팝업 (대시보드와 같은 디자인).

Windows 기본 MessageBox 대신 쓰는 토스트형 알림. 트레이 앱이 **별도 프로세스**로
띄운다(모달 MessageBox 가 폴링 스레드를 잡아먹던 문제도 같이 사라진다):

    pythonw notify.py <실업무_초> <목표_초>

색/폰트/둥근 모서리는 dashboard.py 의 팔레트와 헬퍼(`Pill`, `round_img`)를
그대로 가져다 쓰므로, 테마를 바꾸면 이 팝업도 같이 바뀐다.

단독 확인:  py notify.py 30000 28800
"""

import ctypes
import sys
import tkinter as tk

from PIL import Image, ImageDraw, ImageTk

import storage as S
from dashboard import (
    ACCENT, ACCENT_INK, CARD, FG, FONT, LINE, ON_ACCENT, SUB, Pill,
)

W, H = 400, 150          # 팝업 크기(px)
SHOW_MS = 15000          # 자동으로 닫히기까지
FADE_MS = 25             # 페이드 한 단계 간격
ALPHA = 0.98
# DWM: 창 모서리를 OS 가 둥글게 깎게 한다 (Win11).
# 예전엔 투명 키 컬러 + 둥근 이미지로 흉내냈는데, 페이드(-alpha)와 같이 쓰면
# 색 키가 먹지 않아 모서리에 분홍 자국이 남았다.
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_ROUND = 2


def _badge(size=46):
    """틸 원 + 흰 체크 배지 (Pillow 4배 → LANCZOS, Canvas 계단 방지)."""
    ss = 4
    im = Image.new("RGB", (size * ss, size * ss), CARD)
    d = ImageDraw.Draw(im)
    d.ellipse([0, 0, size * ss - 1, size * ss - 1], fill=ACCENT)
    p = [(0.28, 0.52), (0.43, 0.68), (0.73, 0.33)]
    d.line([(x * size * ss, y * size * ss) for x, y in p],
           fill=ON_ACCENT, width=int(0.085 * size * ss), joint="curve")
    return ImageTk.PhotoImage(im.resize((size, size), Image.LANCZOS))


class GoalPopup:
    def __init__(self, worked: int, goal: int):
        self.root = tk.Tk()
        self.root.title("업무시간 달성")
        self.root.configure(bg=LINE)          # 1px 테두리 역할
        self.root.overrideredirect(True)      # 타이틀바 없는 토스트
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.0)   # 페이드 인

        # 화면 오른쪽 아래(작업표시줄 위)에 띄운다
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.root.geometry(f"{W}x{H}+{sw - W - 24}+{sh - H - 72}")

        # 흰 카드 (테두리 1px 만 남기고 안을 채운다)
        self.card = tk.Frame(self.root, bg=CARD)
        self.card.place(x=1, y=1, width=W - 2, height=H - 2)

        self._badge_img = _badge()
        tk.Label(self.card, image=self._badge_img, bd=0, bg=CARD).place(x=23, y=25)

        x = 85
        self._lbl(x, 24, "목표 시간 달성", FG, 14, True)
        self._lbl(x, 50, S.fmt_hm(worked), ACCENT, 26, True)

        Pill(
            self.card, "확인", font=(FONT, 11, "bold"), fg=ON_ACCENT,
            fill=ACCENT, outline=ACCENT, radius=8, padx=22, pady=6,
            bg=CARD, cmd=self.close, hover_fill=ACCENT_INK,
        ).place(x=W - 106, y=H - 54)

        # 카드 아무 데나 눌러도 닫힌다 (배지/글자 포함)
        for w in [self.root, self.card] + list(self.card.winfo_children()):
            if not isinstance(w, Pill):
                w.bind("<Button-1>", lambda e: self.close())
        self.root.bind("<Escape>", lambda e: self.close())
        self.root.bind("<Return>", lambda e: self.close())
        self.root.focus_force()
        self._round_corners()

        self._closing = False
        self._fade(0.0, +0.14)
        self.root.after(SHOW_MS, self.close)

    def _lbl(self, x, y, text, fg, size, bold=False):
        f = (FONT, size, "bold") if bold else (FONT, size)
        lb = tk.Label(self.card, text=text, fg=fg, bg=CARD, font=f, anchor="w")
        lb.place(x=x, y=y)
        return lb

    def _round_corners(self):
        """Win11 이면 DWM 이 창 모서리를 둥글게 깎아 준다 (실패는 무시)."""
        try:
            self.root.update_idletasks()
            hwnd = (ctypes.windll.user32.GetParent(self.root.winfo_id())
                    or self.root.winfo_id())
            val = ctypes.c_int(DWMWCP_ROUND)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_WINDOW_CORNER_PREFERENCE,
                ctypes.byref(val), ctypes.sizeof(val),
            )
        except Exception:
            pass

    def _fade(self, a, step):
        a = max(0.0, min(ALPHA, a + step))
        self.root.attributes("-alpha", a)
        if step > 0 and a < ALPHA:
            self.root.after(FADE_MS, lambda: self._fade(a, step))
        elif step < 0:
            if a <= 0.0:
                self.root.destroy()
            else:
                self.root.after(FADE_MS, lambda: self._fade(a, step))

    def close(self):
        if self._closing:
            return
        self._closing = True
        self._fade(ALPHA, -0.2)

    def run(self):
        self.root.mainloop()


def main(argv):
    try:
        worked = int(float(argv[1]))
        goal = int(float(argv[2]))
    except (IndexError, ValueError):
        worked, goal = 8 * 3600, 8 * 3600
    GoalPopup(worked, goal).run()


if __name__ == "__main__":
    main(sys.argv)
