"""
storage.py - 출퇴근/업무시간 데이터 저장 및 계산 (SQLite)

데이터는 OneDrive 동기화 충돌을 피하기 위해 %LOCALAPPDATA%\\TimeTracker 에 저장한다.

기본 개념:
  - 업무시간은 '활동 구간(active interval)'의 합이다.
  - 'start' 경계 이벤트: clock_in(출근), unlock(잠금해제)
  - 'stop'  경계 이벤트: lock(잠금), screensaver(화면보호기), clock_out(퇴근), shutdown(종료)
  - 활동 중에는 주기적으로 heartbeat(last_active) 를 갱신한다.
    -> 전원이 꺼져 정상 종료 이벤트를 못 남겨도, 다음 실행 시 last_active 를
       퇴근/종료 시각으로 복구할 수 있다.
"""

import os
import sqlite3
from datetime import datetime, timedelta, date, time

APP_NAME = "TimeTracker"


def data_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    d = os.path.join(base, APP_NAME)
    os.makedirs(d, exist_ok=True)
    return d


def db_path() -> str:
    return os.path.join(data_dir(), "time_tracker.db")


def _now() -> datetime:
    # 초 단위까지만 사용 (마이크로초 제거)
    return datetime.now().replace(microsecond=0)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def _parse(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S")


class Storage:
    def __init__(self, path: str | None = None):
        self.path = path or db_path()
        # 트레이/메시지펌프/heartbeat 스레드에서 함께 접근하므로 check_same_thread=False.
        # 쓰기 직렬화는 호출부(Tracker)의 Lock 으로 보장한다.
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        c = self.conn
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id     INTEGER PRIMARY KEY AUTOINCREMENT,
                ts     TEXT NOT NULL,
                kind   TEXT NOT NULL,   -- 'start' | 'stop'
                reason TEXT NOT NULL    -- clock_in/unlock/lock/screensaver/clock_out/shutdown/crash_recovery
            )
            """
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts)")
        c.execute(
            "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)"
        )
        c.commit()

    # ----- 이벤트 기록 -----
    def add_event(self, kind: str, reason: str, dt: datetime | None = None):
        dt = dt or _now()
        self.conn.execute(
            "INSERT INTO events (ts, kind, reason) VALUES (?, ?, ?)",
            (_iso(dt), kind, reason),
        )
        self.conn.commit()

    def last_event(self) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM events ORDER BY id DESC LIMIT 1"
        ).fetchone()

    # ----- heartbeat / meta -----
    def set_meta(self, key: str, value: str):
        self.conn.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self.conn.commit()

    def get_meta(self, key: str) -> str | None:
        row = self.conn.execute(
            "SELECT value FROM meta WHERE key=?", (key,)
        ).fetchone()
        return row["value"] if row else None

    def touch_heartbeat(self, dt: datetime | None = None):
        self.set_meta("last_active", _iso(dt or _now()))

    def last_active(self) -> datetime | None:
        v = self.get_meta("last_active")
        return _parse(v) if v else None

    # ----- 시작 시 비정상 종료 복구 -----
    def recover_unclean_shutdown(self) -> datetime | None:
        """
        직전 세션이 정상 종료(stop)되지 않은 채로 끝났다면
        (= 마지막 이벤트가 'start'), last_active 시각에 가상의 stop 을 넣는다.
        복구한 퇴근 추정 시각을 반환한다.
        """
        last = self.last_event()
        if last is None or last["kind"] != "start":
            return None
        la = self.last_active()
        recovered = la if la else _parse(last["ts"])
        # start 시각보다 빠르면 보정
        if recovered < _parse(last["ts"]):
            recovered = _parse(last["ts"])
        self.add_event("stop", "crash_recovery", recovered)
        return recovered

    # ----- 활동 구간 계산 -----
    def intervals(self, extend_open_to: datetime | None = None):
        """
        (start_dt, end_dt) 튜플 리스트를 반환.
        아직 닫히지 않은 구간은 extend_open_to(기본: last_active 또는 now)까지 연장.
        """
        rows = self.conn.execute(
            "SELECT ts, kind FROM events ORDER BY id ASC"
        ).fetchall()

        result = []
        open_start: datetime | None = None
        for r in rows:
            dt = _parse(r["ts"])
            if r["kind"] == "start":
                if open_start is None:
                    open_start = dt
                # 이미 열려있으면 중복 start 무시
            else:  # stop
                if open_start is not None:
                    if dt > open_start:
                        result.append((open_start, dt))
                    open_start = None

        if open_start is not None:
            end = extend_open_to or self.last_active() or _now()
            if end < open_start:
                end = open_start
            result.append((open_start, end))
        return result

    def close(self):
        self.conn.close()


# ----- 집계 헬퍼 -----
def _overlap_seconds(start: datetime, end: datetime, day: date) -> float:
    day_start = datetime.combine(day, time.min)
    day_end = day_start + timedelta(days=1)
    lo = max(start, day_start)
    hi = min(end, day_end)
    return max(0.0, (hi - lo).total_seconds())


def seconds_for_day(intervals, day: date) -> float:
    return sum(_overlap_seconds(s, e, day) for (s, e) in intervals)


def week_range(day: date):
    """day 가 포함된 주(월~일)의 (월요일, 일요일) 반환."""
    monday = day - timedelta(days=day.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday


def day_bounds(intervals, day: date):
    """해당 날짜의 첫 출근(start)과 마지막 활동(end) 시각 반환 (없으면 None)."""
    day_start = datetime.combine(day, time.min)
    day_end = day_start + timedelta(days=1)
    first = None
    last = None
    for s, e in intervals:
        if e <= day_start or s >= day_end:
            continue
        cs = max(s, day_start)
        ce = min(e, day_end)
        if first is None or cs < first:
            first = cs
        if last is None or ce > last:
            last = ce
    return first, last


def fmt_hm(seconds: float) -> str:
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    return f"{h}시간 {m}분"
