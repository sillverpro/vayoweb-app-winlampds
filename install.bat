@echo off
rem DevStack installer: Python packages, then Apache / PHP / MySQL / phpMyAdmin downloads and first-time config.
rem Usage: install.bat  [same options as app\bootstrap.py, e.g. --php 8.2,8.3,latest  --ports 8080,8443,3307]
setlocal
cd /d "%~dp0"

rem "py" is the Python launcher; plain "python" may be the Microsoft Store stub, which fails --version.
set "PY="
py -3 --version >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if defined PY goto :havepy
python --version >nul 2>&1
if not errorlevel 1 set "PY=python"
if defined PY goto :havepy
(
  echo Python was not found. Install Python 3.12 or newer first:
  echo     winget install Python.Python.3.13
  echo or download it from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
  echo Then open a new window and run install.bat again.
  pause
  exit /b 1
)
:havepy
%PY% -c "import sys; sys.exit(sys.version_info < (3, 10))" || (
  echo DevStack needs Python 3.10 or newer. Found:
  %PY% --version
  pause
  exit /b 1
)

echo == Python packages
%PY% -m pip install --disable-pip-version-check -q -r app\requirements.txt || (
  echo pip install failed, see above.
  pause
  exit /b 1
)

%PY% app\bootstrap.py %* || (
  echo.
  echo Install failed, see above. Fix the problem and run install.bat again - finished steps are skipped.
  pause
  exit /b 1
)

echo.
echo == Desktop shortcut
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\DevStack.lnk'); $s.TargetPath='%~dp0DevStack.bat'; $s.WorkingDirectory='%~dp0'; $s.WindowStyle=7; $s.Save()" && echo   DevStack.lnk on the desktop

echo.
set /p "RUN=Start DevStack now? [Y/n] "
if /i not "%RUN%"=="n" call "%~dp0DevStack.bat"
endlocal
