"""Small Windows helpers: running commands without console windows, admin checks, process liveness."""
import ctypes
import socket
import subprocess

CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_PROCESS_GROUP = 0x00000200


def run(cmd, timeout=60, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=timeout,
                          creationflags=CREATE_NO_WINDOW, **kw)


def spawn(cmd, cwd=None) -> subprocess.Popen:
    """Start a long-running background process with a hidden console (children inherit it, so no pop-ups)."""
    return subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP)


def spawn_console(cmd, cwd=None, env=None) -> subprocess.Popen:
    """Start a process in a new, visible console window (e.g. "Terminal here")."""
    return subprocess.Popen(cmd, cwd=cwd, env=env, creationflags=subprocess.CREATE_NEW_CONSOLE)


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def pid_alive(pid: int) -> bool:
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return False
    try:
        code = ctypes.c_ulong()
        return bool(k32.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == STILL_ACTIVE
    finally:
        k32.CloseHandle(h)


def port_in_use(port: int, host="127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex((host, port)) == 0


def port_owner(port: int) -> str | None:
    """Name of the process listening on a TCP port, if any."""
    r = run(["netstat", "-ano", "-p", "TCP"])
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[3] == "LISTENING" and parts[1].rsplit(":", 1)[-1] == str(port):
            t = run(["tasklist", "/FI", f"PID eq {parts[4]}", "/FO", "CSV", "/NH"])
            name = t.stdout.strip().split(",")[0].strip('"')
            return f"{name} (PID {parts[4]})" if name else f"PID {parts[4]}"
    return None


def font_families() -> list[str]:
    """Installed font family names (GDI EnumFontFamiliesExW), sorted, without vertical "@" variants."""
    from ctypes import wintypes

    class LOGFONTW(ctypes.Structure):
        _fields_ = [("lfHeight", wintypes.LONG), ("lfWidth", wintypes.LONG), ("lfEscapement", wintypes.LONG),
                    ("lfOrientation", wintypes.LONG), ("lfWeight", wintypes.LONG), ("lfItalic", wintypes.BYTE),
                    ("lfUnderline", wintypes.BYTE), ("lfStrikeOut", wintypes.BYTE), ("lfCharSet", wintypes.BYTE),
                    ("lfOutPrecision", wintypes.BYTE), ("lfClipPrecision", wintypes.BYTE), ("lfQuality", wintypes.BYTE),
                    ("lfPitchAndFamily", wintypes.BYTE), ("lfFaceName", wintypes.WCHAR * 32)]

    proc_t = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.POINTER(LOGFONTW), ctypes.c_void_p, wintypes.DWORD, wintypes.LPARAM)
    names = set()

    def cb(lf, _tm, _type, _lp):
        name = lf.contents.lfFaceName
        if name and not name.startswith("@"):
            names.add(name)
        return 1

    gdi, user = ctypes.windll.gdi32, ctypes.windll.user32
    gdi.EnumFontFamiliesExW.argtypes = [wintypes.HDC, ctypes.POINTER(LOGFONTW), proc_t, wintypes.LPARAM, wintypes.DWORD]
    user.GetDC.restype = wintypes.HDC
    user.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    hdc = user.GetDC(None)
    try:
        lf = LOGFONTW(lfCharSet=1)  # DEFAULT_CHARSET = every charset
        gdi.EnumFontFamiliesExW(hdc, ctypes.byref(lf), proc_t(cb), 0, 0)
    finally:
        user.ReleaseDC(None, hdc)
    return sorted(names, key=str.lower)
