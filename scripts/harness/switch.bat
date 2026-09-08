@echo off
chcp 65001 >nul
setlocal
rem 저장소 루트에서 실행해야 src 패키지와 .venv를 찾는다.
set "ROOT=%~dp0..\..\"
cd /d "%ROOT%"
set "VENV_PYTHON=%ROOT%.venv\Scripts\python.exe"
if not exist "%VENV_PYTHON%" (
    echo [오류] 프로젝트 가상환경 Python을 찾을 수 없습니다: %VENV_PYTHON%
    pause
    exit /b 1
)

"%VENV_PYTHON%" -m investment_agent.operations.commands.harness_switch --interactive
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
    echo.
    echo [알림] 오류가 발생했습니다.
    pause
)
exit /b %EXIT_CODE%
