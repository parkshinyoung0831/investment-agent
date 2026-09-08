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

echo ======================================================================
echo   [ATLAS] 투자 하네스 완전 정지 및 락 해제 (OFF)
echo ======================================================================
echo.

"%VENV_PYTHON%" -m investment_agent.operations.commands.harness_switch --off
set "EXIT_CODE=%ERRORLEVEL%"
echo.
pause
exit /b %EXIT_CODE%
