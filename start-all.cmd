@echo off
setlocal
chcp 65001 >nul
set "PROJECT_ROOT=%~dp0"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PROJECT_ROOT%scripts\start-all.ps1" %*
set "START_EXIT_CODE=%ERRORLEVEL%"

if not "%START_EXIT_CODE%"=="0" (
  echo.
  if /I "%~1"=="-CheckOnly" (
    echo [LetsGoVideoAgent] One or more services are not ready. No service was started.
  ) else (
    echo [LetsGoVideoAgent] Startup failed. See the message and logs above.
    pause
  )
)

exit /b %START_EXIT_CODE%
