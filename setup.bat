@echo off
REM ASCII-only messages: Korean text in a .bat misparses under the console
REM codepage (some UTF-8 bytes look like | or & and break command lines).
echo ============================================
echo   TimeTracker - Setup
echo ============================================
echo.
echo [1/3] Installing required packages...
py -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 (
    echo Package install failed. Check your Python installation.
    pause
    exit /b 1
)
echo.
echo [2/3] Registering auto-start on login...
py "%~dp0install_autostart.py"
echo.
echo [3/3] Launching now...
for /f "delims=" %%i in ('py -c "import sys,os;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))"') do set "PYW=%%i"
start "" "%PYW%" "%~dp0time_tracker.pyw"
echo.
echo Done! A clock icon will appear in the tray (bottom-right).
echo Right-click it and choose the report menu to see your hours.
pause
