"""
dashboard.py - 업무시간 현황 GUI (tkinter, 추가 설치 불필요)

py dashboard.py        # 콘솔과 함께 실행 (디버그)
pythonw dashboard.py   # 콘솔 없이 GUI 만 (트레이 메뉴가 이 방식으로 실행)

다크 테마 카드 UI + 주간 막대그래프 + 5초 자동 새로고침.
위젯은 한 번만 생성하고 값만 갱신하므로 새로고침 시 깜빡임이 없다.
"""

import tkinter as tk
from datetime import date, datetime, timedelta

import storage as S

# ----- 색상/폰트 테마 -----
BG = "#1b1f2e"
CARD = "#262b3d"
CARD2 = "#2f3650"
FG = "#e8ecf5"
SUB = "#9aa3bd"
ACCENT = "#78c8ff"
TODAY = "#ffce6b"
GOOD = "#7ee0a8"

FONT = "맑은 고딕"
WEEKDAY = ["월", "화", "수", "목", "금", "토", "일"]

REFRESH_MS = 5000
WORKDAY_SCALE_SEC = 8 * 3600  # 막대 길이 기준 (8시간)

BAR_X0 = 60       # 막대 시작 x (요일 라벨 영역 다음)
BAR_MAX = 300     # 막대 최대 길이
VAL_W = 96        # 막대 오른쪽 시간 숫자 영역
CHART_W = BAR_X0 + BAR_MAX + VAL_W
ROW_H = 32


class Dashboard:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("업무시간 현황")
        self.root.configure(bg=BG)

        self._build()
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

    def _card(self, parent, pad=14):
        c = tk.Frame(parent, bg=CARD)
        c.pack(fill="x", pady=(0, 12))
        inner = tk.Frame(c, bg=CARD)
        inner.pack(fill="x", padx=pad, pady=pad)
        return inner

    # ----- 레이아웃 1회 생성 -----
    def _build(self):
        root = tk.Frame(self.root, bg=BG)
        root.pack(fill="both", expand=True, padx=18, pady=16)

        # 헤더
        head = tk.Frame(root, bg=BG)
        head.pack(fill="x", pady=(0, 14))
        self.lbl_date = self._label(head, fg=FG, size=15, bold=True, bg=BG)
        self.lbl_date.pack(side="left")
        self.lbl_status = self._label(head, fg=GOOD, size=11, bold=True, bg=BG)
        self.lbl_status.pack(side="right")

        # 오늘 카드
        card = self._card(root)
        self._label(card, "오늘 실 업무시간", fg=SUB, size=10).pack(anchor="w")
        self.lbl_today = self._label(card, fg=ACCENT, size=30, bold=True)
        self.lbl_today.pack(anchor="w", pady=(2, 10))

        row = tk.Frame(card, bg=CARD)
        row.pack(fill="x")
        self.today_cells = {}
        for i, key in enumerate(["출근", "최근 활동", "체류시간"]):
            cell = tk.Frame(row, bg=CARD)
            cell.grid(row=0, column=i, sticky="w", padx=(0, 22))
            self._label(cell, key, fg=SUB, size=9).pack(anchor="w")
            val = self._label(cell, fg=FG, size=13, bold=True)
            val.pack(anchor="w")
            self.today_cells[key] = val

        # 주간 카드
        wcard = self._card(root)
        self.lbl_week_range = self._label(wcard, fg=SUB, size=10)
        self.lbl_week_range.pack(anchor="w", pady=(0, 8))

        self.chart = tk.Canvas(
            wcard, bg=CARD, highlightthickness=0,
            width=CHART_W, height=7 * ROW_H + 6,
        )
        self.chart.pack(fill="x")
        # 7일치 캔버스 아이템을 미리 생성하고 id 보관 → 갱신 시 좌표/텍스트만 수정
        self.bars = []
        for i in range(7):
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

        # 합계 카드
        foot = self._card(root)
        frow = tk.Frame(foot, bg=CARD)
        frow.pack(fill="x")
        self.foot_cells = {}
        for i, (key, col) in enumerate([("주간 합계", GOOD), ("근무일 평균", FG)]):
            cell = tk.Frame(frow, bg=CARD)
            cell.grid(row=0, column=i, sticky="w", padx=(0, 40))
            self._label(cell, key, fg=SUB, size=9).pack(anchor="w")
            val = self._label(cell, fg=col, size=16, bold=True)
            val.pack(anchor="w")
            self.foot_cells[key] = val

        self.lbl_refresh = self._label(root, fg=SUB, size=8, bg=BG)
        self.lbl_refresh.pack(anchor="e", pady=(4, 0))

    # ----- 데이터 -----
    def _load(self):
        st = S.Storage()
        try:
            return st.intervals(), st.last_event()
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
        ivs, last = self._load()
        today = date.today()

        self.lbl_date.config(
            text=f"{today:%Y년 %m월 %d일} ({WEEKDAY[today.weekday()]})"
        )
        stxt, scol = self._status(last)
        self.lbl_status.config(text=stxt, fg=scol)

        today_sec = S.seconds_for_day(ivs, today)
        first, lastt = S.day_bounds(ivs, today)
        self.lbl_today.config(text=S.fmt_hm(today_sec))
        self.today_cells["출근"].config(text=f"{first:%H:%M}" if first else "--:--")
        self.today_cells["최근 활동"].config(text=f"{lastt:%H:%M}" if lastt else "--:--")
        self.today_cells["체류시간"].config(
            text=S.fmt_hm((lastt - first).total_seconds()) if first else "-"
        )

        monday, sunday = S.week_range(today)
        self.lbl_week_range.config(text=f"이번 주  ({monday:%m.%d} ~ {sunday:%m.%d})")

        day_secs = [
            S.seconds_for_day(ivs, monday + timedelta(days=i)) for i in range(7)
        ]
        week_total = sum(day_secs)
        scale = max(WORKDAY_SCALE_SEC, max(day_secs) if day_secs else 0, 1)

        for i, sec in enumerate(day_secs):
            d = monday + timedelta(days=i)
            is_today = d == today
            day_id, bar_id, val_id, y = self.bars[i]
            self.chart.itemconfig(
                day_id, text=f"{WEEKDAY[d.weekday()]} {d:%m.%d}",
                fill=(TODAY if is_today else SUB),
            )
            w = int(BAR_MAX * min(1.0, sec / scale))
            self.chart.coords(bar_id, BAR_X0, y - 8, BAR_X0 + max(w, 0), y + 8)
            self.chart.itemconfig(
                bar_id, fill=(TODAY if is_today else ACCENT),
                state=("normal" if sec > 0 else "hidden"),
            )
            self.chart.itemconfig(
                val_id, text=("-" if sec == 0 else S.fmt_hm(sec)),
                fill=(FG if sec else SUB),
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
        finally:
            self.root.after(REFRESH_MS, self._tick)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    Dashboard().run()
