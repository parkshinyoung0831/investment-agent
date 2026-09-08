@echo off
chcp 65001 >nul
setlocal
set "SCRIPT_DIR=%~dp0"
set "VENV_PYTHON=%SCRIPT_DIR%.venv\Scripts\python.exe"
cd /d "%SCRIPT_DIR%"

if not exist "%VENV_PYTHON%" (
    echo [오류] 프로젝트 가상환경 Python을 찾을 수 없습니다.
    echo        예상 경로: %VENV_PYTHON%
    echo        먼저 .venv를 만들고 의존성을 설치하세요.
    pause
    exit /b 1
)

"%VENV_PYTHON%" "%SCRIPT_DIR%launcher.py" %*
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" echo [오류] 실행기가 종료 코드 %EXIT_CODE%로 끝났습니다.
if "%~1"=="" pause
exit /b %EXIT_CODE%
