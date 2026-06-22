# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Windows-only desktop app that auto-records work hours (출퇴근/업무시간). It runs as a system-tray app that starts on login, logs clock-in, pauses counting on screen lock / screensaver / 3-minute idle, resumes on return, and records clock-out on shutdown (with heartbeat-based recovery for hard power-offs). Korean is the UI language.

## Running & commands

There is **no build, lint, or test framework**. It is plain Python 3.13 + standard library + three packages (`pywin32`, `pystray`, `pillow`).

- **`python` on this machine is the Microsoft Store stub and does not execute code — always use the `py` launcher.** Real interpreter: `C:\Users\chaa8\AppData\Local\Programs\Python\Python313-32\` (`python.exe` / `pythonw.exe`).
- Install deps + register autostart + launch: double-click `setup.bat` (or `py -m pip install -r requirements.txt`).
- Run the tray app windowless: `pythonw time_tracker.pyw` (full path to `pythonw.exe` if not on PATH — it usually isn't).
- GUI dashboard standalone: `py dashboard.py`. Text report: `py report.py [--date YYYY-MM-DD]`.
- Autostart: `py install_autostart.py [--status|--remove]` (writes `HKCU\...\Run`, no admin needed).

### Manual smoke testing (the established pattern)

Data lives at `%LOCALAPPDATA%\TimeTracker\time_tracker.db`. To exercise code without polluting real records, **override `LOCALAPPDATA` to a temp dir** for the test process, populate events via `storage.Storage` with explicit timestamps, then run/launch. For GUI checks, launch with `pythonw`, `Start-Sleep`, capture the screen with .NET `System.Drawing` (`CopyFromScreen`), then `Stop-Process`. Always restore `LOCALAPPDATA` and clean the temp dir afterward.

## Architecture

Four cooperating pieces; the non-obvious logic is the **active-interval model** and the **threading model**.

- **`storage.py`** — the source of truth. SQLite `events` table holds `start`/`stop` boundary rows (reason: clock_in/unlock/lock/screensaver/idle/clock_out/shutdown/crash_recovery), plus a `meta` table holding `last_active` (the heartbeat). Work time = sum of paired start→stop intervals. Key behaviors:
  - `intervals()` walks events **by id (insertion = chronological order)**, pairing starts with stops; a still-open trailing interval is extended to `last_active` (so a crashed/running session reports correctly).
  - `recover_unclean_shutdown()` runs at startup: if the last event is a dangling `start`, it inserts a synthetic `stop` at `last_active` — this is how clock-out is recovered after a hard power-off.
  - `seconds_for_day` clips intervals to a date so totals **split correctly across midnight**; `week_range` is Monday–Sunday.
  - Connection uses `check_same_thread=False`; writes are serialized by the caller's lock (see below), not by SQLite.

- **`time_tracker.pyw`** — the tray app. Contains two classes:
  - `Tracker` = the state machine + DB writer. Flags `locked`, `screensaver`, `idle`, `manual_pause`; `_recompute()` emits a `start` or `stop` only on active↔inactive transitions (active = none of the flags set). All DB access is under `self.lock`. Counting resumes only when **all** pause conditions clear.
  - `App` = OS integration. Creates a **hidden win32 message window** to receive `WM_WTSSESSION_CHANGE` (lock/unlock via `WTSRegisterSessionNotification`) and `WM_ENDSESSION` (shutdown → clock_out). A background poll loop (`_heartbeat_loop`, every `POLL_SEC`) detects screensaver (`SPI_GETSCREENSAVERRUNNING`) and idle (`GetLastInputInfo` ≥ `IDLE_THRESHOLD_SEC`), writes the heartbeat every `HEARTBEAT_SEC`, and refreshes the tray tooltip.
  - **Threading model (important):** main thread runs `win32gui.PumpMessages()` (owns the hidden window); the heartbeat poll loop and the `pystray` icon each run on their own daemon threads. Quitting posts `WM_DESTROY` → `PostQuitMessage`.

- **`dashboard.py`** — tkinter GUI (dark theme). Built **once**, then `_refresh()` updates label text and canvas item coords/colors in place every 5 s (no destroy/recreate — that was a deliberate fix for flicker). Window auto-sizes to required content via `winfo_reqwidth/reqheight` so labels are never clipped regardless of font/DPI. Launched by the tray menu via `subprocess.Popen([sys.executable, ...])` (sys.executable is pythonw → no console).

- **`report.py`** — CLI/text equivalent of the dashboard, used as a fallback. Reconfigures stdout to UTF-8 so Korean survives any console codepage.

## Windows-specific gotchas (learned the hard way)

- **`.bat` files must be ASCII-only.** Korean text in a batch file misparses under the Korean console codepage (949) — some UTF-8 bytes look like `|`/`&` and split `echo` lines into bogus commands. Keep batch messages in English; let Python handle Korean output.
- `pythonw`/`python` are frequently **not on PATH**; resolve the real path via the `py` launcher (`py -c "import sys,os; print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))"`) — `setup.bat` does this.
- The DB intentionally lives in `%LOCALAPPDATA%`, **not** the repo dir, to avoid OneDrive sync conflicts (the working tree is inside a OneDrive folder).
