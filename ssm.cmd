@echo off
setlocal
set PIP_PREFIX=
set PYTHONHOME=
set VIRTUAL_ENV=
set PYTHONUTF8=1
"%~dp0.venv\Scripts\python.exe" "%~dp0ssm.py" %*
