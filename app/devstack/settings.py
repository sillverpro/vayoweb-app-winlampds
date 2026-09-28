"""Persistent app state (ports, run mode, sites) in config/devstack.json."""
import json
import threading

from . import paths

DEFAULT_SITE = "localhost"
TLD = "test"

_lock = threading.RLock()

DEFAULTS = {
    "ports": {"http": 80, "https": 443, "mysql": 3306},
    "run_mode": "service",          # "service" = Windows services (auto-start at boot), "process" = child processes
    "default_php": None,
    "cli_php": None,                # PHP version bin/cli/php.bat falls back to (None = default_php)
    "mysql_root_password": "",
    "apache": None,                 # active folder in bin/apache, e.g. "apache2.4.68" (None = newest)
    "mysql": None,                  # active folder in bin/mysql
    "close_to_tray": True,          # the window's X button hides DevStack in the tray instead of quitting
    "backup": {"enabled": False, "dbs": [], "keep": 7},   # dbs: [] = every non-system database
    "mail_catcher": False,          # local SMTP server (mailcatch.py) that saves mail instead of sending it
    "mail_port": 1025,
    "sites": [],
}


def load() -> dict:
    with _lock:
        data = {}
        if paths.SETTINGS_FILE.exists():
            data = json.loads(paths.SETTINGS_FILE.read_text(encoding="utf-8"))
        merged = json.loads(json.dumps(DEFAULTS))
        merged.update(data)
        merged["ports"] = {**DEFAULTS["ports"], **data.get("ports", {})}
        return merged


def save(data: dict):
    with _lock:
        paths.SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = paths.SETTINGS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(paths.SETTINGS_FILE)


def find_site(data: dict, name: str) -> dict | None:
    return next((s for s in data["sites"] if s["name"] == name), None)


def site_urls(data: dict, site: dict) -> dict:
    p = data["ports"]
    http = "" if p["http"] == 80 else f":{p['http']}"
    https = "" if p["https"] == 443 else f":{p['https']}"
    urls = {"http": f"http://{site['domain']}{http}/"}
    if site.get("ssl"):
        urls["https"] = f"https://{site['domain']}{https}/"
    return urls
