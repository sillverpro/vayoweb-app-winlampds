"""Filesystem layout of a DevStack install. Everything lives under ROOT."""
import re
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    ROOT = Path(sys.executable).resolve().parent
else:
    ROOT = Path(__file__).resolve().parents[2]

APP = ROOT / "app"
UI = (Path(sys._MEIPASS) / "ui") if getattr(sys, "frozen", False) else APP / "ui"
TEMPLATES = (Path(sys._MEIPASS) / "templates") if getattr(sys, "frozen", False) else APP / "templates"
CHANGELOG = (Path(sys._MEIPASS) if getattr(sys, "frozen", False) else ROOT) / "CHANGELOG.md"

BIN = ROOT / "bin"
APACHE_ROOT = BIN / "apache"
PHP_ROOT = BIN / "php"
MYSQL_ROOT = BIN / "mysql"
PMA = ROOT / "apps" / "phpmyadmin"
CLI = BIN / "cli"                       # generated php.bat / composer.bat shims (see cli.py)
COMPOSER = BIN / "composer"
COMPOSER_PHAR = COMPOSER / "composer.phar"

CONFIG = ROOT / "config"
SETTINGS_FILE = CONFIG / "devstack.json"
APACHE_CONF = CONFIG / "apache" / "httpd.conf"
SITES_CONF = CONFIG / "apache" / "sites"
MY_INI = CONFIG / "mysql" / "my.ini"
PHP_SITE_CONFIG = CONFIG / "php-site"   # per-site PHP_INI_SCAN_DIR (see apache.py / core.py, feature L)

SSL = ROOT / "ssl"
CA_CRT = SSL / "ca" / "devstack-ca.crt"
CA_KEY = SSL / "ca" / "devstack-ca.key"
SITE_CERTS = SSL / "sites"
CACERT_BUNDLE = SSL / "cacert.pem"

LOGS = ROOT / "logs"
SITE_LOGS = LOGS / "sites"
TMP = ROOT / "tmp"
DOWNLOADS = TMP / "downloads"
WWW = ROOT / "www"
MYSQL_DATA = ROOT / "data" / "mysql"
DB_EXPORTS = ROOT / "data" / "exports"      # .sql backups made from the Database page
MAIL_DIR = ROOT / "data" / "mail"           # .eml files saved by the mail catcher (mailcatch.py)

HOSTS_FILE = Path(r"C:\Windows\System32\drivers\etc\hosts")


def fwd(p) -> str:
    """Path as a forward-slash string, which Apache, PHP and MySQL all accept on Windows."""
    return str(p).replace("\\", "/")


def version_key(name: str) -> tuple:
    """"apache2.4.62.1" -> (2, 4, 62, 1). Pre-releases ("8.6.0RC2") sort before the final release."""
    nums = tuple(int(x) for x in re.findall(r"\d+", name.split("RC")[0].split("-")[0]))
    return nums + (0 if re.search(r"RC|alpha|beta|-dev", name, re.I) else 1,)


def installed_dirs(parent: Path) -> list[Path]:
    """Version folders, oldest first. Folders starting with "." are unfinished installs."""
    if not parent.is_dir():
        return []
    dirs = [d for d in parent.iterdir() if d.is_dir() and not d.name.startswith((".", "modules"))]
    return sorted(dirs, key=lambda d: version_key(d.name))


def _active_dir(parent: Path, key: str) -> Path | None:
    from . import settings   # settings imports paths
    chosen = settings.load().get(key)
    if chosen and (parent / chosen).is_dir():
        return parent / chosen
    dirs = installed_dirs(parent)
    return dirs[-1] if dirs else None


def apache_dir() -> Path | None:
    return _active_dir(APACHE_ROOT, "apache")


def mysql_dir() -> Path | None:
    return _active_dir(MYSQL_ROOT, "mysql")


def ensure_dirs():
    for d in (CONFIG, SITES_CONF, MY_INI.parent, CA_CRT.parent, SITE_CERTS, LOGS, SITE_LOGS,
              TMP, DOWNLOADS, TMP / "sessions", TMP / "uploads", TMP / "pma", WWW, MYSQL_DATA, DB_EXPORTS,
              CLI, COMPOSER, PHP_SITE_CONFIG, MAIL_DIR):
        d.mkdir(parents=True, exist_ok=True)
