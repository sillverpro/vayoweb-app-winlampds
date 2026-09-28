"""DevStack desktop app entry point."""
import ctypes
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import webview  # noqa: E402

from devstack import jobs, paths, tray  # noqa: E402
from devstack.api import Api  # noqa: E402
from devstack.winutil import is_admin  # noqa: E402

INSTANCE_FILE = paths.TMP / "app-instance.port"


def relaunch_as_admin() -> bool:
    """Ask UAC for admin (hosts file, services, trusted CA). Returns True if a new elevated copy started."""
    if getattr(sys, "frozen", False):
        exe, params = sys.executable, subprocess.list2cmdline(sys.argv[1:])
    else:
        exe = sys.executable.replace("python.exe", "pythonw.exe")
        params = subprocess.list2cmdline([str(Path(__file__).resolve()), *sys.argv[1:]])
    return ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, str(paths.ROOT), 1) > 32


def app_stamp() -> str:
    """Newest modification time of the app's code and UI. It changes when DevStack is updated."""
    app = Path(__file__).resolve().parent
    files = [*app.rglob("*.py"), *(app / "ui").rglob("*"), paths.CHANGELOG]
    return str(int(max((f.stat().st_mtime for f in files if f.is_file()), default=0)))


def show_running_instance(stamp: str) -> bool:
    """If DevStack already runs (maybe hidden in the tray), bring its window up. True when it answered.
    If it runs older code (updated since it started), it quits instead and we wait for it to exit and
    start fresh - otherwise an update stays hidden behind the old tray process."""
    try:
        port, _, pid = INSTANCE_FILE.read_text().partition(" ")
        with socket.create_connection(("127.0.0.1", int(port)), timeout=1) as s:
            s.sendall(f"show {stamp}".encode())
            reply = s.recv(16)
    except (OSError, ValueError):
        return False
    if reply == b"restart":
        wait_for_exit(pid)
        return False
    return reply == b"ok"


def wait_for_exit(pid: str, timeout: float = 20):
    try:
        import psutil
        pid = int(pid)
    except (ImportError, ValueError):
        time.sleep(3)
        return
    end = time.time() + timeout
    while psutil.pid_exists(pid) and time.time() < end:
        time.sleep(0.2)


def listen_for_instances(stamp: str, on_show, on_quit):
    """A second launch connects here and asks this window to show itself instead of opening another copy.
    A launch of newer code makes this one quit (unless a job such as an install is still running)."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen()
    paths.TMP.mkdir(parents=True, exist_ok=True)
    INSTANCE_FILE.write_text(f"{srv.getsockname()[1]} {os.getpid()}")

    def loop():
        while True:
            conn, _ = srv.accept()
            with conn:
                try:
                    msg = conn.recv(64).decode(errors="replace").split()
                    if msg[:1] != ["show"]:
                        continue
                    busy = any(not j["done"] for j in jobs.listing())
                    if len(msg) > 1 and msg[1] != stamp and not busy:
                        conn.sendall(b"restart")
                        srv.close()
                        on_quit()
                        return
                    conn.sendall(b"ok")
                    on_show()
                except OSError:
                    pass
    threading.Thread(target=loop, name="instance", daemon=True).start()


def main():
    stamp = app_stamp()
    if show_running_instance(stamp):
        return
    if not is_admin() and "--no-admin" not in sys.argv and relaunch_as_admin():
        return
    api = Api()
    icon = tray.Tray(api) if tray.available() else None
    api._tray = icon

    def on_show():
        if icon:
            icon.show()
        elif api._window:
            api._window.show()
            api._window.restore()

    def on_quit():
        if icon:
            icon.quit()
        elif api._window:
            api._window.destroy()
    listen_for_instances(stamp, on_show, on_quit)

    if icon:
        icon.start()
    clear_ui_cache()
    # Closing to the tray ends webview.start() once the WebView is released (frees ~160 MB);
    # the tray's Open (or a second launch) opens a fresh window in the same process.
    while True:
        window = open_window(api, icon)
        # Persistent WebView storage so UI choices (e.g. dismissed notes) survive a restart.
        webview.start(debug="--debug" in sys.argv, private_mode=False,
                      storage_path=str(paths.TMP / "webview"))
        api._window = None
        if not icon or not icon.wait_for_show():
            break
    if icon:
        icon.stop()
    try:
        INSTANCE_FILE.unlink()
    except OSError:
        pass


def clear_ui_cache():
    """WebView2 keeps its HTTP cache in the persistent profile and may serve an old app.js/index.html
    after an update. Drop the caches (localStorage lives elsewhere and is kept)."""
    base = paths.TMP / "webview" / "EBWebView" / "Default"
    for name in ("Cache", "Code Cache"):
        shutil.rmtree(base / name, ignore_errors=True)


def open_window(api, icon):
    window = webview.create_window(
        "DevStack", str(paths.UI / "index.html"), js_api=api,
        width=1120, height=740, min_size=(860, 560), background_color="#111318",
    )
    api._window = window
    if not icon:
        return window
    icon.window = window

    def on_shown():
        # Hook the native form: pywebview's closing event can't tell the X button from a Windows shutdown,
        # and cancelling a shutdown would block it.
        from System.Windows.Forms import CloseReason

        def form_closing(sender, args):
            if icon.on_close(args.CloseReason == CloseReason.UserClosing):
                args.Cancel = True
        window.native.FormClosing += form_closing
    window.events.shown += on_shown
    return window

if __name__ == "__main__":
    main()
