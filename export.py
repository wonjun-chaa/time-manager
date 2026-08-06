"""
export.py - 저장된 근무 기록을 CSV 로 내보낸다.

엑셀에서 바로 열 수 있도록 UTF-8 BOM(utf-8-sig)으로 저장한다.
대시보드 '데이터 내보내기' 버튼과 CLI 양쪽에서 같은 함수를 쓴다.

CLI:
    py export.py                       # 이번 달
    py export.py --month 2026-06       # 특정 달
    py export.py --from 2026-06-01 --to 2026-06-30   # 임의 구간
    py export.py --month 2026-06 --out "D:/내보내기"  # 출력 폴더 지정

만들어지는 파일(구간 태그가 파일명에 붙는다):
    daily_<태그>.csv     날짜·요일·출근·퇴근·체류·실업무·비업무·휴가출장반차·보정
    weekly_<태그>.csv    주(월~금)·근무일수·주간 실업무 합계·일 평균
    nonwork_<태그>.csv   날짜·방식·시작·끝·시간(분)·사유

토·일과 기록이 전혀 없는 날(휴가/출장/반차 표시도 없는 날)은 어느 파일에도 넣지 않는다.
"""

import os
import sys
import csv
import argparse
from datetime import date, timedelta

import storage as S

WEEKDAY = ["월", "화", "수", "목", "금", "토", "일"]


def default_out_dir() -> str:
    """기본 출력 폴더(사용자 홈 아래 TimeTracker_export)."""
    return os.path.join(os.path.expanduser("~"), "TimeTracker_export")


def _hm(seconds) -> str:
    """초 → 'H:MM' (엑셀에서 보기 좋은 시:분). 0 도 '0:00' 으로 표기."""
    s = int(round(seconds))
    return f"{s // 3600}:{(s % 3600) // 60:02d}"


def _signed_hm(seconds: int) -> str:
    if not seconds:
        return ""
    sign = "+" if seconds > 0 else "-"
    return sign + _hm(abs(seconds))


def month_bounds(year: int, month: int):
    """해당 월의 (1일, 말일) 반환."""
    first = date(year, month, 1)
    if month == 12:
        nxt = date(year + 1, 1, 1)
    else:
        nxt = date(year, month + 1, 1)
    return first, nxt - timedelta(days=1)


def _daterange(d1: date, d2: date):
    cur = d1
    while cur <= d2:
        yield cur
        cur += timedelta(days=1)


def _collect(st: S.Storage, d1: date, d2: date):
    """구간 [d1, d2] 의 일별 집계와 비업무 상세를 모은다.

    토·일은 건너뛰고, 평일도 기록이나 휴가/출장 표시가 없으면 뺀다.
    """
    ivs = st.intervals()
    daily = []
    nonwork = []
    for day in _daterange(d1, d2):
        if day.weekday() >= 5:      # 토·일 제외
            continue
        adjust = st.total_adjust_seconds(day)
        leave = st.get_leave(day)
        work, nw = S.split_for_day(ivs, day, adjust, leave)
        first, last = S.day_bounds(ivs, day)
        # 기록도 휴가/출장/반차 표시도 수기 비업무도 없는 날은 제외
        if first is None and not leave and not st.manual_nonwork_seconds(day):
            continue
        stay = S.stay_seconds(ivs, day)
        daily.append({
            "day": day,
            "first": first,
            "last": last,
            "stay": stay,
            "work": work,
            "nonwork": nw,
            "leave": S.LEAVE_LABELS.get(leave, ""),
            "adjust": adjust,
            "has_data": first is not None,
        })
        for p in st.nonwork_periods(day):
            nonwork.append({
                "day": day,
                "method": S.NONWORK_REASON_LABELS.get(p["reason"], "기타"),
                "start": p["start"],
                "end": p["end"],
                "minutes": max(1, int(round(p["seconds"] / 60))),
                "ongoing": p["ongoing"],
                "note": st.get_nonwork_note(p["stop_id"]),
            })
    return daily, nonwork


def _weekly(daily):
    """일별 집계를 주(월~금) 단위로 합산 (daily 에 이미 토·일이 없다)."""
    by_monday = {}
    for row in daily:
        monday, _ = S.week_range(row["day"])
        agg = by_monday.setdefault(monday, {"monday": monday,
                                            "friday": monday + timedelta(days=4),
                                            "work": 0.0, "workdays": 0})
        agg["work"] += row["work"]
        if row["work"] > 0:
            agg["workdays"] += 1
    return [by_monday[m] for m in sorted(by_monday)]


def _write_csv(path: str, header, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def export_range(d1: date, d2: date, out_dir: str | None = None, tag: str | None = None):
    """구간 [d1, d2] 을 CSV 3종으로 내보내고, 생성된 파일 경로 dict 를 반환한다."""
    out_dir = out_dir or default_out_dir()
    os.makedirs(out_dir, exist_ok=True)
    tag = tag or (f"{d1:%Y-%m-%d}_{d2:%Y-%m-%d}")

    st = S.Storage()
    try:
        daily, nonwork = _collect(st, d1, d2)
    finally:
        st.close()
    weekly = _weekly(daily)

    paths = {
        "daily": os.path.join(out_dir, f"daily_{tag}.csv"),
        "weekly": os.path.join(out_dir, f"weekly_{tag}.csv"),
        "nonwork": os.path.join(out_dir, f"nonwork_{tag}.csv"),
    }

    _write_csv(
        paths["daily"],
        ["날짜", "요일", "출근", "퇴근", "체류", "실업무", "비업무", "휴가/출장/반차", "보정"],
        [
            [
                f"{r['day']:%Y-%m-%d}",
                WEEKDAY[r["day"].weekday()],
                f"{r['first']:%H:%M}" if r["first"] else "",
                f"{r['last']:%H:%M}" if r["last"] else "",
                _hm(r["stay"]) if r["has_data"] else "",
                _hm(r["work"]) if (r["has_data"] or r["leave"]) else "",
                _hm(r["nonwork"]) if r["has_data"] else "",
                r["leave"],
                _signed_hm(r["adjust"]),
            ]
            for r in daily
        ],
    )

    _write_csv(
        paths["weekly"],
        ["주(월~금)", "근무일수", "주간 실업무 합계", "일 평균"],
        [
            [
                f"{w['monday']:%Y-%m-%d} ~ {w['friday']:%m-%d}",
                w["workdays"],
                _hm(w["work"]),
                _hm(w["work"] / w["workdays"]) if w["workdays"] else "0:00",
            ]
            for w in weekly
        ],
    )

    _write_csv(
        paths["nonwork"],
        ["날짜", "방식", "시작", "끝", "시간(분)", "사유"],
        [
            [
                f"{n['day']:%Y-%m-%d}",
                n["method"],
                f"{n['start']:%H:%M}" if n["start"] else "",
                ("진행 중" if n["ongoing"]
                 else (f"{n['end']:%H:%M}" if n["end"] else "")),
                n["minutes"],
                n["note"],
            ]
            for n in nonwork
        ],
    )

    return paths


def export_month(year: int, month: int, out_dir: str | None = None):
    d1, d2 = month_bounds(year, month)
    return export_range(d1, d2, out_dir, tag=f"{year:04d}-{month:02d}")


def _parse_args(argv):
    p = argparse.ArgumentParser(description="근무 기록 CSV 내보내기")
    p.add_argument("--month", help="YYYY-MM (해당 월 전체)")
    p.add_argument("--from", dest="d_from", help="시작일 YYYY-MM-DD")
    p.add_argument("--to", dest="d_to", help="종료일 YYYY-MM-DD")
    p.add_argument("--out", help="출력 폴더 (기본: ~/TimeTracker_export)")
    return p.parse_args(argv)


def main(argv=None):
    # 한글 출력이 콘솔 코드페이지와 무관하게 나오도록
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    args = _parse_args(argv if argv is not None else sys.argv[1:])

    if args.d_from and args.d_to:
        d1 = date.fromisoformat(args.d_from)
        d2 = date.fromisoformat(args.d_to)
        paths = export_range(d1, d2, args.out)
    else:
        if args.month:
            y, m = args.month.split("-")
            y, m = int(y), int(m)
        else:
            today = date.today()
            y, m = today.year, today.month
        paths = export_month(y, m, args.out)

    print("내보내기 완료:")
    for k in ("daily", "weekly", "nonwork"):
        print(f"  {k}: {paths[k]}")


if __name__ == "__main__":
    main()
