@echo off
setlocal
set "LOG=%TEMP%\hw-server-launcher.log"
set "SCRIPT_DIR=%~dp0"
set "RUNTIME_PORT=%~1"
set "RUNTIME_TOKEN=%~2"
if "%RUNTIME_PORT%"=="" set "RUNTIME_PORT=5000"
if "%RUNTIME_TOKEN%"=="" set "RUNTIME_TOKEN=windowsbench-runtime-token"
echo [%date% %time%] starting HelloWorld server launcher>"%LOG%"
where py>>"%LOG%" 2>&1
call py -3 -c "import flask, PIL, pyautogui, uiautomation, win32gui, psutil" >>"%LOG%" 2>&1
if errorlevel 1 (
  echo [%date% %time%] installing missing runtime dependencies>>"%LOG%"
  call py -3 -m pip install flask Pillow pyautogui uiautomation pywin32 psutil>>"%LOG%" 2>&1
)
if exist "%SCRIPT_DIR%arrange-sota-desktop.py" (
  echo [%date% %time%] arranging SOTA desktop>>"%LOG%"
  call py -3 "%SCRIPT_DIR%arrange-sota-desktop.py">>"%LOG%" 2>&1
)
echo [%date% %time%] launching runtime on port %RUNTIME_PORT%>>"%LOG%"
call py -3 "%SCRIPT_DIR%server\helloworld_server.py" --host 0.0.0.0 --port %RUNTIME_PORT% --token %RUNTIME_TOKEN%>>"%LOG%" 2>&1
echo [%date% %time%] exit_code=%ERRORLEVEL%>>"%LOG%"
