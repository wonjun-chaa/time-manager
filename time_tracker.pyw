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
from datetime import date

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

HEARTBEAT_SEC = 30          # 활동 중 마지막 활동시각 저장 주기
POLL_SEC = 2               # 화면보호기/자리비움 감지 주기
IDLE_THRESHOLD_SEC = 180   # 입력 없음 임계 기본값(초). 실제 값은 설정에서 읽음


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

    def _apply_locked(self, stop_reason: str, start_reason: str):
        """self.lock 을 보유한 상태에서 active 전환을 반영한다."""
        should_be_active = not self._effective_pause()
        if should_be_active and not self.active:
            self.storage.add_event("start", start_reason)
            self.active = True
            self.storage.touch_heartbeat()
        elif not should_be_active and self.active:
            self.storage.add_event("stop", stop_reason)
            self.active = False

    def _recompute(self, stop_reason: str, start_reason: str):
        """상태 변화에 따라 start/stop 경계 이벤트를 발생시킨다."""
        with self.lock:
            self._apply_locked(stop_reason, start_reason)

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

    def on_idle(self, is_idle: bool):
        self.idle = is_idle
        self._recompute("idle", "idle_end")

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
                self.storage.get_adjust_seconds(day),
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
    def _heartbeat_loop(self):
        import time
        prev_ss = False
        prev_idle = False
        last_hb = 0.0
        while not self._stopping:
            # 설정 갱신(대시보드에서 켜고/끄거나 시간을 바꾼 값 반영).
            # 방식이 꺼지면 여기서 유효 일시정지가 풀려 카운팅이 재개된다.
            settings = self.tracker.refresh_settings()

            # 화면보호기 상태 변화 감지 (물리적 상태는 항상 추적)
            ss = screensaver_running()
            if ss != prev_ss:
                self.tracker.on_screensaver(ss)
                prev_ss = ss

            # 자리비움(입력 없음) 감지 - 임계값은 설정에서
            threshold = settings.get("idle_threshold_sec", IDLE_THRESHOLD_SEC)
            is_idle = idle_seconds() >= threshold
            if is_idle != prev_idle:
                self.tracker.on_idle(is_idle)
                prev_idle = is_idle

            # 하트비트는 HEARTBEAT_SEC 주기로만 기록
            now = time.monotonic()
            if now - last_hb >= HEARTBEAT_SEC:
                self.tracker.heartbeat()
                last_hb = now

            # 트레이 툴팁 갱신 (호버 시 최신 시간 표시)
            self._update_tooltip()

            # POLL_SEC 동안 잘게 쪼개 대기 (종료 응답성)
            for _ in range(int(POLL_SEC * 2)):
                if self._stopping:
                    return
                time.sleep(0.5)

    # ---------- 트레이 아이콘 ----------
    def _make_image(self):
        img = Image.new("RGB", (64, 64), (28, 32, 48))
        d = ImageDraw.Draw(img)
        d.ellipse((6, 6, 58, 58), outline=(120, 200, 255), width=4)
        # 시계 바늘
        d.line((32, 32, 32, 14), fill=(120, 200, 255), width=4)
        d.line((32, 32, 46, 38), fill=(120, 200, 255), width=4)
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
