"""Numbers for the dashboard: disk use, what the servers are doing, and which database each site uses."""
import os
import re
import shutil
import threading
import time
from collections import deque
from pathlib import Path

from . import mysql, paths, settings

SIZE_TTL = 600          # folder sizes are recounted at most every 10 minutes
DB_SCAN_TTL = 120

_sizes = {"at": 0.0, "data": {}, "running": False}
_sizes_lock = threading.Lock()


def folder_size(path: Path) -> int:
    total, stack = 0, [str(path)]
    while stack:
        try:
            with os.scandir(stack.pop()) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            stack.append(e.path)
                        else:
                            total += e.stat(follow_symlinks=False).st_size
                    except OSError:
                        pass
        except OSError:
            pass
    return total


def project_folder(site: dict) -> Path:
    """The project a site belongs to: the docroot, or its parent for public/ and web/ style projects."""
    root = Path(site["root"])
    return root.parent if root.name.lower() in ("public", "web", "public_html", "htdocs", "webroot") else root


def _count_sizes():
    cfg = settings.load()
    data = {"sites": {}}
    seen = {}
    for s in cfg["sites"]:
        p = project_folder(s)
        key = str(p).lower()
        if key not in seen:
            seen[key] = folder_size(p)
        data["sites"][s["name"]] = seen[key]
    data["projects"] = sum(seen.values())
    data["mysql"] = folder_size(paths.MYSQL_DATA)
    data["logs"] = folder_size(paths.LOGS)
    data["apps"] = folder_size(paths.ROOT / "apps")
    data["bin"] = folder_size(paths.BIN) + data["apps"]          # programs: Apache, PHP, MySQL + phpMyAdmin
    data["backups"] = folder_size(paths.ROOT / "data" / "exports")
    with _sizes_lock:
        _sizes.update(at=time.time(), data=data, running=False)


def sizes(refresh=False) -> dict:
    """Last counted sizes; starts a recount in the background when they are old. {} until the first count."""
    with _sizes_lock:
        stale = refresh or time.time() - _sizes["at"] > SIZE_TTL
        if stale and not _sizes["running"]:
            _sizes["running"] = True
            threading.Thread(target=_count_sizes, daemon=True).start()
        return dict(_sizes["data"], counting=_sizes["running"])


# ---------------------------------------------------------------- site icons (dashboard cards)

ICON_FILES = ("favicon.ico", "favicon.png", "favicon.svg", "apple-touch-icon.png", "favicon.gif")
ICON_TYPES = {".ico": "image/x-icon", ".png": "image/png", ".svg": "image/svg+xml", ".gif": "image/gif",
              ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
ICON_MAX = 256 * 1024
_LINK_ICON = re.compile(r"<link[^>]*rel=[\"'][^\"']*icon[^\"']*[\"'][^>]*>", re.I)
_HREF = re.compile(r"href=[\"']([^\"']+)[\"']", re.I)
_icons = {}              # site name -> (checked at, data uri or None)


def _icon_from_page(root: Path):
    """A local icon from <link rel="icon" href="..."> in the index page (relative or root-relative paths only)."""
    for name in ("index.html", "index.htm", "index.php"):
        try:
            with open(root / name, encoding="utf-8", errors="ignore") as f:
                head = f.read(30000)
        except OSError:
            continue
        for tag in _LINK_ICON.findall(head):
            m = _HREF.search(tag)
            href = m.group(1).split("?")[0].split("#")[0] if m else ""
            if not href or "://" in href or href.startswith("//") or "<?" in href:
                continue
            p = (root / href.lstrip("/")).resolve()
            if p.is_file() and root.resolve() in p.parents:
                return p
    return None


ICON_SKIP = {"vendor", "node_modules", ".git", "plugin", "plugins", "upload", "uploads", "cache", "storage", "event", "events"}


def _icon_search(root: Path, max_depth=4, max_dirs=400):
    """Most frameworks keep the icon in assets/ and link it from a PHP template: look for favicon*/apple-touch-icon*
    files, shallowest first, skipping vendor/plugin/upload folders."""
    def rank(name):
        n = name.lower()
        if n.startswith("apple-touch-icon"):
            return 1
        return 0 if n.split(".")[0] == "favicon" else 2 if not n.startswith("favicon-16") else 3
    level, dirs = [root], 0
    for _ in range(max_depth + 1):
        found, nxt = [], []
        for d in level:
            dirs += 1
            if dirs > max_dirs:
                return None
            try:
                with os.scandir(d) as it:
                    for e in it:
                        n = e.name.lower()
                        if e.is_dir(follow_symlinks=False):
                            if n not in ICON_SKIP and not n.startswith("."):
                                nxt.append(Path(e.path))
                        elif (n.startswith("favicon") or n.startswith("apple-touch-icon")) and Path(n).suffix in ICON_TYPES:
                            found.append(Path(e.path))
            except OSError:
                pass
        if found:
            return min(found, key=lambda p: rank(p.name))
        level = nxt
    return None


def site_icon(site: dict) -> str | None:
    """The site's favicon as a data: URI, read from its docroot (the site doesn't have to be running). Cached 10 min."""
    import base64
    hit = _icons.get(site["name"])
    if hit and time.time() - hit[0] < SIZE_TTL:
        return hit[1]
    root, uri = Path(site["root"]), None
    for p in [root / n for n in ICON_FILES] + [_icon_from_page(root), _icon_search(root)]:
        try:
            if p is None:
                continue
            if p.is_file() and 0 < p.stat().st_size <= ICON_MAX and p.suffix.lower() in ICON_TYPES:
                uri = f"data:{ICON_TYPES[p.suffix.lower()]};base64," + base64.b64encode(p.read_bytes()).decode()
                break
        except OSError:
            pass
    _icons[site["name"]] = (time.time(), uri)
    return uri


# ---------------------------------------------------------------- live process numbers (sampled every second)

GROUPS = {"httpd.exe": "apache", "php-cgi.exe": "php", "mysqld.exe": "mysql"}
KEYS = ("apache", "php", "mysql")
FINE_KEEP = 900          # 1 s samples for the last 15 minutes
COARSE_EVERY = 10        # plus 10 s averages ...
COARSE_KEEP = 1080       # ... for the last 3 hours

_procs = {}              # pid -> psutil.Process started from this DevStack, or None (same name, other install)
_io_last = {}            # pid -> (time, read_bytes, write_bytes)
_fine = deque(maxlen=FINE_KEEP)       # rows: [t, cpu x3, mem x3, io x3] in KEYS order
_coarse = deque(maxlen=COARSE_KEEP)
_pending = []            # fine rows not yet averaged into a coarse row
_now = None              # latest per-group numbers
_hist_lock = threading.Lock()
_sampler = None


def _sample(psutil, root, cpus):
    now = time.time()
    out = {g: {"count": 0, "cpu": 0.0, "mem": 0, "read": 0.0, "write": 0.0, "since": None} for g in KEYS}
    alive = set()
    for p in psutil.process_iter(["name"]):           # names only: cheap; exe is checked once per pid
        g = GROUPS.get((p.info["name"] or "").lower())
        if not g:
            continue
        pid = p.pid
        alive.add(pid)
        if pid not in _procs:
            try:
                _procs[pid] = p if (p.exe() or "").lower().startswith(root) else None
            except psutil.Error:
                continue
        proc = _procs[pid]
        if proc is None:
            continue
        try:
            with proc.oneshot():
                cpu = proc.cpu_percent(None) / cpus
                mem = proc.memory_info().rss
                io = proc.io_counters()
                since = proc.create_time()
        except psutil.Error:
            continue
        o = out[g]
        o["count"] += 1
        o["cpu"] += cpu
        o["mem"] += mem
        last = _io_last.get(pid)
        if last and now > last[0]:
            o["read"] += max(0, io.read_bytes - last[1]) / (now - last[0])
            o["write"] += max(0, io.write_bytes - last[2]) / (now - last[0])
        _io_last[pid] = (now, io.read_bytes, io.write_bytes)
        o["since"] = min(o["since"] or since, since)
    for pid in list(_procs):
        if pid not in alive:
            _procs.pop(pid, None)
            _io_last.pop(pid, None)
    return now, out


def _sampler_loop():
    import psutil
    global _now
    root, cpus = str(paths.ROOT).lower(), psutil.cpu_count() or 1
    while True:
        started = time.time()
        try:
            t, out = _sample(psutil, root, cpus)
            row = [round(t, 1), *(round(out[g]["cpu"], 2) for g in KEYS), *(out[g]["mem"] for g in KEYS),
                   *(round(out[g]["read"] + out[g]["write"]) for g in KEYS)]
            with _hist_lock:
                _now = out
                _fine.append(row)
                _pending.append(row)
                if len(_pending) >= COARSE_EVERY:
                    avg = [sum(r[i] for r in _pending) / len(_pending) for i in range(1, len(row))]
                    _coarse.append([row[0], *(round(v, 2) for v in avg)])
                    _pending.clear()
        except Exception:
            pass
        time.sleep(max(0.2, 1 - (time.time() - started)))


def start_sampler() -> bool:
    """Start the once-a-second sampler (history lives in memory while the app runs). False without psutil."""
    global _sampler
    try:
        import psutil  # noqa: F401
    except ImportError:
        return False
    if _sampler is None:
        _sampler = threading.Thread(target=_sampler_loop, name="stats-sampler", daemon=True)
        _sampler.start()
    return True


def live() -> dict | None:
    """Latest CPU, memory, disk I/O and uptime of Apache, PHP workers and MySQL started from this DevStack."""
    if not start_sampler():
        return None
    return _now


def activity(fine_since=0.0, coarse_since=0.0) -> dict | None:
    """Live numbers plus the history rows newer than the given times (the UI keeps what it already has)."""
    if not start_sampler():
        return None
    import psutil
    with _hist_lock:
        return {
            "now": _now,
            "keys": KEYS,
            "fine": [r for r in _fine if r[0] > fine_since],
            "coarse": [r for r in _coarse if r[0] > coarse_since],
            "ram": psutil.virtual_memory().total,
        }


def disk() -> dict:
    u = shutil.disk_usage(paths.ROOT)
    return {"drive": paths.ROOT.drive, "total": u.total, "free": u.free}


# ---------------------------------------------------------------- which database does a site use?

_SKIP_DIRS = {"vendor", "node_modules", ".git", ".svn", ".idea", ".vscode", "storage", "cache", "uploads",
              "upload", "images", "img", "assets", "css", "js", "fonts", "tmp", "temp", "logs", "backup", "backups"}
_CONFIG_NAME = re.compile(r"^\.env|config|database|setting|db|conn|parameters|local|app\.php$", re.I)
_CONFIG_EXT = {".php", ".inc", ".ini", ".env", ".yml", ".yaml", ".json", ".xml", ""}
_TOKEN = re.compile(r"""['"]([\w$-]{1,64})['"]|^[ \t]*[\w.]*(?:DB|DATABASE)[\w.]*[ \t]*[=:][ \t]*([\w$-]{1,64})[ \t]*$""",
                    re.M | re.I)
_db_cache = {"at": 0.0, "key": None, "data": {}}


def _config_files(project: Path, max_depth=3, limit=300):
    base_depth = len(project.parts)
    found = 0
    for dirpath, dirs, files in os.walk(project):
        depth = len(Path(dirpath).parts) - base_depth
        dirs[:] = [] if depth >= max_depth else [d for d in dirs if d.lower() not in _SKIP_DIRS]
        for f in files:
            if f.startswith(".env") or (_CONFIG_NAME.search(f) and Path(f).suffix.lower() in _CONFIG_EXT):
                p = Path(dirpath) / f
                try:
                    if p.stat().st_size < 256_000:
                        yield p
                        found += 1
                except OSError:
                    continue
                if found >= limit:
                    return


def detect_site_dbs(cfg=None, dbs=None) -> dict:
    """{site name: [database, ...]} for databases named in the project's config files.
    A site's "db" setting overrides this: a name, or "" for none."""
    cfg = cfg or settings.load()
    dbs = dbs if dbs is not None else mysql.databases()
    names = {d["name"].lower(): d["name"] for d in dbs}
    key = (tuple((s["name"], s["root"], s.get("db")) for s in cfg["sites"]), tuple(sorted(names)))
    if _db_cache["key"] == key and time.time() - _db_cache["at"] < DB_SCAN_TTL:
        return _db_cache["data"]
    out = {}
    for s in cfg["sites"]:
        if s.get("db") is not None:
            out[s["name"]] = [s["db"]] if s["db"] else []
            continue
        hits = []
        for f in _config_files(project_folder(s)):
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for m in _TOKEN.finditer(text):
                n = names.get((m.group(1) or m.group(2) or "").lower())
                if n and n not in hits:
                    hits.append(n)
        out[s["name"]] = hits
    _db_cache.update(at=time.time(), key=key, data=out)
    return out
