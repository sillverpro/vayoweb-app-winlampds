@echo off
rem Starts DevStack. It asks Windows for administrator rights (hosts file, services, certificates).
where pythonw >nul 2>&1 && (start "" pythonw "%~dp0app\main.py" %*) || (start "" pyw -3 "%~dp0app\main.py" %*)
