"""PHP versions and their php.ini files.

Each version keeps its own php.ini next to php-cgi.exe. Settings are edited in place,
so manual edits to php.ini survive changes made from the app.
"""
import re
import shutil

from . import paths
from .winutil import run

MARKER = "; Managed by DevStack - settings below may be changed from the app.\n"

# Settings shown in the app. Anything else: edit php.ini directly.
EDITABLE = [
    "short_open_tag", "display_errors", "error_reporting", "memory_limit",
    "upload_max_filesize", "post_max_size", "max_execution_time", "max_input_time",
    "max_input_vars", "date.timezone",
]

BASELINE = {
    "short_open_tag": "On",
    "memory_limit": "512M",
    "upload_max_filesize": "256M",
    "post_max_size": "256M",
    "max_execution_time": "300",
    "max_input_time": "300",
    "max_input_vars": "5000",
    "date.timezone": "UTC",
}

DEFAULT_EXTENSIONS = [
    "bz2", "curl", "fileinfo", "gd", "gd2", "gettext", "intl", "mbstring", "exif", "mysqli",
    "openssl", "pdo_mysql", "pdo_sqlite", "sqlite3", "soap", "sockets", "sodium", "xsl", "zip",
]
ZEND_EXTENSIONS = {"opcache", "xdebug"}
HIDDEN_EXTENSIONS = {"zend_test", "dl_test", "phpdbg_webhelper"}

# Speed settings, applied once per php.ini (the marker line stops them coming back after a manual change).
TUNED = "; DevStack: OPcache and realpath cache set up. Delete this line to set them up again.\n"
PERFORMANCE = {
    "realpath_cache_size": "4096K",
    "realpath_cache_ttl": "120",
    "opcache.enable": "1",
    "opcache.enable_cli": "0",
    "opcache.memory_consumption": "256",
    "opcache.interned_strings_buffer": "16",
    "opcache.max_accelerated_files": "20000",
    "opcache.validate_timestamps": "1",     # with revalidate_freq 0, an edited file shows on the next request
    "opcache.revalidate_freq": "0",
}


def versions() -> list[str]:
    if not paths.PHP_ROOT.is_dir():
        return []
    found = [d.name[3:] for d in paths.PHP_ROOT.iterdir()
             if d.is_dir() and d.name.startswith("php") and (d / "php-cgi.exe").exists()]
    return sorted(found, key=paths.version_key)


def php_dir(ver: str):
    d = paths.PHP_ROOT / f"php{ver}"
    if not (d / "php-cgi.exe").exists():
        raise ValueError(f"PHP {ver} is not installed")
    return d


_timezones = {}


def timezones(ver: str) -> list[str]:
    """Timezone names this PHP version knows (for date.timezone), cached per version."""
    if ver not in _timezones:
        res = run([str(php_dir(ver) / "php.exe"), "-n", "-r", "echo implode(PHP_EOL, timezone_identifiers_list());"], timeout=20)
        names = [x.strip() for x in res.stdout.splitlines() if "/" in x or x.strip() == "UTC"]
        if not names:
            import zoneinfo
            names = sorted(z for z in zoneinfo.available_timezones() if "/" in z and not z.startswith(("Etc/", "SystemV/"))) + ["UTC"]
        _timezones[ver] = names
    return _timezones[ver]


def ini_path(ver: str):
    return php_dir(ver) / "php.ini"


# ---------------------------------------------------------------- ini editing

def _key_re(key: str, commented: bool):
    prefix = r"^[ \t]*;[ \t]*" if commented else r"^[ \t]*"
    return re.compile(prefix + re.escape(key) + r"[ \t]*=.*$", re.M)


def get_value(text: str, key: str) -> str | None:
    m = _key_re(key, False).search(text)
    if not m:
        return None
    val = m.group(0).split("=", 1)[1]
    val = re.sub(r"\s;.*$", "", val).strip()
    return val.strip('"')


def set_value(text: str, key: str, value: str) -> str:
    # Quote paths and anything ini would misparse; leave expressions like "E_ALL & ~E_NOTICE" bare.
    if re.search(r'[;=/:\\]', value) and not value.startswith('"'):
        value = f'"{value}"'
    line = f"{key} = {value}"
    for commented in (False, True):
        m = _key_re(key, commented).search(text)
        if m:
            return text[:m.start()] + line + text[m.end():]
    return text.rstrip("\n") + "\n" + line + "\n"


def _ext_name(value: str) -> str:
    v = value.strip().strip('"').replace("\\", "/").rsplit("/", 1)[-1]
    v = re.sub(r"^php_", "", v)
    v = re.sub(r"\.dll$", "", v, flags=re.I)
    return "xdebug" if v.startswith("xdebug") else v


_EXT_LINE = re.compile(r"^([ \t]*;?[ \t]*)(zend_)?extension[ \t]*=[ \t]*([^;\r\n]+?)[ \t]*(;.*)?$", re.M)


def enabled_extensions(text: str) -> set[str]:
    return {_ext_name(m.group(3)) for m in _EXT_LINE.finditer(text) if ";" not in m.group(1)}


def available_extensions(ver: str) -> list[str]:
    d = php_dir(ver)
    names = {_ext_name(f.name) for f in (d / "ext").glob("php_*.dll")}
    if list((d / "zend_ext").glob("php_xdebug*.dll")):
        names.add("xdebug")
    return sorted(names - HIDDEN_EXTENSIONS)


def _xdebug_dll(ver: str):
    dlls = sorted((php_dir(ver) / "zend_ext").glob("php_xdebug*.dll"))
    return dlls[-1] if dlls else None


def xdebug_dll(ver: str):
    """The installed Xdebug DLL for a PHP version, if any (public wrapper for other modules)."""
    return _xdebug_dll(ver)


_COMPILER_TO_VS = {"2019": "vs16", "2022": "vs17"}   # PHP's "Visual C++ <year>" -> xdebug.org's build tag


def build_info(ver: str) -> dict:
    """Thread safety, compiler (vs16/vs17) and arch of an installed PHP, for matching an Xdebug build."""
    out = run([str(php_dir(ver) / "php.exe"), "-i"], timeout=20).stdout
    ts = bool(re.search(r"Thread Safety\s*=>\s*enabled", out, re.I))
    m = re.search(r"Compiler\s*=>\s*Visual C\+\+ (\d+)", out)
    compiler = _COMPILER_TO_VS.get(m.group(1)) if m else None
    arch = "x86_64" if "x64" in (re.search(r"Architecture\s*=>\s*(\S+)", out) or [None, ""])[1] else "x86"
    return {"ts": ts, "compiler": compiler, "arch": arch}


def set_extension(text: str, ver: str, name: str, on: bool) -> str:
    # Comment out every active line for this extension, then enable exactly one.
    def disable(m):
        if ";" in m.group(1) or _ext_name(m.group(3)) != name:
            return m.group(0)
        return ";" + m.group(0).lstrip()
    text = _EXT_LINE.sub(disable, text)
    if not on:
        return text
    directive = "zend_extension" if name in ZEND_EXTENSIONS else "extension"
    # PHP before 7.2 only understands the file name (extension=php_curl.dll), and a full path for zend_extension.
    value = f"php_{name}.dll" if paths.version_key(ver) < (7, 2) else name
    if directive == "zend_extension" and paths.version_key(ver) < (7, 2):
        value = f'"{paths.fwd(php_dir(ver) / "ext" / value)}"'
    if name == "xdebug":
        dll = _xdebug_dll(ver)
        if not dll:
            raise ValueError(f"xdebug is not available for PHP {ver}")
        line = f'zend_extension = "{paths.fwd(dll)}"'
        block = ("\n[xdebug]\n" + line + "\nxdebug.mode = debug\nxdebug.start_with_request = trigger\n"
                 "xdebug.client_port = 9003\n")
        if "[xdebug]" in text:
            return re.sub(r"^\[xdebug\][ \t]*\r?\n", "[xdebug]\n" + line + "\n", text, count=1, flags=re.M)
        return text.rstrip("\n") + "\n" + block
    for m in _EXT_LINE.finditer(text):
        if ";" in m.group(1) and _ext_name(m.group(3)) == name and bool(m.group(2)) == (directive == "zend_extension"):
            return text[:m.start()] + f"{directive}={value}" + text[m.end():]
    return text.rstrip("\n") + f"\n{directive}={value}\n"


# ---------------------------------------------------------------- per-version ops

def read_ini(ver: str) -> str:
    return ini_path(ver).read_text(encoding="utf-8", errors="replace")


def write_ini(ver: str, text: str):
    ini_path(ver).write_text(text, encoding="utf-8")


def ensure_ini(ver: str, force: bool = False):
    """Create a DevStack php.ini from php.ini-development the first time."""
    ini = ini_path(ver)
    if ini.exists() and not force:
        if ini.read_text(encoding="utf-8", errors="replace").startswith(MARKER):
            return
        backup = ini.with_name("php.ini.original")
        if not backup.exists():
            shutil.copy2(ini, backup)
    d = php_dir(ver)
    text = MARKER + (d / "php.ini-development").read_text(encoding="utf-8", errors="replace")
    values = dict(BASELINE)
    values.update({
        "extension_dir": paths.fwd(d / "ext"),
        "error_log": paths.fwd(paths.LOGS / f"php{ver}_error.log"),
        "session.save_path": paths.fwd(paths.TMP / "sessions"),
        "upload_tmp_dir": paths.fwd(paths.TMP / "uploads"),
        "sys_temp_dir": paths.fwd(paths.TMP),
        "curl.cainfo": paths.fwd(paths.CACERT_BUNDLE),
        "openssl.cafile": paths.fwd(paths.CACERT_BUNDLE),
    })
    for k, v in values.items():
        text = set_value(text, k, v)
    available = set(available_extensions(ver))
    for ext in DEFAULT_EXTENSIONS:
        if ext in available:
            text = set_extension(text, ver, ext, True)
    ini.write_text(tune(text, ver), encoding="utf-8")


def tune(text: str, ver: str) -> str:
    """Turn on OPcache (dev-safe: edits still show at once) and a bigger realpath cache, once."""
    if TUNED in text:
        return text
    values = dict(PERFORMANCE)
    if paths.version_key(ver) >= (7, 0):
        # Windows: if a php-cgi process can't attach to the shared memory, OPcache falls back to this folder.
        cache = paths.TMP / "opcache" / ver
        cache.mkdir(parents=True, exist_ok=True)
        values["opcache.file_cache"] = paths.fwd(cache)
    if "opcache" in available_extensions(ver):      # PHP 8.5+ has OPcache built in, no DLL
        text = set_extension(text, ver, "opcache", True)
    for k, v in values.items():
        text = set_value(text, k, v)
    return text.rstrip("\n") + "\n\n" + TUNED


def ensure_tuned(ver: str) -> bool:
    """Apply tune() to an existing php.ini. True if it changed (php-cgi needs a restart)."""
    text = read_ini(ver)
    if TUNED in text:
        return False
    write_ini(ver, tune(text, ver))
    return True


def set_mail_catcher(ver: str, on: bool, port: int, sendmail_from: str = "devstack@localhost") -> bool:
    """Point mail() at the local mail catcher. Returns True if php.ini changed. Only ever turns it ON here -
    turning the app setting off leaves php.ini as it is, so mail() fails loudly instead of silently pretending to send."""
    if not on:
        return False
    old = read_ini(ver)
    text = set_value(old, "SMTP", "127.0.0.1")
    text = set_value(text, "smtp_port", str(port))
    text = set_value(text, "sendmail_from", sendmail_from)
    if text == old:
        return False
    write_ini(ver, text)
    return True


def get_config(ver: str) -> dict:
    text = read_ini(ver)
    enabled = enabled_extensions(text)
    return {
        "version": ver,
        "ini": paths.fwd(ini_path(ver)),
        "settings": {k: get_value(text, k) or "" for k in EDITABLE},
        "extensions": [{"name": e, "enabled": e in enabled} for e in available_extensions(ver)],
    }


def update_config(ver: str, settings: dict | None = None, extensions: dict | None = None):
    text = read_ini(ver)
    for k, v in (settings or {}).items():
        if k not in EDITABLE:
            raise ValueError(f"{k} is not editable from the app")
        text = set_value(text, k, str(v).strip())
    for name, on in (extensions or {}).items():
        text = set_extension(text, ver, name, bool(on))
    write_ini(ver, text)


def copy_setup(old: str, new: str):
    """Give a newly installed patch release the php.ini and extra extensions of the old one (same branch)."""
    src, dst = php_dir(old), php_dir(new)
    for sub in ("ext", "zend_ext"):          # e.g. xdebug or PECL DLLs added by hand
        if (src / sub).is_dir():
            (dst / sub).mkdir(exist_ok=True)
            for f in (src / sub).glob("*.dll"):
                if not (dst / sub / f.name).exists():
                    shutil.copy2(f, dst / sub / f.name)
    text = read_ini(old)
    cache = paths.TMP / "opcache"
    for a, b in ((paths.fwd(src), paths.fwd(dst)), (str(src), str(dst)), (f"php{old}_error.log", f"php{new}_error.log"),
                 (paths.fwd(cache / old), paths.fwd(cache / new))):
        text = text.replace(a, b)
    (cache / new).mkdir(parents=True, exist_ok=True)
    write_ini(new, text)
