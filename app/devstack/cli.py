"""PHP CLI: bin/cli/php.bat (+ composer.bat) shims, and adding bin/cli to the user's PATH.

php.bat resolves which PHP to run by walking up from %CD% looking for a `.php-version` file
(content like "8.3" or "8.3.14"); without one it falls back to the `cli_php` setting.
The version -> installed folder mapping is baked into the batch file when it is generated,
so the shim itself stays a plain, fast batch script with no external dependency.
"""
import ctypes
import winreg

from . import paths, php, settings

PATH_ENTRY = str(paths.CLI)


def _branch_map() -> dict[str, str]:
    """{"8.3": "8.3.14", ...} - the newest installed patch release of each major.minor branch."""
    out = {}
    for v in php.versions():
        branch = ".".join(v.split(".")[:2])
        if branch not in out or paths.version_key(v) > paths.version_key(out[branch]):
            out[branch] = v
    return out


def write_shims(cfg: dict | None = None):
    cfg = cfg or settings.load()
    cli_ver = cfg.get("cli_php") or cfg.get("default_php") or ""
    paths.CLI.mkdir(parents=True, exist_ok=True)
    root = paths.ROOT
    lines = [
        "@echo off",
        f'set "ROOT={root}"',
        f'set "CLIVER={cli_ver}"',
    ]
    for branch, ver in _branch_map().items():
        lines.append(f'set "B{branch}={ver}"')
    lines += [
        'set "DIR=%CD%"',
        ":loop",
        'if exist "%DIR%\\.php-version" goto haveraw',
        'for %%I in ("%DIR%\\..") do set "PARENT=%%~fI"',
        'if /I "%PARENT%"=="%DIR%" goto useclidefault',
        'set "DIR=%PARENT%"',
        "goto loop",
        ":haveraw",
        'set "RAWV="',
        'set /p RAWV=<"%DIR%\\.php-version"',
        'for /f "tokens=* delims= 	" %%A in ("%RAWV%") do set "RAWV=%%A"',
        'set "PVER="',
        'if exist "%ROOT%\\bin\\php\\php%RAWV%\\php.exe" set "PVER=%RAWV%"',
        'if not defined PVER if defined B%RAWV% call set "PVER=%%B%RAWV%%%"',
        "if not defined PVER goto useclidefault",
        "goto run",
        ":useclidefault",
        'set "PVER=%CLIVER%"',
        ":run",
        "if not defined PVER (",
        "  echo DevStack: no PHP CLI version is set >&2",
        "  exit /b 1",
        ")",
        'if not exist "%ROOT%\\bin\\php\\php%PVER%\\php.exe" (',
        "  echo DevStack: PHP %PVER% is not installed >&2",
        "  exit /b 1",
        ")",
        '"%ROOT%\\bin\\php\\php%PVER%\\php.exe" %*',
        "exit /b %errorlevel%",
    ]
    (paths.CLI / "php.bat").write_text("\r\n".join(lines) + "\r\n", encoding="utf-8", newline="")
    (paths.CLI / "composer.bat").write_text(
        '@echo off\r\nphp "%~dp0..\\composer\\composer.phar" %*\r\nexit /b %errorlevel%\r\n', encoding="utf-8", newline="")


def ensure_shims(cfg: dict | None = None):
    """Regenerate the shims if missing, or if the installed PHP versions changed since they were written."""
    cfg = cfg or settings.load()
    marker = paths.CLI / "php.bat"
    if not marker.exists():
        write_shims(cfg)
        return
    text = marker.read_text(encoding="utf-8", errors="replace")
    wanted = f'set "CLIVER={cfg.get("cli_php") or cfg.get("default_php") or ""}"'
    if wanted not in text or any(f'set "B{b}={v}"' not in text for b, v in _branch_map().items()):
        write_shims(cfg)


# ---------------------------------------------------------------- user PATH (HKCU\Environment)

def _open_env(write=False):
    return winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0,
                          winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE if write else winreg.KEY_QUERY_VALUE)


def _read_path() -> tuple[str, int]:
    try:
        with _open_env() as k:
            value, kind = winreg.QueryValueEx(k, "Path")
            return value, kind
    except FileNotFoundError:
        return "", winreg.REG_EXPAND_SZ


def on_path() -> bool:
    value, _ = _read_path()
    return any(p.strip().lower() == PATH_ENTRY.lower() for p in value.split(";") if p.strip())


def _broadcast_env_change():
    HWND_BROADCAST, WM_SETTINGCHANGE, SMTO_ABORTIFHUNG = 0xFFFF, 0x001A, 0x0002
    result = ctypes.c_long()
    ctypes.windll.user32.SendMessageTimeoutW(HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment",
                                             SMTO_ABORTIFHUNG, 5000, ctypes.byref(result))


def add_to_path():
    value, kind = _read_path()
    parts = [p for p in value.split(";") if p.strip()]
    if any(p.strip().lower() == PATH_ENTRY.lower() for p in parts):
        return
    new_value = PATH_ENTRY + (";" + value if value else "")
    with _open_env(write=True) as k:
        winreg.SetValueEx(k, "Path", 0, kind or winreg.REG_EXPAND_SZ, new_value)
    _broadcast_env_change()


def remove_from_path():
    value, kind = _read_path()
    parts = [p for p in value.split(";") if p.strip() and p.strip().lower() != PATH_ENTRY.lower()]
    with _open_env(write=True) as k:
        winreg.SetValueEx(k, "Path", 0, kind or winreg.REG_EXPAND_SZ, ";".join(parts))
    _broadcast_env_change()
