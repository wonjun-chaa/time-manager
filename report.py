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
    st = S.Storage()
    try:
        ivs = st.intervals()
    finally:
        st.close()

    lines = []
    lines.append("=" * 44)
    lines.append("  업무시간 현황")
    lines.append("=" * 44)

    # --- 오늘(대상일) ---
    today_sec = S.seconds_for_day(ivs, target)
    first, last = S.day_bounds(ivs, target)
    lines.append(f"\n[{target:%Y-%m-%d} ({WEEKDAY_KR[target.weekday()]})] 일일 현황")
    if first:
        lines.append(f"  출근(첫 활동) : {first:%H:%M}")
        lines.append(f"  마지막 활동   : {last:%H:%M}")
        gross = (last - first).total_seconds()
        lines.append(f"  체류 시간     : {S.fmt_hm(gross)}")
    else:
        lines.append("  기록 없음")
    lines.append(f"  실 업무 시간  : {S.fmt_hm(today_sec)}")

    # --- 이번 주 ---
    monday, sunday = S.week_range(target)
    lines.append(f"\n[주간] {monday:%m-%d}(월) ~ {sunday:%m-%d}(일)")
    week_total = 0.0
    for i in range(7):
        d = monday + timedelta(days=i)
        sec = S.seconds_for_day(ivs, d)
        week_total += sec
        mark = " <- 오늘" if d == date.today() else ""
        bar = "#" * int(sec // 1800)  # 30분당 막대 1칸
        lines.append(
            f"  {d:%m-%d}({WEEKDAY_KR[d.weekday()]})  {S.fmt_hm(sec):>10}  {bar}{mark}"
        )
    lines.append("-" * 44)
    lines.append(f"  주간 합계     : {S.fmt_hm(week_total)}")
    avg = week_total / max(1, sum(1 for i in range(7)
                                 if S.seconds_for_day(ivs, monday + timedelta(days=i)) > 0))
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
