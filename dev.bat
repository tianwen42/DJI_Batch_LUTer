@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "APP_NAME=DJI Batch LUTer"
set "MAIN=src\DJI_Batch_LUTer.py"
set "BUILDER=src\build.py"
REM build output: the dist\ folder itself is the whole project
REM               (exe + _internal + config + doc ...)
set "EXE=dist\DJI_Batch_LUTer.exe"

REM ==============================================================
REM  DJI Batch LUTer - one click dev script
REM    dev.bat            show menu
REM    dev.bat run        run the app
REM    dev.bat build      build app folder (fast start)  -> dist\
REM    dev.bat build1     build single-file EXE (slow)   -> dist\
REM    dev.bat buildrun   build app folder then run
REM ==============================================================

REM ---------- locate python ----------
set "PY="
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY if exist "venv\Scripts\python.exe" set "PY=venv\Scripts\python.exe"
if not defined PY (
    where python >nul 2>nul && set "PY=python"
)
if not defined PY (
    echo [ERROR] Python not found. Install Python 3.9+ and add it to PATH.
    pause
    exit /b 1
)

REM ---------- direct args ----------
if /i "%~1"=="run"      goto :run
if /i "%~1"=="build"    goto :build
if /i "%~1"=="buildrun" goto :buildrun
if /i "%~1"=="br"       goto :buildrun
if /i "%~1"=="build1"   goto :build1
if /i "%~1"=="onefile"  goto :build1
if /i "%~1"=="help"     goto :help
if /i "%~1"=="-h"       goto :help
if not "%~1"==""        goto :help

REM ---------- menu ----------
:menu
cls
echo ==============================================
echo    %APP_NAME%   -   Quick Menu
echo ==============================================
echo.
echo    [1] Run the app                 (Run)
echo    [2] Build app folder            (fast start)  -^> dist\
echo    [3] Build and run               (Build + Run)
echo    [4] Build single-file EXE       (slow start)  -^> dist\
echo    [0] Exit
echo.
set "choice="
set /p "choice=Choose [1/2/3/4/0]: "
if "%choice%"=="1" goto :run
if "%choice%"=="2" goto :build
if "%choice%"=="3" goto :buildrun
if "%choice%"=="4" goto :build1
if "%choice%"=="0" exit /b 0
goto :menu

REM ---------- shared: deps ----------
:ensure_deps
"%PY%" -c "import PyQt6" >nul 2>nul
if errorlevel 1 (
    echo [INFO] PyQt6 not found, installing from requirements.txt ...
    "%PY%" -m pip install -r requirements.txt
)
exit /b 0

REM ---------- run ----------
:run
call :ensure_deps
echo.
echo [RUN] %MAIN%
echo ----------------------------------------------
"%PY%" "%MAIN%"
set "rc=%errorlevel%"
if not "%rc%"=="0" (
    echo.
    echo [ERROR] app exited with code %rc%
    pause
)
exit /b %rc%

REM ---------- build (app folder, fast start) ----------
:build
call :ensure_deps
echo.
echo [BUILD] creating app folder (dist\ = whole project) ...
echo ----------------------------------------------
"%PY%" "%BUILDER%"
if errorlevel 1 (
    echo.
    echo [ERROR] build failed, check the log above.
    pause
    exit /b 1
)
echo.
echo [DONE] output: %EXE%
pause
exit /b 0

REM ---------- build single-file EXE ----------
:build1
call :ensure_deps
echo.
echo [BUILD] creating single-file EXE ...
echo ----------------------------------------------
"%PY%" "%BUILDER%" --onefile
if errorlevel 1 (
    echo.
    echo [ERROR] build failed, check the log above.
    pause
    exit /b 1
)
echo.
echo [DONE] output: %EXE%
pause
exit /b 0

REM ---------- build + run ----------
:buildrun
call :ensure_deps
echo.
echo [BUILD] creating app folder (dist\ = whole project) ...
echo ----------------------------------------------
"%PY%" "%BUILDER%"
if errorlevel 1 (
    echo.
    echo [ERROR] build failed, check the log above.
    pause
    exit /b 1
)
if not exist "%EXE%" (
    echo.
    echo [ERROR] output not found: %EXE%
    pause
    exit /b 1
)
echo.
echo [RUN] %EXE%
start "" "%EXE%"
exit /b 0

REM ---------- help ----------
:help
echo.
echo Usage:
echo   dev.bat            show the menu
echo   dev.bat run        run the app
echo   dev.bat build      build app folder (fast start)  -^> dist\
echo   dev.bat build1     build single-file EXE (slow)   -^> dist\
echo   dev.bat buildrun   build app folder then run
echo.
echo Note: dist\ itself is the whole project (DJI_Batch_LUTer.exe + _internal + config ...)
echo.
exit /b 0
