@echo off
rem Metis launcher for Windows: double-click to install (first time) and start the server.
setlocal
cd /d "%~dp0"
set "PY="
py -3.12 -c "import sys" >nul 2>nul && set "PY=py -3.12"
if not defined PY py -3 -c "import sys" >nul 2>nul && set "PY=py -3"
if not defined PY python -c "import sys" >nul 2>nul && set "PY=python"
if not exist ".venv\Scripts\python.exe" (
  if not defined PY goto :nopython
  echo Creating the Python environment with %PY%...
  %PY% -m venv .venv || goto :nopython
)
echo Installing the Python packages (quick after the first time)...
".venv\Scripts\python.exe" -m pip install -q -r requirements.lock || goto :pipfail
echo.
echo Starting Metis at http://127.0.0.1:8000  (close this window to stop it)
".venv\Scripts\python.exe" -m metis %*
if errorlevel 1 (
  echo.
  echo Metis stopped with an error. The messages above say why.
  pause
)
goto :end
:nopython
echo.
echo Python 3 was not found. Install it with:  winget install Python.Python.3.12
echo then double-click run.bat again.
pause
goto :end
:pipfail
echo.
echo Installing the Python packages failed. Check your internet connection and try again.
pause
:end
endlocal
