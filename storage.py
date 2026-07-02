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

# 카운팅 방식 설정 (meta 테이블에 'setting:<key>' 로 저장).
# 트레이 앱과 대시보드(별도 프로세스)가 DB 를 통해 공유하므로,
# 대시보드에서 바꾼 값이 트레이 앱 폴링 주기 내에 반영된다.
SETTING_PREFIX = "setting:"
DEFAULT_SETTINGS = {
    "idle_enabled": True,         # 자리비움(미입력) 감지로 일시정지
    "idle_threshold_sec": 180,    # 미입력 임계 시간(초). 기본 3분
    "lock_enabled": True,         # 화면 잠금으로 일시정지
    "screensaver_enabled": True,  # 화면보호기로 일시정지
}


# 날짜별 비업무시간 수기 보정 (meta 테이블 'adjust:<날짜>')
ADJUST_PREFIX = "adjust:"

# 날짜별 휴가/출장 표시 (meta 'leave:<날짜>' = 'vacation'|'trip').
# 표시된 날은 실제 기록과 무관하게 LEAVE_DEFAULT_SEC(8시간)으로 채운다.
LEAVE_PREFIX = "leave:"
LEAVE_LABELS = {"vacation": "휴가", "trip": "출장"}
LEAVE_DEFAULT_SEC = 8 * 3600

# 비업무(일시정지) 구간의 사유 텍스트 (meta 'nwnote:<stop이벤트 id>').
# 구간을 일으킨 stop 이벤트의 id 에 묶어 저장하므로 날짜가 지나도 안정적으로 유지된다.
NONWORK_NOTE_PREFIX = "nwnote:"
# 일시정지를 유발한 stop reason → 카운팅 방식 한글 라벨.
NONWORK_REASON_LABELS = {
    "idle": "자리비움",
    "lock": "화면잠금",
    "screensaver": "화면보호기",
    "manual_pause": "수동 일시정지",
    "settings_change": "설정 변경",
}


def _coerce_setting(key: str, raw: str):
    """meta 에 저장된 문자열을 기본값 타입에 맞게 변환."""
    default = DEFAULT_SETTINGS[key]
    if isinstance(default, bool):
        return raw == "1"
    if isinstance(default, int):
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default
    return raw


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

    def last_event_time(self) -> datetime | None:
        """마지막으로 기록된 이벤트의 시각(datetime). 이벤트가 없으면 None.

        idle stop 을 마지막 입력 시각으로 소급 기록할 때, 직전 이벤트 ts 아래로
        내려가지 않도록 클램프하는 기준으로 쓴다(이벤트는 삽입=시간 순서 전제).
        """
        row = self.last_event()
        return _parse(row["ts"]) if row else None

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

    # ----- 카운팅 방식 설정 -----
    def get_settings(self) -> dict:
        """저장된 설정을 기본값과 병합해 dict 로 반환 (없으면 기본값)."""
        out = dict(DEFAULT_SETTINGS)
        for k in DEFAULT_SETTINGS:
            v = self.get_meta(SETTING_PREFIX + k)
            if v is not None:
                out[k] = _coerce_setting(k, v)
        return out

    def set_setting(self, key: str, value):
        if key not in DEFAULT_SETTINGS:
            raise KeyError(f"unknown setting: {key}")
        if isinstance(value, bool):
            raw = "1" if value else "0"
        elif isinstance(value, int):
            raw = str(value)
        else:
            raw = str(value)
        self.set_meta(SETTING_PREFIX + key, raw)

    # ----- 비업무시간 수기 보정 (날짜별) -----
    # meta 테이블에 'adjust:YYYY-MM-DD' = 부호 있는 초. 양수면 비업무를 늘려
    # 그만큼 업무시간을 줄이고, 음수면 반대로 작용한다.
    def get_adjust_seconds(self, day: date) -> int:
        v = self.get_meta(ADJUST_PREFIX + day.isoformat())
        try:
            return int(v) if v is not None else 0
        except (TypeError, ValueError):
            return 0

    def set_adjust_seconds(self, day: date, seconds: int):
        self.set_meta(ADJUST_PREFIX + day.isoformat(), str(int(seconds)))

    def add_adjust_seconds(self, day: date, delta: int) -> int:
        new = self.get_adjust_seconds(day) + int(delta)
        self.set_adjust_seconds(day, new)
        return new

    # ----- 휴가/출장 표시 (날짜별) -----
    def get_leave(self, day: date) -> str | None:
        v = self.get_meta(LEAVE_PREFIX + day.isoformat())
        return v if v in LEAVE_LABELS else None

    def set_leave(self, day: date, kind: str | None):
        """kind 가 'vacation'/'trip' 이면 표시, 그 외(None 등)면 표시 해제."""
        key = LEAVE_PREFIX + day.isoformat()
        if kind in LEAVE_LABELS:
            self.set_meta(key, kind)
        else:
            self.conn.execute("DELETE FROM meta WHERE key=?", (key,))
            self.conn.commit()

    # ----- 비업무(일시정지) 구간 사유 메모 -----
    def get_nonwork_note(self, stop_id) -> str:
        v = self.get_meta(NONWORK_NOTE_PREFIX + str(stop_id))
        return v or ""

    def set_nonwork_note(self, stop_id, text):
        key = NONWORK_NOTE_PREFIX + str(stop_id)
        text = (text or "").strip()
        if text:
            self.set_meta(key, text)
        else:
            self.conn.execute("DELETE FROM meta WHERE key=?", (key,))
            self.conn.commit()

    # ----- 비업무(일시정지) 구간 목록 -----
    def nonwork_periods(self, day: date):
        """해당 날짜에 업무시간에서 빠진(일시정지) 구간 목록을 반환.

        각 항목 dict: stop_id, start, end, seconds, reason, ongoing.
          - 활동 구간 사이의 공백이 곧 비업무 구간이고, 그 사유(카운팅 방식)는
            공백을 시작시킨 stop 이벤트의 reason 이다(idle/lock/screensaver...).
          - 체류시간(첫~마지막 활동) 안의 공백만 포함한다(출근 전/퇴근 후 제외).
          - 현재 일시정지 중이면 진행 중(ongoing=True) 구간을 now 까지로 추가한다.
        stop_id 는 사유 메모(get/set_nonwork_note)의 안정적 키로 쓰인다.
        """
        rows = self.conn.execute(
            "SELECT id, ts, kind, reason FROM events ORDER BY id ASC"
        ).fetchall()
        # (start_dt, end_dt, stop_id, stop_reason); 마지막 열린 구간은 stop_id=None.
        seq = []
        open_start = None
        for r in rows:
            dt = _parse(r["ts"])
            if r["kind"] == "start":
                if open_start is None:
                    open_start = dt
            else:  # stop
                if open_start is not None:
                    seq.append((open_start, dt, r["id"], r["reason"]))
                    open_start = None

        # 아직 열려 있는(현재 업무 중인) 구간도 페어링에 포함해야, 잠깐 멈췄다
        # 다시 일하는 동안 생긴 공백(마지막 닫힌 구간 ↔ 열린 구간 사이)을 놓치지 않는다.
        if open_start is not None:
            end = self.last_active() or _now()
            if end < open_start:
                end = open_start
            seq.append((open_start, end, None, None))

        plain = [(s, e) for (s, e, _, _) in seq]
        first, last = day_bounds(plain, day)
        periods = []
        if first is None:
            return periods

        for i in range(len(seq) - 1):
            g_start = seq[i][1]
            g_end = seq[i + 1][0]
            if g_end <= g_start:
                continue
            if g_start < first or g_end > last:
                continue  # 체류시간 밖은 비업무가 아님
            periods.append({
                "stop_id": seq[i][2],          # 공백을 시작시킨 stop 이벤트
                "start": g_start,
                "end": g_end,
                "seconds": (g_end - g_start).total_seconds(),
                "reason": seq[i][3],
                "ongoing": False,
            })

        # 현재 일시정지 중(마지막 이벤트가 stop, 아직 재개 전)이면 진행 중 구간 추가
        if rows and rows[-1]["kind"] == "stop":
            last_stop = rows[-1]
            if last_stop["reason"] in NONWORK_REASON_LABELS:
                g_start = _parse(last_stop["ts"])
                now = _now()
                if g_start.date() == day and now > g_start and g_start >= first:
                    periods.append({
                        "stop_id": last_stop["id"],
                        "start": g_start,
                        "end": now,
                        "seconds": (now - g_start).total_seconds(),
                        "reason": last_stop["reason"],
                        "ongoing": True,
                    })
        return periods

    def ongoing_pause_now(self, day: date) -> datetime | None:
        """현재 일시정지 중이면(마지막 이벤트가 비업무성 stop) now 를 반환.

        진행 중 일시정지를 체류/비업무에 실시간 반영하기 위한 기준 시각으로,
        해당 날짜(day)에 시작된 일시정지만 인정한다 (nonwork_periods 와 같은 기준).
        """
        last = self.last_event()
        if last is None or last["kind"] != "stop":
            return None
        if last["reason"] not in NONWORK_REASON_LABELS:
            return None
        g_start = _parse(last["ts"])
        now = _now()
        if g_start.date() != day or now <= g_start:
            return None
        return now

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


def stay_seconds(intervals, day: date, until: datetime | None = None) -> float:
    """해당 날짜의 체류시간(첫 활동~마지막 활동) 초. 기록 없으면 0.

    until 이 주어지면(진행 중 일시정지의 now) 마지막 활동을 그 시각까지 연장해
    일시정지 중에도 체류·비업무가 실시간으로 늘게 한다. 자정은 넘지 않는다.
    """
    first, last = day_bounds(intervals, day)
    if first is None:
        return 0.0
    if until is not None:
        day_end = datetime.combine(day, time.min) + timedelta(days=1)
        last = max(last, min(until, day_end))
    return max(0.0, (last - first).total_seconds())


def split_for_day(intervals, day: date, adjust_sec: float = 0.0,
                  leave_kind: str | None = None,
                  pause_until: datetime | None = None):
    """해당 날짜의 (실 업무초, 비업무초) 를 보정값을 반영해 반환.

    휴가/출장으로 표시된 날(leave_kind)은 실제 기록과 무관하게
    (8시간, 0) 으로 채운다.

    그 외에는 비업무 = 체류 - 업무. 수기 보정(adjust_sec, 부호 있음)은 비업무에
    더해지고, 그만큼 업무에서 빠진다. 업무+비업무 = 체류 불변식을 유지하며
    [0, 체류] 범위로 클립한다.

    pause_until 은 진행 중 일시정지를 실시간 반영하기 위한 연장 시각.
    """
    if leave_kind in LEAVE_LABELS:
        return float(LEAVE_DEFAULT_SEC), 0.0
    base_work = seconds_for_day(intervals, day)
    stay = stay_seconds(intervals, day, pause_until)
    base_nonwork = max(0.0, stay - base_work)
    nonwork = min(max(0.0, base_nonwork + adjust_sec), stay)
    work = stay - nonwork
    return work, nonwork


def fmt_hm(seconds: float) -> str:
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    # 0시간은 표기하지 않는다 (예: 34분, 2시간 5분)
    return f"{h}시간 {m}분" if h else f"{m}분"


def fmt_dur(seconds: float) -> str:
    """짧은 구간까지 정직하게 표기한다.

    60초 미만은 '초' 단위로(예: 45초, 0이면 0초), 60초 이상은 fmt_hm 에 위임한다.
    비업무 구간의 짧은 잠금/자리비움이 '0분' 으로 뭉개지지 않게 하기 위함.
    """
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}초"
    return fmt_hm(seconds)
