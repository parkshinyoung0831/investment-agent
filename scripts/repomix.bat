@echo off
rem repomix context packer (referenced alongside .venv\Scripts\python.exe)
set "PATH=C:\Program Files\nodejs;%PATH%"
if exist "C:\Program Files\nodejs\npx.cmd" goto :run_direct
npx repomix %*
goto :eof

:run_direct
call "C:\Program Files\nodejs\npx.cmd" repomix %*
goto :eof
