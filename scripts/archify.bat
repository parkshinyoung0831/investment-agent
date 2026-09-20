@echo off
rem archify diagram compiler (referenced alongside .venv\Scripts\python.exe)
setlocal
set "NODE_EXE=C:\Program Files\nodejs\node.exe"
set "ARCHIFY_MJS=C:\Users\parks\.agents\skills\archify\bin\archify.mjs"

if not exist "%NODE_EXE%" (
    where node >nul 2>nul
    if %errorlevel% equ 0 (
        set "NODE_EXE=node"
    ) else (
        echo [ERROR] node.exe not found at "%NODE_EXE%" and not in PATH.
        exit /b 1
    )
)

if not exist "%ARCHIFY_MJS%" (
    echo [ERROR] archify.mjs not found at "%ARCHIFY_MJS%".
    exit /b 1
)

"%NODE_EXE%" "%ARCHIFY_MJS%" %*
endlocal
