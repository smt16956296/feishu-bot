@echo off
setlocal

set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "VBS_PATH=E:\feishu-bot\start_hidden.vbs"
set "LNK_PATH=%STARTUP_DIR%\FeishuBot.lnk"

echo ========================================
echo   Feishu Bot - Install Auto Start
echo ========================================
echo.

if not exist "%VBS_PATH%" (
    echo [ERROR] Not found: %VBS_PATH%
    echo.
    pause
    exit /b 1
)

echo Creating startup shortcut...
echo   Target : %VBS_PATH%
echo   Startup: %STARTUP_DIR%
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws = New-Object -ComObject WScript.Shell; $sc = $ws.CreateShortcut('%LNK_PATH%'); $sc.TargetPath = '%VBS_PATH%'; $sc.WorkingDirectory = 'E:\feishu-bot'; $sc.Description = 'Feishu Bot'; $sc.Save()"

if exist "%LNK_PATH%" (
    echo [OK] Auto start installed successfully.
    echo.
    echo Shortcut created at:
    echo   %LNK_PATH%
    echo.
    echo The bot will run in background after next login.
    echo To start it now, double-click start_hidden.vbs
) else (
    echo [FAILED] Could not create shortcut.
    echo Please manually copy a shortcut of start_hidden.vbs to:
    echo   %STARTUP_DIR%
)

echo.
pause
