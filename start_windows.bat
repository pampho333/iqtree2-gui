@echo off
setlocal
cd /d "%~dp0"
where pyw >nul 2>nul
if %ERRORLEVEL%==0 (
    start "" pyw -3 "%~dp0app.py"
    exit /b 0
)
where pythonw >nul 2>nul
if %ERRORLEVEL%==0 (
    start "" pythonw "%~dp0app.py"
    exit /b 0
)
where py >nul 2>nul
if %ERRORLEVEL%==0 (
    py -3 "%~dp0app.py"
    exit /b %ERRORLEVEL%
)
echo Python 3 is required to run this source distribution.
echo Install Python from https://www.python.org/downloads/windows/
echo Or build a standalone EXE with build_windows_exe.bat after installing Python.
pause
exit /b 1
