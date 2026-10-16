@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %ERRORLEVEL%==0 (
    set "PY=py -3"
) else (
    set "PY=python"
)
%PY% -m pip install --upgrade pyinstaller
if errorlevel 1 goto fail
%PY% -m PyInstaller --noconfirm --clean --onefile --windowed --name IQTree2_GUI --add-data "assets;assets" --add-data "examples;examples" app.py
if errorlevel 1 goto fail
echo.
echo EXE ready: dist\IQTree2_GUI.exe
echo NOTE: IQ-TREE 2 binary is separate. Set its location in the GUI or put iqtree2.exe beside the EXE.
pause
exit /b 0
:fail
echo Build failed. Please inspect the messages above.
pause
exit /b 1
