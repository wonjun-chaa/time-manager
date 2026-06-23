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
  - **Work/non-work split + manual correction.** `stay_seconds` = first activity → last activity for a day; `split_for_day(intervals, day, adjust_sec, leave_kind)` returns `(work, nonwork)` holding the invariant **work + nonwork = stay**, clipped to `[0, stay]`. The per-day signed correction is stored in `meta` under `adjust:YYYY-MM-DD` seconds (`get/set/add_adjust_seconds`): a **positive** value moves time from work into non-work (and vice-versa). All callers (dashboard, tray summary, report) go through `split_for_day`, so a correction shows up everywhere consistently.
  - **Vacation / business-trip (휴가/출장).** Stored in `meta` under `leave:YYYY-MM-DD` = `vacation`|`trip` (`get_leave`/`set_leave`, cleared by deleting the row). When `split_for_day` gets a `leave_kind`, it **overrides everything and returns `(LEAVE_DEFAULT_SEC=8h, 0)`** — the day counts as a full 8-hour workday regardless of recorded events. `LEAVE_LABELS` maps the keys to Korean.
  - Connection uses `check_same_thread=False`; writes are serialized by the caller's lock (see below), not by SQLite.
  - **Counting-method settings** live in the same `meta` table under `setting:<key>` keys (`get_settings`/`set_setting`, defaults in `DEFAULT_SETTINGS`): `idle_enabled`, `idle_threshold_sec`, `lock_enabled`, `screensaver_enabled`. Stored as strings, coerced back to bool/int on read. This is the **IPC channel** between the dashboard (which edits them) and the running tray app (which re-reads them each poll).

- **`time_tracker.pyw`** — the tray app. Contains two classes:
  - `Tracker` = the state machine + DB writer. Flags `locked`, `screensaver`, `idle`, `manual_pause` track **physical** state (set regardless of settings); `_effective_pause()` then ANDs each with its `*_enabled` setting (manual pause always counts) so a disabled method never pauses. `_recompute()`/`_apply_locked()` emit a `start` or `stop` only on active↔inactive transitions. `refresh_settings()` reloads settings from the DB and reconciles (toggling a method off mid-pause resumes counting, emitting a `settings_change` boundary). All DB access — including the settings read — is under `self.lock`.
  - `App` = OS integration. Creates a **hidden win32 message window** to receive `WM_WTSSESSION_CHANGE` (lock/unlock via `WTSRegisterSessionNotification`) and `WM_ENDSESSION` (shutdown → clock_out). A background poll loop (`_heartbeat_loop`, every `POLL_SEC`) calls `refresh_settings()`, detects screensaver (`SPI_GETSCREENSAVERRUNNING`) and idle (`GetLastInputInfo` ≥ the **configurable** `idle_threshold_sec`), writes the heartbeat every `HEARTBEAT_SEC`, and refreshes the tray tooltip.
  - **Threading model (important):** main thread runs `win32gui.PumpMessages()` (owns the hidden window); the heartbeat poll loop and the `pystray` icon each run on their own daemon threads. Quitting posts `WM_DESTROY` → `PostQuitMessage`.

- **`dashboard.py`** — tkinter GUI (dark theme). A lightweight **tab bar** (`_build_tabs`/`_show_tab`, plain `tk.Label` buttons toggled via `pack`/`pack_forget` — no `ttk.Notebook`, to keep the dark theme) switches between two pre-built frames: **현황** (the dashboard) and **설정** (counting-method toggles + idle-minutes spinbox). The dashboard is built **once**, then `_refresh()` updates label text and canvas item coords/colors in place every 5 s (no destroy/recreate — that was a deliberate fix for flicker). The settings tab is **edit-gated**: it opens read-only with toggles/stepper disabled and an **편집** button; `_enter_edit` snapshots current values and unlocks the controls (showing **저장**/**취소**); **저장** (`_save_edit`→`_save_settings`) writes all four keys via `set_setting`, **취소** (`_cancel_edit`) restores the snapshot. Nothing persists until 저장, and the tray app picks it up within `POLL_SEC`. The weekly chart shows **weekdays only (월~금, `WEEKDAYS_SHOWN=5`)** — Sat/Sun were dropped from the chart, weekly total, and average (the 오늘 card still reflects today even on a weekend). A collapsible **휴가 · 출장** panel under the chart has one button per weekday that cycles 근무→휴가→출장 (`_cycle_leave` → `set_leave`); marked days render with `VAC`/`TRIP` colours and an "휴가/출장 8시간" label. The 현황 tab's today card shows a **비업무** (non-work) cell beside 체류시간 and a **collapsible** manual-correction section (`_build_adjust`): a button-like full-width toggle bar (▼/▲ chevron + 펼치기/접기 label + `HOVER` colour on mouse-over; `_toggle_adjust` packs/forgets `adjust_body`, `_refit_height` resizes the window) that's collapsed by default. Inside, a number stepper + `＋/−/초기화` buttons adjust today's correction. `_apply_adjust` **clamps the stored adjustment to `[-base_nonwork, +base_work]`** so non-work can never go below 0 (subtract limit = current non-work) nor work below 0 (add limit = current work) — keeping the displayed correction linked to reality. Both number inputs use the custom **`Stepper`** widget (replaces `tk.Spinbox`, whose tiny arrows + blinking caret were poor UX): `− [entry] +` (small flat buttons), click/focus selects-all, non-blinking caret (`insertofftime=0`) that disappears on commit (Enter / button / focus-out → `_defocus`), `value()` clamps to `[lo, hi]`. The 설정 idle field passes `on_commit=_save_settings` so it persists on commit (not per keystroke); `set_enabled` greys it out when idle detection is off. Each setting's on/off uses a custom **`ToggleSwitch`** (replaces the plain `tk.Checkbutton`): a rounded pill + sliding knob rendered with **Pillow at 4× then LANCZOS-downscaled** (tk Canvas has no anti-aliasing, so a Canvas-drawn circle looked jagged) into a cached `ImageTk.PhotoImage` on a `tk.Label`; muted `TOGGLE_ON/OFF/KNOB` colours (plus dimmed `*_DIS` variants for the disabled/locked state via `set_enabled`). It flips the bound `BooleanVar` only when enabled; a `var` trace re-renders on external changes. Fonts/paddings were tuned down to keep the window short. Window auto-sizes to required content via `winfo_reqwidth/reqheight` so labels are never clipped regardless of font/DPI. Launched by the tray menu via `subprocess.Popen([sys.executable, ...])` (sys.executable is pythonw → no console).

- **`report.py`** — CLI/text equivalent of the dashboard, used as a fallback. Reconfigures stdout to UTF-8 so Korean survives any console codepage.

## Windows-specific gotchas (learned the hard way)

- **`.bat` files must be ASCII-only.** Korean text in a batch file misparses under the Korean console codepage (949) — some UTF-8 bytes look like `|`/`&` and split `echo` lines into bogus commands. Keep batch messages in English; let Python handle Korean output.
- `pythonw`/`python` are frequently **not on PATH**; resolve the real path via the `py` launcher (`py -c "import sys,os; print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))"`) — `setup.bat` does this.
- The DB intentionally lives in `%LOCALAPPDATA%`, **not** the repo dir, to avoid OneDrive sync conflicts (the working tree is inside a OneDrive folder).
