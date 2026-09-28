"""System tray icon. Closing the window hides DevStack here; the right-click menu starts/stops the servers
and opens sites. Needs pystray + Pillow (without them the window simply closes as before)."""
import threading
import time
import webbrowser

from . import paths, services, settings

HINT_FILE = paths.TMP / "tray-hint-shown"
RELEASE_AFTER = 60   # seconds hidden before the window (and its WebView2 processes, ~160 MB) is closed
STATE_COLORS = {"running": (52, 199, 123), "partial": (232, 182, 76), "stopped": (239, 90, 90)}
ACCENT = (109, 124, 255)


def available() -> bool:
    try:
        import PIL  # noqa: F401
        import pystray  # noqa: F401
        return True
    except ImportError:
        return False


def _image(state: str):
    """The sidebar logo (white D on the accent square) with a status dot in the corner."""
    from PIL import Image, ImageDraw, ImageFont
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((2, 2, size - 3, size - 3), radius=14, fill=ACCENT)
    try:
        font = ImageFont.truetype("segoeuib.ttf", 42)
    except OSError:
        font = ImageFont.load_default()
    d.text((size / 2 - 2, size / 2), "D", font=font, fill="white", anchor="mm")
    d.ellipse((size - 26, size - 26, size - 1, size - 1), fill=STATE_COLORS[state], outline=(17, 19, 24), width=4)
    return img


class Tray:
    def __init__(self, api):
        self.api = api
        self.window = None        # set by main.py for every window it opens; None while released
        self.icon = None
        self.quitting = False
        self._sig = None
        self._lock = threading.Lock()
        self._hidden = False
        self._releasing = False
        self._timer = None
        self._reopen = threading.Event()

    # ---------------------------------------------------------------- state

    def _states(self) -> dict:
        cfg = settings.load()
        return {k: services.status(cfg, k) for k in ("apache", "mysql")}

    def _overall(self, st: dict) -> str:
        up = [v == "running" for v in st.values()]
        return "running" if all(up) else "partial" if any(up) else "stopped"

    def _refresh(self, force=False):
        st = self._states()
        stamp = paths.SETTINGS_FILE.stat().st_mtime if paths.SETTINGS_FILE.exists() else 0
        sig = (tuple(st.items()), stamp)
        if not force and sig == self._sig:
            return
        self._sig = sig
        self.icon.icon = _image(self._overall(st))
        self.icon.title = "DevStack · " + " · ".join(
            f"{'Apache' if k == 'apache' else 'MySQL'} {v.replace('-', ' ')}" for k, v in st.items())
        self.icon.update_menu()

    def _watch(self):
        while not self.quitting:
            try:
                self._refresh()
            except Exception:
                pass
            time.sleep(3)

    # ---------------------------------------------------------------- menu

    def _menu(self):
        import pystray
        Item, Menu = pystray.MenuItem, pystray.Menu
        st = self._states()
        cfg = settings.load()

        def server(kind, name):
            s = st[kind]
            return Item(f"{name}: {s.replace('-', ' ')}", Menu(
                Item("Start", self._do("service", kind, "start"), enabled=s != "running" and s != "not-installed"),
                Item("Stop", self._do("service", kind, "stop"), enabled=s == "running"),
                Item("Restart", self._do("service", kind, "restart"), enabled=s == "running"),
            ))

        sites = [Item(s["domain"], self._open_url(settings.site_urls(cfg, s).get("https") or settings.site_urls(cfg, s)["http"]))
                 for s in cfg["sites"]]
        if cfg["sites"]:
            home = settings.site_urls(cfg, cfg["sites"][0])
            sites += [Menu.SEPARATOR, Item("phpMyAdmin", self._open_url((home.get("https") or home["http"]) + "phpmyadmin/"))]
        return (
            Item("Open DevStack", lambda: self.show(), default=True),
            Menu.SEPARATOR,
            server("apache", "Apache"),
            server("mysql", "MySQL"),
            Item("Start all", self._do("all_services", "start")),
            Item("Restart all", self._do("restart_all")),
            Item("Stop all", self._do("all_services", "stop")),
            Menu.SEPARATOR,
            Item("Open site", Menu(*sites) if sites else None, enabled=bool(sites)),
            Item("Sites folder", lambda: self.api.open_path(str(paths.WWW))),
            Menu.SEPARATOR,
            Item("Quit DevStack", lambda: self.quit()),
        )

    def _open_url(self, url):
        return lambda: webbrowser.open(url)

    def _do(self, endpoint, *args):
        """Menu action that runs an Api endpoint in the background, then updates icon, menu and window."""
        def run():
            res = getattr(self.api, endpoint)(*args)
            if not res["ok"]:
                self.icon.notify(res["error"][:250], "DevStack")
            try:
                self._refresh(force=True)
                if self.window and not self._hidden:
                    self.window.evaluate_js("typeof refresh === 'function' && refresh()")
            except Exception:
                pass
        return lambda: threading.Thread(target=run, daemon=True).start()

    # ---------------------------------------------------------------- window

    def show(self):
        with self._lock:
            if self._timer:
                self._timer.cancel()
            if self.window is None:       # released: main.py opens a new window
                self._reopen.set()
                return
            self._hidden = False
            self.window.show()
            self.window.restore()

    def on_close(self, user_closing: bool) -> bool:
        """The form is closing (X button, Windows shutdown or destroy()). True = cancel and hide to the tray."""
        if self._releasing:
            return False
        if user_closing and not self.quitting and settings.load().get("close_to_tray", True):
            threading.Thread(target=self.hide, daemon=True).start()
            return True
        self.quitting = True
        return False

    def hide(self):
        """Close button: hide to the tray, and close the WebView after a while to give its memory back.
        The first time, say where DevStack went."""
        with self._lock:
            self._hidden = True
            self.window.hide()
            self._timer = threading.Timer(RELEASE_AFTER, self._release)
            self._timer.daemon = True
            self._timer.start()
        if not HINT_FILE.exists():
            try:
                HINT_FILE.write_text("1")
                self.icon.notify("DevStack is still running here. Right-click for Apache, MySQL and your sites; "
                                 "Quit DevStack closes it for real.", "DevStack")
            except Exception:
                pass

    def _release(self):
        with self._lock:
            if not self._hidden or self.window is None:
                return
            window, self.window = self.window, None
            self._releasing = True
        window.destroy()                  # ends webview.start(); main.py then waits in wait_for_show()

    def wait_for_show(self) -> bool:
        """Block until Open DevStack (True) or Quit (False) while no window exists."""
        self._reopen.wait()
        self._reopen.clear()
        self._releasing = self._hidden = False
        return not self.quitting

    def quit(self):
        self.quitting = True
        if self._timer:
            self._timer.cancel()
        self.icon.stop()
        if self.window:
            self.window.destroy()
        self._reopen.set()

    def start(self):
        import pystray
        self.icon = pystray.Icon("DevStack", _image("stopped"), "DevStack", pystray.Menu(self._menu))
        threading.Thread(target=self.icon.run, name="tray", daemon=True).start()
        threading.Thread(target=self._watch, name="tray-watch", daemon=True).start()

    def stop(self):
        self.quitting = True
        if self.icon:
            self.icon.stop()
