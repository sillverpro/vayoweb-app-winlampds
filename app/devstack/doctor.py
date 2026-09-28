"""Doctor: a list of environment checks with a pass/warn/fail status and, where safe, a fix the UI can run.

Read-only: this module only inspects the system. Fixes are existing endpoints the UI calls on its own
(sync_hosts, trust_ca, renew_certs, install_php, the "service" start) - nothing here writes anything itself.
"""
import shutil
import winreg
from pathlib import Path

from . import apache, cli, hosts, mysql, paths, php, services, settings, ssl
from .winutil import port_in_use, port_owner, run

VC_REDIST_URL = "https://aka.ms/vs/17/release/vc_redist.x64.exe"
# Apache/MySQL services other local servers install; they fight over ports 80/443/3306.
OTHER_SERVICES = ["wampapache64", "wampmysqld64", "Apache2.4"]


def _check(id, label, status, detail="", fix=None, fix_args=None):
    return {"id": id, "label": label, "status": status, "detail": detail, "fix": fix, "fix_args": fix_args or []}


def _vcredist_present() -> bool:
    for d in (r"C:\Windows\System32", r"C:\Windows\SysWOW64"):
        if (Path(d) / "vcruntime140.dll").exists():
            return True
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64"):
            return True
    except OSError:
        return False


def _other_services() -> list[str]:
    """Other local servers' Apache/MySQL services, if still installed and running or set to auto-start."""
    found = []
    for name in OTHER_SERVICES:
        r = run(["sc", "query", name])
        if "1060" in r.stdout or r.returncode == 1060:
            continue
        if "RUNNING" in r.stdout:
            found.append(name)
        elif "AUTO_START" in run(["sc", "qc", name]).stdout:
            found.append(f"{name} (Auto start, not running now)")
    return found


def _first_php_on_path() -> str | None:
    """The php a new console would run: system PATH, then user PATH (read fresh, our own env is stale)."""
    dirs = []
    for hive, key in ((winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
                      (winreg.HKEY_CURRENT_USER, "Environment")):
        try:
            with winreg.OpenKey(hive, key) as k:
                dirs += winreg.ExpandEnvironmentStrings(winreg.QueryValueEx(k, "Path")[0]).split(";")
        except OSError:
            pass
    for d in filter(None, (x.strip() for x in dirs)):
        for name in ("php.exe", "php.bat", "php.cmd"):
            if (Path(d) / name).is_file():
                return str(Path(d) / name)
    return None


def run_checks() -> list[dict]:
    cfg = settings.load()
    out = []

    for kind, port, label in (
        ("apache", cfg["ports"]["http"], f"Port {cfg['ports']['http']} (HTTP)"),
        ("apache", cfg["ports"]["https"], f"Port {cfg['ports']['https']} (HTTPS)"),
        ("mysql", cfg["ports"]["mysql"], f"Port {cfg['ports']['mysql']} (MySQL)"),
    ):
        ours = services.status(cfg, kind) == "running"
        in_use = port_in_use(port)
        if in_use and not ours:
            owner = port_owner(port) or "another program"
            hint = " - looks like IIS, stop the W3SVC service" if "W3SVC" in owner else ""
            out.append(_check(f"port-{port}", label, "warn", f"Held by {owner}{hint}."))
        else:
            out.append(_check(f"port-{port}", label, "pass", "In use by DevStack." if ours else "Free."))

    others = _other_services()
    out.append(_check("other-servers", "Other local servers", "warn" if others else "pass",
                      f"Still around: {', '.join(others)}. Set them to Manual (services.msc) so they don't take the ports."
                      if others else "Not running."))

    vc = _vcredist_present()
    out.append(_check("vcredist", "Visual C++ runtime", "pass" if vc else "fail",
                      "Present." if vc else "vcruntime140.dll not found - PHP and MySQL need the VC++ redistributable.",
                      fix=None if vc else "open_url", fix_args=[] if vc else [VC_REDIST_URL]))

    trusted = ssl.is_ca_trusted()
    out.append(_check("ca", "Local CA trusted", "pass" if trusted else "warn",
                      "Trusted by Windows." if trusted else "Not trusted yet - HTTPS sites show a warning.",
                      fix=None if trusted else "trust_ca"))

    domains_in_hosts = set(hosts.current_domains())
    for s in cfg["sites"]:
        ok = s["domain"] in domains_in_hosts
        out.append(_check(f"hosts-{s['domain']}", f"Hosts entry: {s['domain']}", "pass" if ok else "warn",
                          "Present." if ok else "Missing from the hosts file.",
                          fix=None if ok else "sync_hosts"))

    ok, apache_out = apache.test_config()
    out.append(_check("apache-conf", "Apache config (httpd -t)", "pass" if ok else "fail",
                      "OK." if ok else apache_out.strip()[-2000:]))

    for s in cfg["sites"]:
        exists = Path(s["root"]).is_dir()
        out.append(_check(f"docroot-{s['domain']}", f"Folder for {s['domain']}", "pass" if exists else "fail",
                          s["root"] if exists else f"{s['root']} does not exist."))
        installed = s["php"] in php.versions()
        out.append(_check(f"php-{s['domain']}", f"PHP for {s['domain']}", "pass" if installed else "fail",
                          f"PHP {s['php']}." if installed else f"PHP {s['php']} is not installed.",
                          fix=None if installed else "install_php", fix_args=[] if installed else [s["php"]]))
        if s.get("ssl"):
            info = ssl.cert_info(s["domain"])
            if info["state"] in ("expiring", "expired"):
                detail = "Expired." if info["state"] == "expired" else f"Expires in {info['days_left']} days."
                out.append(_check(f"cert-{s['domain']}", f"Certificate for {s['domain']}",
                                  "fail" if info["state"] == "expired" else "warn", detail,
                                  fix="renew_certs", fix_args=[[s["domain"]]]))

    if services.status(cfg, "mysql") != "running":
        out.append(_check("mysql-reachable", "MySQL reachable", "warn", "MySQL is not running.",
                          fix="service", fix_args=["mysql", "start"]))
    else:
        args = [str(mysql.bin_dir() / "mysqladmin.exe"), "-uroot", "-h127.0.0.1", f"-P{cfg['ports']['mysql']}"]
        if cfg.get("mysql_root_password"):
            args.append(f"-p{cfg['mysql_root_password']}")
        ok = run(args + ["ping"], timeout=15).returncode == 0
        out.append(_check("mysql-reachable", "MySQL reachable", "pass" if ok else "fail",
                          "Responding to ping." if ok else "Did not respond - check the saved root password."))

    php_first = _first_php_on_path()
    if cli.on_path() and php_first and Path(php_first).parent != paths.CLI:
        out.append(_check("cli-path", "php on PATH", "warn",
                          f"{php_first} comes first (system PATH is searched before the user PATH), so plain "
                          f"`php` doesn't use DevStack's version switch. Remove it from the system PATH."))
    elif cli.on_path():
        out.append(_check("cli-path", "php on PATH", "pass", "DevStack's php.bat comes first."))

    free_gb = shutil.disk_usage(paths.ROOT.anchor).free / 1e9
    out.append(_check("disk", "Free disk space", "pass" if free_gb > 5 else "warn",
                      f"{free_gb:.1f} GB free on {paths.ROOT.anchor}"))

    return out
