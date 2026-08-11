"""
time_tracker.pyw - 출퇴근/업무시간 자동 기록 트레이 앱

동작:
  - 실행(부팅/로그인) 시: 출근(clock_in) 기록, 업무시간 카운팅 시작
  - 화면 잠금(Win+L) / 화면보호기 작동 시: 카운팅 일시정지
  - 잠금 해제 / 화면보호기 종료 시: 카운팅 재개
  - 시스템 종료/로그오프 시: 퇴근(clock_out) 기록
  - 비정상 종료(전원 차단 등) 시: 다음 실행 때 마지막 활동시각으로 퇴근 복구

트레이 아이콘 메뉴에서 현황 보기 / 수동 일시정지 / 퇴근 후 종료가 가능하다.

.pyw 확장자 + pythonw.exe 로 실행하면 콘솔 창 없이 백그라운드로 동작한다.
"""

import os
import sys
import threading
import subprocess
import traceback
from datetime import date, datetime

import ctypes

import win32con
import win32gui
import win32ts

from PIL import Image, ImageDraw
import pystray

import storage as S


# ---- Windows 상수 ----
WM_WTSSESSION_CHANGE = 0x02B1
WTS_SESSION_LOCK = 0x7
WTS_SESSION_UNLOCK = 0x8
NOTIFY_FOR_THIS_SESSION = 0
SPI_GETSCREENSAVERRUNNING = 0x0072

# MessageBoxW 플래그 (목표 달성 팝업)
MB_OK = 0x00000000
MB_ICONINFORMATION = 0x00000040
MB_SETFOREGROUND = 0x00010000
MB_TOPMOST = 0x00040000

HEARTBEAT_SEC = 10          # 활동 중 마지막 활동시각 저장 주기
POLL_SEC = 2               # 화면보호기/자리비움 감지 주기
IDLE_THRESHOLD_SEC = 180   # 입력 없음 임계 기본값(초). 실제 값은 설정에서 읽음

ERROR_LOG_MAX_BYTES = 256 * 1024   # 오류 로그가 무한정 커지지 않게 넘으면 새로 쓴다


def log_path() -> str:
    return os.path.join(S.data_dir(), "tracker_error.log")


def log_error(where: str):
    """폴링 스레드에서 삼킨 예외를 파일에 남긴다.

    pythonw 로 돌아 콘솔이 없으므로 stderr 는 사라진다. 예외를 삼키고 루프를
    계속 돌리되, 무슨 일이 있었는지는 %LOCALAPPDATA%\\TimeTracker 에 남긴다.
    """
    try:
        path = log_path()
        mode = "a"
        try:
            if os.path.getsize(path) > ERROR_LOG_MAX_BYTES:
                mode = "w"
        except OSError:
            pass
        with open(path, mode, encoding="utf-8") as f:
            f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {where}\n")
            f.write(traceback.format_exc())
            f.write("\n")
    except Exception:
        pass   # 로그조차 실패해도 앱은 계속 돈다


def screensaver_running() -> bool:
    running = ctypes.c_int(0)
    ctypes.windll.user32.SystemParametersInfoW(
        SPI_GETSCREENSAVERRUNNING, 0, ctypes.byref(running), 0
    )
    return bool(running.value)


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


def idle_seconds() -> float:
    """마지막 키보드/마우스 입력 이후 경과한 초 (시스템 전체 기준)."""
    info = _LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(info)
    ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info))
    tick = ctypes.windll.kernel32.GetTickCount() & 0xFFFFFFFF
    elapsed_ms = (tick - info.dwTime) & 0xFFFFFFFF
    return elapsed_ms / 1000.0


class Tracker:
    """업무 활동 상태 머신 + DB 기록."""

    def __init__(self):
        self.lock = threading.Lock()
        self.storage = S.Storage()
        # 물리적 상태(실제로 잠겼는지 등) - 켜고 끄는 여부와 무관하게 그대로 기록.
        self.locked = False
        self.screensaver = False
        self.idle = False
        self.manual_pause = False
        self.active = False
        # 카운팅 방식 설정 (대시보드에서 변경 가능, 폴링 시 갱신)
        self.settings = self.storage.get_settings()

        # 직전 비정상 종료 복구
        recovered = self.storage.recover_unclean_shutdown()
        self.recovered_at = recovered

        # 출근 기록
        with self.lock:
            self.storage.add_event("start", "clock_in")
            self.active = True
            self.storage.touch_heartbeat()

    def _effective_pause(self) -> bool:
        """현재 설정을 반영한 '유효 일시정지' 여부.

        물리적으로 잠겨 있어도 해당 감지 방식이 꺼져 있으면 일시정지로 치지 않는다.
        수동 일시정지는 설정과 무관하게 항상 적용된다.
        """
        s = self.settings
        return (
            self.manual_pause
            or (self.locked and s["lock_enabled"])
            or (self.screensaver and s["screensaver_enabled"])
            or (self.idle and s["idle_enabled"])
        )

    def _apply_locked(self, stop_reason: str, start_reason: str,
                      stop_dt=None):
        """self.lock 을 보유한 상태에서 active 전환을 반영한다.

        stop_dt 가 주어지면(자리비움 소급 등) stop 이벤트를 그 시각으로 기록한다.
        단, 직전 이벤트 ts 보다 앞서면 안 되므로(삽입=시간 순서 전제) 그 값으로
        클램프한다. start 경로는 stop_dt 와 무관하게 기존 그대로.
        """
        should_be_active = not self._effective_pause()
        if should_be_active and not self.active:
            self.storage.add_event("start", start_reason)
            self.active = True
            self.storage.touch_heartbeat()
        elif not should_be_active and self.active:
            if stop_dt is not None:
                last_ts = self.storage.last_event_time()
                if last_ts is not None and stop_dt < last_ts:
                    stop_dt = last_ts
            self.storage.add_event("stop", stop_reason, stop_dt)
            self.active = False

    def _recompute(self, stop_reason: str, start_reason: str, stop_dt=None):
        """상태 변화에 따라 start/stop 경계 이벤트를 발생시킨다."""
        with self.lock:
            self._apply_locked(stop_reason, start_reason, stop_dt)

    def refresh_settings(self) -> dict:
        """설정을 DB 에서 다시 읽어 반영한다(대시보드에서 바뀐 값 포함).

        켜짐→꺼짐 등으로 유효 일시정지 상태가 바뀌면 경계 이벤트를 발생시킨다.
        갱신된 설정 dict 를 반환한다.
        """
        with self.lock:
            self.settings = self.storage.get_settings()
            self._apply_locked("settings_change", "settings_change")
            return dict(self.settings)

    # 이벤트 핸들러
    def on_lock(self):
        self.locked = True
        self._recompute("lock", "unlock")

    def on_unlock(self):
        self.locked = False
        self._recompute("lock", "unlock")

    def on_screensaver(self, running: bool):
        self.screensaver = running
        self._recompute("screensaver", "screensaver_end")

    def on_idle(self, is_idle: bool, idle_elapsed: float = 0.0):
        """자리비움 상태 전환을 반영한다.

        idle 진입 시엔 실제로 자리를 비운 시작(=마지막 입력 시각 ≈ now-idle_elapsed)
        으로 stop 을 소급 기록한다. 그래야 감지 지연(threshold)만큼의 자리비움이
        업무시간에 잘못 포함되지 않고, 짧은 비업무 구간도 정직하게 남는다.
        """
        self.idle = is_idle
        stop_dt = None
        if is_idle and idle_elapsed > 0:
            from datetime import datetime, timedelta
            stop_dt = (datetime.now() - timedelta(seconds=idle_elapsed)).replace(
                microsecond=0
            )
        self._recompute("idle", "idle_end", stop_dt)

    def set_manual_pause(self, value: bool):
        self.manual_pause = value
        self._recompute("manual_pause", "manual_resume")

    def clock_out(self, reason: str = "clock_out"):
        with self.lock:
            if self.active:
                self.storage.add_event("stop", reason)
                self.active = False

    def heartbeat(self):
        with self.lock:
            if self.active:
                self.storage.touch_heartbeat()

    def summary(self):
        """(오늘 업무초, 이번주 업무초) - 수기 보정/휴가·출장 반영, 주간은 월~금만."""
        from datetime import timedelta
        ivs = self.storage.intervals()
        td = date.today()
        monday, _ = S.week_range(td)

        def work(day):
            return S.split_for_day(
                ivs, day,
                self.storage.total_adjust_seconds(day),
                self.storage.get_leave(day),
            )[0]

        today = work(td)
        week = sum(work(monday + timedelta(days=i)) for i in range(5))  # 월~금
        return today, week

    def today_seconds(self) -> float:
        return self.summary()[0]

    def status_text(self) -> str:
        today, week = self.summary()
        s = self.settings
        if self.manual_pause:
            state = "수동 일시정지"
        elif self.locked and s["lock_enabled"]:
            state = "잠금(일시정지)"
        elif self.screensaver and s["screensaver_enabled"]:
            state = "화면보호기(일시정지)"
        elif self.idle and s["idle_enabled"]:
            state = "자리비움(일시정지)"
        else:
            state = "업무 중"
        return (
            f"상태: {state}\n"
            f"오늘: {S.fmt_hm(today)}\n"
            f"이번 주: {S.fmt_hm(week)}"
        )


class App:
    def __init__(self):
        self.tracker = Tracker()
        self.hwnd = None
        self.icon = None
        self._stopping = False
        # 폴링 상태 (_heartbeat_loop / _poll_once 공유)
        self._prev_ss = False
        self._prev_idle = False
        self._last_hb = 0.0

    # ---------- 숨김 창 (세션/종료 이벤트 수신) ----------
    def _create_window(self):
        message_map = {
            WM_WTSSESSION_CHANGE: self._on_session_change,
            win32con.WM_QUERYENDSESSION: self._on_query_end,
            win32con.WM_ENDSESSION: self._on_end_session,
            win32con.WM_DESTROY: self._on_destroy,
        }
        wc = win32gui.WNDCLASS()
        wc.lpszClassName = "TimeTrackerHiddenWnd"
        wc.lpfnWndProc = message_map
        class_atom = win32gui.RegisterClass(wc)
        self.hwnd = win32gui.CreateWindow(
            class_atom, "TimeTracker", 0, 0, 0, 0, 0, 0, 0, 0, None
        )
        win32ts.WTSRegisterSessionNotification(self.hwnd, NOTIFY_FOR_THIS_SESSION)

    def _on_session_change(self, hwnd, msg, wparam, lparam):
        if wparam == WTS_SESSION_LOCK:
            self.tracker.on_lock()
        elif wparam == WTS_SESSION_UNLOCK:
            self.tracker.on_unlock()
        self._update_tooltip()
        return 0

    def _update_tooltip(self):
        """트레이 아이콘 툴팁(마우스 호버 시 표시)을 현재 상태로 갱신."""
        if self.icon:
            try:
                self.icon.title = self.tracker.status_text()
            except Exception:
                pass

    def _on_query_end(self, hwnd, msg, wparam, lparam):
        # 종료를 허용
        return 1

    def _on_end_session(self, hwnd, msg, wparam, lparam):
        if wparam:
            self.tracker.clock_out("shutdown")
        return 0

    def _on_destroy(self, hwnd, msg, wparam, lparam):
        try:
            win32ts.WTSUnRegisterSessionNotification(hwnd)
        except Exception:
            pass
        win32gui.PostQuitMessage(0)
        return 0

    # ---------- heartbeat + 화면보호기 폴링 ----------
    def _poll_once(self):
        """폴링 1회분. 예외는 호출부(_heartbeat_loop)에서 잡는다."""
        import time
        # 설정 갱신(대시보드에서 켜고/끄거나 시간을 바꾼 값 반영).
        # 방식이 꺼지면 여기서 유효 일시정지가 풀려 카운팅이 재개된다.
        settings = self.tracker.refresh_settings()

        # 화면보호기 상태 변화 감지 (물리적 상태는 항상 추적)
        ss = screensaver_running()
        if ss != self._prev_ss:
            self.tracker.on_screensaver(ss)
            self._prev_ss = ss

        # 자리비움(입력 없음) 감지 - 임계값은 설정에서
        threshold = settings.get("idle_threshold_sec", IDLE_THRESHOLD_SEC)
        idle_sec = idle_seconds()
        is_idle = idle_sec >= threshold
        if is_idle != self._prev_idle:
            # 경과초를 넘겨 stop 을 마지막 입력 시각으로 소급 기록하게 한다.
            self.tracker.on_idle(is_idle, idle_sec)
            self._prev_idle = is_idle

        # 하트비트는 HEARTBEAT_SEC 주기로만 기록
        now = time.monotonic()
        if now - self._last_hb >= HEARTBEAT_SEC:
            self.tracker.heartbeat()
            self._last_hb = now

        # 목표 시간 달성 알림 - 설정에서 끄면 건너뛴다
        if settings.get("goal_alarm_enabled"):
            self._check_goal(settings.get("goal_sec", S.DAILY_GOAL_SEC))

        # 트레이 툴팁 갱신 (호버 시 최신 시간 표시)
        self._update_tooltip()

    def _heartbeat_loop(self):
        """폴링 스레드. 예외가 나도 절대 죽지 않는다.

        여기서 예외가 새어나가면 스레드가 조용히 끝나 하트비트/자리비움 감지가
        영구히 멈추는데, 트레이 아이콘은 멀쩡해서 알아채기 어렵다(대시보드의
        '최근 활동'만 특정 시각에 멈춰 보인다). 그래서 한 회차를 통째로 감싸고
        같은 오류가 반복되면 로그만 한 번 남긴 뒤 계속 돈다.
        """
        import time
        self._prev_ss = False
        self._prev_idle = False
        self._last_hb = 0.0
        last_err = None
        while not self._stopping:
            try:
                self._poll_once()
                last_err = None
            except Exception as e:
                sig = f"{type(e).__name__}: {e}"
                if sig != last_err:      # 같은 오류가 매 회차 반복되면 한 번만 기록
                    log_error("_heartbeat_loop")
                    last_err = sig

            # POLL_SEC 동안 잘게 쪼개 대기 (종료 응답성)
            for _ in range(int(POLL_SEC * 2)):
                if self._stopping:
                    return
                time.sleep(0.5)

    # ---------- 트레이 아이콘 ----------
    def _make_image(self):
        # 대시보드와 같은 톤(틸 원 + 흰 바늘). 트레이는 밝은/어두운 배경 모두
        # 가능하므로 채운 원으로 그려 어디서든 보이게 한다.
        img = Image.new("RGB", (64, 64), (237, 240, 237))
        d = ImageDraw.Draw(img)
        d.ellipse((4, 4, 60, 60), fill=(23, 118, 107))
        # 시계 바늘
        d.line((32, 32, 32, 15), fill=(255, 255, 255), width=4)
        d.line((32, 32, 45, 39), fill=(255, 255, 255), width=4)
        return img

    def _report_dir(self):
        return os.path.dirname(os.path.abspath(__file__))

    def _show_report(self, icon, item):
        # GUI 대시보드(dashboard.py)를 콘솔 없이 실행
        dashboard_py = os.path.join(self._report_dir(), "dashboard.py")
        try:
            subprocess.Popen([sys.executable, dashboard_py], close_fds=True)
        except Exception as e:
            self._notify(f"현황 실행 실패: {e}")

    def _show_status(self, icon, item):
        self._notify(self.tracker.status_text())

    def _notify(self, msg, title="TimeTracker"):
        try:
            if self.icon:
                self.icon.notify(msg, title)
        except Exception:
            pass

    def _goal_popup(self, worked: int, goal_sec: int):
        """목표 달성 알림을 대시보드와 같은 디자인의 토스트로 띄운다.

        notify.py 를 **별도 프로세스**로 실행한다: 이 앱의 메인 스레드는
        PumpMessages, 다른 스레드는 pystray/폴링이라 여기서 Tk 를 띄울 자리가
        없고, 프로세스를 나누면 팝업이 죽어도 트레이 앱은 멀쩡하다.
        실패하면 예전처럼 기본 MessageBox 로 떨어진다.
        """
        notify_py = os.path.join(self._report_dir(), "notify.py")
        try:
            subprocess.Popen(
                [sys.executable, notify_py, str(int(worked)), str(int(goal_sec))],
                close_fds=True,
            )
        except Exception:
            log_error("goal_popup")
            self._popup(
                f"오늘 실 업무시간 {S.fmt_hm(goal_sec)}을 채웠습니다.\n\n"
                f"현재 {S.fmt_hm(worked)}",
                "업무시간 달성",
            )

    def _popup(self, msg, title="TimeTracker"):
        """모달 팝업(MessageBox). 확인을 누를 때까지 떠 있으므로,
        폴링 스레드가 막히지 않도록 항상 별도 스레드에서 띄운다.
        (지금은 notify.py 실행이 실패했을 때의 대비책으로만 쓴다.)"""
        def show():
            try:
                ctypes.windll.user32.MessageBoxW(
                    0, msg, title,
                    MB_OK | MB_ICONINFORMATION | MB_SETFOREGROUND | MB_TOPMOST,
                )
            except Exception:
                pass
        threading.Thread(target=show, daemon=True).start()

    def _check_goal(self, goal_sec: int):
        """오늘 실 업무시간이 목표를 넘으면 하루 한 번 팝업으로 알린다.

        표식(goal_notified)을 먼저 보고 빠져나가므로, 한 번 뜬 뒤에는 폴링마다
        업무시간을 다시 집계하지 않는다. 목표 시간은 설정에서 온다.
        """
        today = date.today()
        st = self.tracker.storage
        with self.tracker.lock:
            if st.goal_notified(today):
                return
            worked = self.tracker.summary()[0]
            if worked < goal_sec:
                return
            st.set_goal_notified(today)
        self._goal_popup(worked, goal_sec)

    def _toggle_pause(self, icon, item):
        new_value = not self.tracker.manual_pause
        self.tracker.set_manual_pause(new_value)
        self._notify("수동 일시정지됨" if new_value else "업무 재개됨")

    def _is_paused(self, item):
        return self.tracker.manual_pause

    def _clock_out_quit(self, icon, item):
        self.tracker.clock_out("clock_out")
        self._notify(f"퇴근 처리 완료\n오늘: {S.fmt_hm(self.tracker.today_seconds())}")
        self._quit(icon, item)

    def _quit(self, icon, item):
        self._stopping = True
        self.tracker.clock_out("clock_out")
        if self.icon:
            self.icon.stop()
        if self.hwnd:
            win32gui.PostMessage(self.hwnd, win32con.WM_DESTROY, 0, 0)

    def _build_menu(self):
        return pystray.Menu(
            pystray.MenuItem("현황 보기 (일일/주간)", self._show_report, default=True),
            pystray.MenuItem("현재 상태 알림", self._show_status),
            pystray.MenuItem(
                "수동 일시정지", self._toggle_pause, checked=self._is_paused
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("퇴근 처리 후 종료", self._clock_out_quit),
            pystray.MenuItem("종료", self._quit),
        )

    # ---------- 실행 ----------
    def run(self):
        self._create_window()

        # heartbeat/화면보호기 스레드
        threading.Thread(target=self._heartbeat_loop, daemon=True).start()

        # 트레이 아이콘 (별도 스레드)
        self.icon = pystray.Icon(
            "TimeTracker",
            self._make_image(),
            self.tracker.status_text(),
            self._build_menu(),
        )
        threading.Thread(target=self.icon.run, daemon=True).start()

        if self.tracker.recovered_at:
            self._notify(
                f"이전 세션 퇴근시각 복구: {self.tracker.recovered_at:%m-%d %H:%M}"
            )

        # 메인 스레드: 윈도우 메시지 펌프 (잠금/종료 이벤트 수신)
        win32gui.PumpMessages()


if __name__ == "__main__":
    App().run()
