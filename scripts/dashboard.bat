@echo off
chcp 65001 >nul
setlocal

set "SCRIPT_DIR=%~dp0..\"
set "VENV_PYTHON=%SCRIPT_DIR%.venv\Scripts\python.exe"
set "VENV_STREAMLIT=%SCRIPT_DIR%.venv\Scripts\streamlit.exe"
cd /d "%SCRIPT_DIR%"

echo ======================================================================
echo    ATLAS 읽기 전용 투자 관제 대시보드를 시작합니다.
echo ======================================================================
echo  * 이 경로는 주문, 승인 요청, Discord 발송을 수행하지 않습니다.
echo  * 8501부터 사용 가능한 로컬 포트를 자동으로 확인합니다.
echo ======================================================================

if not exist "%VENV_PYTHON%" (
    echo [오류] 프로젝트 가상환경 Python이 없습니다: %VENV_PYTHON%
    pause
    exit /b 1
)
if not exist "%VENV_STREAMLIT%" (
    echo [오류] .venv에 Streamlit이 설치되어 있지 않습니다.
    echo        설치: python -m pip install uv==0.12.10 ^&^& uv sync --group dashboard
    pause
    exit /b 1
)

"%VENV_PYTHON%" "%SCRIPT_DIR%launcher.py" --dashboard
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" echo [오류] 대시보드 실행이 종료 코드 %EXIT_CODE%로 끝났습니다.
pause
exit /b %EXIT_CODE%
