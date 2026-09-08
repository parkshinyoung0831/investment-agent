@echo off
chcp 65001 >nul
setlocal
set "SCRIPT_DIR=%~dp0..\..\"
set "VENV_PYTHON=%SCRIPT_DIR%.venv\Scripts\python.exe"
cd /d "%SCRIPT_DIR%"

if not exist "%VENV_PYTHON%" (
    echo [오류] 프로젝트 가상환경 Python을 찾을 수 없습니다.
    echo        예상 경로: %VENV_PYTHON%
    pause
    exit /b 1
)

echo ======================================================================
echo   [AI 모의투자] Shadow 분석 ^& 가상 포트폴리오 하네스를 시작합니다
echo   * 실주문 없음 / 계좌 손익 불변 / 순수 AI 분석 ^& 가상 제안 기록
echo ======================================================================
echo.

"%VENV_PYTHON%" "%SCRIPT_DIR%launcher.py" --shadow
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" echo [오류] 실행기가 종료 코드 %EXIT_CODE%로 끝났습니다.
pause
exit /b %EXIT_CODE%
