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
echo   [ATLAS] 정비 보류 토글 - 걸려 있으면 하네스가 아예 기동하지 않습니다
echo ======================================================================
echo.
echo   [1] 정비 보류 걸기 (작업 중 실수로 켜지는 것을 막습니다)
echo   [2] 정비 보류 해제 (거래 킬스위치는 그대로 둡니다)
echo   [3] 현재 상태 보기
echo.
set /p CHOICE=선택 [1/2/3]: 

if "%CHOICE%"=="1" "%VENV_PYTHON%" -m investment_agent.operations.commands.harness_switch --maintenance on --maintenance-reason manual
if "%CHOICE%"=="2" "%VENV_PYTHON%" -m investment_agent.operations.commands.harness_switch --maintenance off
if "%CHOICE%"=="3" "%VENV_PYTHON%" -m investment_agent.operations.commands.harness_switch --status
set "EXIT_CODE=%ERRORLEVEL%"
echo.
pause
exit /b %EXIT_CODE%
