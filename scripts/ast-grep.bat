@echo off
rem ast-grep CLI launcher (uses .venv\Scripts\python.exe or standalone binary)
setlocal
set "VENV_AST_GREP=%~dp0..\.venv\Scripts\ast-grep.exe"
set "GLOBAL_AST_GREP=C:\Users\parks\AppData\Local\Programs\Python\Python312\Scripts\ast-grep.exe"
if exist "%VENV_AST_GREP%" goto :run_venv
if exist "%GLOBAL_AST_GREP%" goto :run_global
ast-grep %*
goto :eof

:run_venv
"%VENV_AST_GREP%" %*
goto :eof

:run_global
"%GLOBAL_AST_GREP%" %*
goto :eof
