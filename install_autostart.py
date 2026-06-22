"""
install_autostart.py - 부팅(로그인) 시 자동 실행 등록/해제

등록:  py install_autostart.py
해제:  py install_autostart.py --remove
확인:  py install_autostart.py --status

HKEY_CURRENT_USER\\...\\Run 레지스트리에 등록하므로 관리자 권한이 필요 없다.
콘솔 창 없이 백그라운드 실행되도록 pythonw.exe 로 .pyw 를 실행한다.
"""

import os
import sys
import winreg

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "TimeTracker"


def pythonw_path() -> str:
    exe = sys.executable
    cand = exe.replace("python.exe", "pythonw.exe")
    return cand if os.path.exists(cand) else exe


def script_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "time_tracker.pyw")


def command() -> str:
    return f'"{pythonw_path()}" "{script_path()}"'


def install():
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
    ) as k:
        winreg.SetValueEx(k, VALUE_NAME, 0, winreg.REG_SZ, command())
    print("[OK] 자동 시작 등록 완료")
    print("     " + command())


def remove():
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as k:
            winreg.DeleteValue(k, VALUE_NAME)
        print("[OK] 자동 시작 해제 완료")
    except FileNotFoundError:
        print("[..] 등록되어 있지 않음")


def status():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            val, _ = winreg.QueryValueEx(k, VALUE_NAME)
        print("[등록됨] " + val)
    except FileNotFoundError:
        print("[미등록]")


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg == "--remove":
        remove()
    elif arg == "--status":
        status()
    else:
        install()
