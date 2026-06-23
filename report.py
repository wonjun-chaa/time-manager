"""
report.py - 일일/주간 업무시간 현황 보기

사용법:
    py report.py              # 오늘 + 이번 주 요약
    py report.py --week       # 이번 주 일자별 상세
    py report.py --date 2026-06-22
"""

import argparse
import sys
from datetime import date, datetime, timedelta

import storage as S

# 콘솔 코드페이지와 무관하게 한글이 깨지지 않도록 UTF-8 로 출력
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


WEEKDAY_KR = ["월", "화", "수", "목", "금", "토", "일"]


def build_report(target: date) -> str:
    monday, _ = S.week_range(target)
    friday = monday + timedelta(days=4)
    st = S.Storage()
    try:
        ivs = st.intervals()
        days = [monday + timedelta(days=i) for i in range(5)]   # 월~금
        adjusts = {d: st.get_adjust_seconds(d) for d in days}
        leaves = {d: st.get_leave(d) for d in days}
        target_adj = st.get_adjust_seconds(target)
        target_leave = st.get_leave(target)
    finally:
        st.close()

    lines = []
    lines.append("=" * 44)
    lines.append("  업무시간 현황")
    lines.append("=" * 44)

    # --- 오늘(대상일) ---
    work, nonwork = S.split_for_day(ivs, target, target_adj, target_leave)
    first, last = S.day_bounds(ivs, target)
    lines.append(f"\n[{target:%Y-%m-%d} ({WEEKDAY_KR[target.weekday()]})] 일일 현황")
    if target_leave:
        lines.append(f"  표시          : {S.LEAVE_LABELS[target_leave]} (8시간 기본)")
    if first:
        lines.append(f"  출근(첫 활동) : {first:%H:%M}")
        lines.append(f"  마지막 활동   : {last:%H:%M}")
        gross = (last - first).total_seconds()
        lines.append(f"  체류 시간     : {S.fmt_hm(gross)}")
    elif not target_leave:
        lines.append("  기록 없음")
    lines.append(f"  실 업무 시간  : {S.fmt_hm(work)}")
    lines.append(f"  비업무 시간   : {S.fmt_hm(nonwork)}")
    if target_adj:
        sign = "+" if target_adj > 0 else "-"
        lines.append(f"  수기 보정     : 비업무 {sign}{S.fmt_hm(abs(target_adj))}")

    # --- 이번 주 (월~금) ---
    lines.append(f"\n[주간] {monday:%m-%d}(월) ~ {friday:%m-%d}(금)")
    week_total = 0.0
    worked_days = 0
    for d in days:
        sec = S.split_for_day(ivs, d, adjusts.get(d, 0), leaves.get(d))[0]
        week_total += sec
        if sec > 0:
            worked_days += 1
        mark = " <- 오늘" if d == date.today() else ""
        lv = leaves.get(d)
        tag = f" [{S.LEAVE_LABELS[lv]}]" if lv else ""
        bar = "#" * int(sec // 1800)  # 30분당 막대 1칸
        lines.append(
            f"  {d:%m-%d}({WEEKDAY_KR[d.weekday()]})  {S.fmt_hm(sec):>10}  {bar}{mark}{tag}"
        )
    lines.append("-" * 44)
    lines.append(f"  주간 합계     : {S.fmt_hm(week_total)}")
    avg = week_total / max(1, worked_days)
    lines.append(f"  근무일 평균   : {S.fmt_hm(avg)}")
    lines.append("=" * 44)
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="업무시간 현황")
    ap.add_argument("--date", help="YYYY-MM-DD (기본: 오늘)")
    ap.add_argument("--week", action="store_true", help="이번 주 상세 (동일 출력)")
    args = ap.parse_args()

    if args.date:
        target = datetime.strptime(args.date, "%Y-%m-%d").date()
    else:
        target = date.today()

    print(build_report(target))


if __name__ == "__main__":
    main()
