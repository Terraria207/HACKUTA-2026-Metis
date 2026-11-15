@echo off
rem Metis launcher for Windows: double-click to install (first time) and start the server.
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (set "PY=py -3.12") else (set "PY=python")
if not exist ".venv\Scripts\python.exe" (
  echo Creating the Python environment...
  %PY% -m venv .venv || goto :nopython
)
".venv\Scripts\python" -m pip install -q -r requirements.lock || goto :pipfail
echo Starting Metis at http://127.0.0.1:8000  (close this window to stop it)
".venv\Scripts\python" -m metis %*
goto :end
:nopython
echo.
echo Python 3.12 was not found. Install it with:  winget install Python.Python.3.12
echo then double-click run.bat again.
pause
goto :end
:pipfail
echo.
echo Installing the Python packages failed. Check your internet connection and try again.
pause
:end
endlocal
