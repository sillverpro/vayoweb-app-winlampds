"""High-level operations used by the UI and CLI: setup, sites, applying config."""
import fnmatch
import json
import os
import re
from pathlib import Path
import shutil
import threading
import time
import zipfile

from . import apache, cli, hosts, mysql, paths, php, services, settings, ssl
from .settings import DEFAULT_SITE, TLD
from .winutil import is_admin, port_in_use, spawn_console

_lock = threading.RLock()

_NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*$")
_ALIAS_RE = re.compile(r"^(\*\.)?[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*$")

PLACEHOLDER = """<?php
// New DevStack site. Replace this file with your project.
?><!doctype html>
<html><head><meta charset="utf-8"><title><?= $_SERVER['HTTP_HOST'] ?></title>
<style>body{font:16px system-ui,sans-serif;max-width:640px;margin:15vh auto;padding:0 16px;color:#222}
code{background:#f2f2f2;padding:2px 6px;border-radius:4px}</style></head>
<body><h1><?= htmlspecialchars($_SERVER['HTTP_HOST']) ?></h1>
<p>It works. PHP <?= PHP_VERSION ?>, document root <code><?= htmlspecialchars(__DIR__) ?></code></p>
</body></html>
"""


def _default_php(cfg):
    vers = php.versions()
    if cfg.get("default_php") in vers:
        return cfg["default_php"]
    # Prefer the newest 8.3, which phpMyAdmin 5.2 runs cleanly on, else the newest installed.
    v83 = [v for v in vers if v.startswith("8.3.")]
    return (v83 or vers or [None])[-1]


def normalize_name(name: str) -> str:
    name = name.strip().lower()
    if name.endswith("." + TLD):
        name = name[: -len(TLD) - 1]
    if not _NAME_RE.match(name):
        raise ValueError("Use letters, numbers, dashes and dots only (e.g. shop or api.shop)")
    return name


# ---------------------------------------------------------------- setup

def _site_aliases(cfg: dict) -> list[str]:
    """Every site's non-wildcard aliases (a wildcard like *.shop.test can't go in the hosts file)."""
    out = []
    for s in cfg["sites"]:
        out += [a for a in s.get("aliases", []) if not a.startswith("*.")]
    return out


def setup_state() -> dict:
    cfg = settings.load()
    wanted = {s["domain"] for s in cfg["sites"]} | set(_site_aliases(cfg))
    return {
        "binaries": bool(paths.apache_dir() and php.versions() and paths.mysql_dir()),
        "initialized": paths.SETTINGS_FILE.exists() and bool(cfg["sites"]),
        "admin": is_admin(),
        "ca_trusted": ssl.is_ca_trusted(),
        "services_installed": all(services.service_state(k) != "not-installed" for k in ("apache", "mysql")),
        "hosts_ok": wanted <= set(hosts.current_domains()),
    }


def initialize(ports: dict | None = None, run_mode: str | None = None, log=print):
    """First-time setup. Safe to run again: existing data and sites are kept."""
    with _lock:
        paths.ensure_dirs()
        cfg = settings.load()
        if ports:
            cfg["ports"].update(ports)
        if run_mode:
            cfg["run_mode"] = run_mode
        cfg["default_php"] = _default_php(cfg)

        for v in php.versions():
            log(f"php.ini for PHP {v}")
            php.ensure_ini(v)

        log("Local certificate authority")
        ssl.ensure_ca()

        if not settings.find_site(cfg, DEFAULT_SITE):
            root = paths.WWW / DEFAULT_SITE
            root.mkdir(parents=True, exist_ok=True)
            tpl = paths.TEMPLATES / "localhost"
            if tpl.is_dir() and not any(root.iterdir()):
                shutil.copytree(tpl, root, dirs_exist_ok=True)
            cfg["sites"].insert(0, {"name": DEFAULT_SITE, "domain": f"{DEFAULT_SITE}.{TLD}",
                                    "root": paths.fwd(root), "php": cfg["default_php"], "ssl": True})
        settings.save(cfg)

        log("MySQL config")
        mysql.write_my_ini(cfg)
        mysql.write_pma_config(cfg)
        if not mysql.datadir_initialized():
            log("Initializing MySQL data directory (takes a minute)")
            mysql.init_datadir()

        log("Apache config")
        apache.write_all(cfg)
        ok, out = apache.test_config()
        if not ok:
            raise RuntimeError("Apache config test failed:\n" + out)

        log("PHP CLI shims")
        cli.write_shims(cfg)
        return cfg


def finish_admin_setup(log=print):
    """Steps that need admin: trust CA, hosts file, Windows services."""
    if not is_admin():
        raise PermissionError("Run DevStack as administrator to finish setup.")
    cfg = settings.load()
    if not ssl.is_ca_trusted():
        log("Trusting local CA")
        ssl.trust_ca(machine=True)
    log("Updating hosts file")
    hosts.sync([s["domain"] for s in cfg["sites"]], _site_aliases(cfg))
    if cfg["run_mode"] == "service":
        log("Installing Windows services")
        services.install_services()


# ---------------------------------------------------------------- apply

def apply(cfg: dict, restart_apache=True):
    """Write config, update hosts, test and restart Apache. Raises with the Apache error on bad config."""
    apache.write_all(cfg)
    ok, out = apache.test_config()
    if not ok:
        raise RuntimeError("Apache config test failed:\n" + out)
    if is_admin():
        hosts.sync([s["domain"] for s in cfg["sites"]], _site_aliases(cfg))
    if restart_apache and services.status(cfg, "apache") == "running":
        services.restart(cfg, "apache")


def _mtime(p) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


_reconcile_failed = None   # signature of the last failed attempt, so the 5s poll doesn't retry it forever
_tuned = False              # the once-per-app-start step in reconcile() has run


def reconcile() -> list[str]:
    """Catch up with changes made outside the app (a script, an older window, a hand-edited devstack.json):
    rewrite Apache config if settings are newer, fix the hosts file, restart Apache if it runs old config."""
    global _reconcile_failed, _tuned
    if not _lock.acquire(blocking=False):
        return []
    done = []
    try:
        cfg = settings.load()
        if not _tuned:
            # Once per app start: pick up config changes from a newer DevStack (e.g. HTTP/2), and php.ini speed settings.
            _tuned = True
            apache.write_all(cfg)
            changed = []
            for v in php.versions():
                try:
                    tuned = php.ensure_tuned(v)
                    # A PHP version installed after the mail catcher was turned on gets its SMTP settings here.
                    mail = php.set_mail_catcher(v, bool(cfg.get("mail_catcher")), cfg.get("mail_port", 1025))
                    if tuned or mail:
                        changed.append(v)
                except (OSError, ValueError):
                    pass
            if changed and services.status(cfg, "apache") == "running":
                services.restart(cfg, "apache")
                done.append(f"php.ini updated for PHP {', '.join(changed)}")
        try:
            cli.ensure_shims(cfg)
        except OSError:
            pass
        conf_files = [paths.APACHE_CONF, paths.SITES_CONF, *paths.SITES_CONF.glob("*.conf")]
        if _mtime(paths.SETTINGS_FILE) > _mtime(paths.APACHE_CONF):
            apache.write_all(cfg)
            conf_files = [paths.APACHE_CONF, paths.SITES_CONF, *paths.SITES_CONF.glob("*.conf")]
        domains = [s["domain"] for s in cfg["sites"]]
        aliases = _site_aliases(cfg)
        if is_admin() and not (set(domains) | set(aliases)) <= set(hosts.current_domains()):
            try:
                hosts.sync(domains, aliases)
                done.append("hosts file updated")
            except OSError:
                pass
        started = _mtime(services.PID_FILES["apache"])
        newest = max(_mtime(f) for f in conf_files)
        sig = (started, newest)
        if newest > started and sig != _reconcile_failed and services.status(cfg, "apache") == "running":
            try:
                ok, out = apache.test_config()
                if not ok:
                    raise RuntimeError(out)
                services.restart(cfg, "apache")
                done.append("Apache restarted with the new site config")
            except Exception:
                _reconcile_failed = sig
    finally:
        _lock.release()
    return done


def _transaction(mutate):
    """Apply a settings change; roll back settings and Apache config if it fails."""
    with _lock:
        before = settings.load()
        cfg = settings.load()
        result = mutate(cfg)
        settings.save(cfg)
        try:
            apply(cfg)
        except Exception:
            settings.save(before)
            try:
                apply(before, restart_apache=False)
            except Exception:
                pass
            raise
        return result


# ---------------------------------------------------------------- sites

def create_site(name: str, root: str = "", php_version: str = "", use_ssl: bool = True, create_db: bool = False,
                db: str | None = None) -> dict:
    """create_db makes a new database + user; otherwise `db` links an existing one ("" = none, None = auto-detect)."""
    name = normalize_name(name)
    creds = {}

    def mutate(cfg):
        if settings.find_site(cfg, name):
            raise ValueError(f"{name}.{TLD} already exists")
        ver = php_version or cfg.get("default_php") or _default_php(cfg)
        php.php_dir(ver)
        folder = paths.WWW / name if not root else Path(root)
        folder.mkdir(parents=True, exist_ok=True)
        if not any(folder.iterdir()):
            (folder / "index.php").write_text(PLACEHOLDER, encoding="utf-8")
        site = {"name": name, "domain": f"{name}.{TLD}", "root": paths.fwd(folder), "php": ver, "ssl": bool(use_ssl),
                "created": int(time.time())}
        if create_db:
            db_name = re.sub(r"[^a-z0-9_]", "_", name.lower())
            creds.update(mysql.create_database(cfg, db_name, db_name))
            site["db"] = creds["database"]
        elif db is not None:
            site["db"] = db
        cfg["sites"].append(site)
        return site

    site = _with_warnings(_transaction(mutate))
    return {**site, "db_credentials": creds} if creds else site


LAN_PORT_BASE = 8100


def _pick_lan_port(cfg: dict) -> int:
    """First free port from 8100, unique among sites and not one of the main ports."""
    used = {s["lan_port"] for s in cfg["sites"] if s.get("lan_port")} | set(cfg["ports"].values())
    port = LAN_PORT_BASE
    while port in used or port_in_use(port):
        port += 1
    return port


def lan_ip() -> str | None:
    """The machine's LAN-routable IPv4, e.g. for the "share on LAN" QR code. Best-effort: asks the OS which
    local address it would use to reach the internet - no packet is actually sent (UDP connect() is local-only)."""
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
    except OSError:
        return None
    if ip.startswith(("127.", "169.254.")):
        return None
    return ip


def allow_lan_firewall(port: int):
    """Add a Windows Firewall inbound rule for a shared site's port. Needs admin (the app runs elevated)."""
    from .winutil import run
    name = f"DevStack LAN {port}"
    r = run(["netsh", "advfirewall", "firewall", "add", "rule", f"name={name}", "dir=in", "action=allow",
            "protocol=TCP", f"localport={port}"], timeout=20)
    if r.returncode != 0:
        raise RuntimeError((r.stdout + r.stderr).strip() or "netsh failed")


def remove_lan_firewall(port: int):
    from .winutil import run
    run(["netsh", "advfirewall", "firewall", "delete", "rule", f"name=DevStack LAN {port}"], timeout=20)


def _suggest_name(folder_name: str) -> str:
    name = re.sub(r"[^a-z0-9.-]+", "-", folder_name.lower())
    return re.sub(r"-{2,}", "-", name).strip("-.")


_INDEX_FILES = ("index.php", "index.html", "index.htm")
_SKIP_DIRS = {"vendor", "node_modules", ".git", ".svn", ".idea", "storage", "cache", "tmp", "logs"}


def _suggest_docroot(folder: Path) -> Path:
    """Laravel, Symfony, CodeIgniter 4 etc. serve from public/, Yii from web/."""
    if any((folder / f).is_file() for f in _INDEX_FILES):
        return folder
    for sub in ("public", "web", "public_html", "htdocs"):
        if (folder / sub / "index.php").is_file() or (folder / sub / "index.html").is_file():
            return folder / sub
    return folder


def _docroot_candidates(folder: Path, depth: int = 3, limit: int = 20) -> list[Path]:
    """Folders up to `depth` levels down that have an index file, e.g. web/production and web/staging.
    Doesn't look inside a folder that already has one (so no wp-admin/, admin/ ... under a site)."""
    out = []

    def walk(d: Path, level: int):
        if len(out) >= limit:
            return
        if any((d / f).is_file() for f in _INDEX_FILES):
            out.append(d)
            return
        if level >= depth:
            return
        try:
            subs = sorted((p for p in d.iterdir() if p.is_dir()), key=lambda p: p.name.lower())
        except OSError:
            return
        for s in subs:
            if not s.name.startswith(".") and s.name.lower() not in _SKIP_DIRS:
                walk(s, level + 1)

    walk(folder, 0)
    return out


def scan_folder(folder: str = "") -> list[dict]:
    """Subfolders of `folder` (default www) that are not a site yet, with a suggested name and docroot."""
    base = Path(folder) if folder else paths.WWW
    if not base.is_dir():
        raise ValueError(f"Folder not found: {base}")
    cfg = settings.load()
    used_roots = {s["root"].lower().rstrip("/") for s in cfg["sites"]}
    used_names = {s["name"] for s in cfg["sites"]}
    found = []
    for d in sorted(base.iterdir(), key=lambda p: p.name.lower()):
        if not d.is_dir() or d.name.startswith(".") or d == paths.WWW / DEFAULT_SITE:
            continue
        if paths.fwd(d).lower() in used_roots:
            continue
        # Docroots not used by a site yet, so web/staging still shows up after web/production was added.
        with_index = [paths.fwd(p) for p in _docroot_candidates(d)]
        roots = [r for r in dict.fromkeys([paths.fwd(_suggest_docroot(d))] + with_index) if r.lower() not in used_roots]
        if not roots:
            continue
        # Prefer a folder with an index file, e.g. 3477_ADP/production when 3477_ADP itself has none.
        root = next((r for r in roots if r in with_index), roots[0])
        name = _suggest_name(d.name)
        found.append({"folder": paths.fwd(d), "root": root, "roots": roots, "name": name,
                      "taken": name in used_names})
    return found


def _wildcard_hits(pattern: str, host: str) -> bool:
    # Apache's * in ServerAlias matches any characters, dots included.
    return fnmatch.fnmatchcase(host, pattern)


def alias_conflicts(cfg: dict) -> list[str]:
    """Wildcard aliases that swallow another site: Apache uses the first vhost that matches, and the
    site files load alphabetically, so *.shop.test on shop.test also catches staging.shop.test."""
    out = []
    for a in cfg["sites"]:
        wild = [x for x in a.get("aliases", []) if "*" in x]
        for b in cfg["sites"]:
            if b is a or not wild or apache.site_conf_path(a).name >= apache.site_conf_path(b).name:
                continue
            hosts_b = [b["domain"], f"www.{b['domain']}"] + [x for x in b.get("aliases", []) if "*" not in x]
            for w in wild:
                hit = next((h for h in hosts_b if _wildcard_hits(w, h)), None)
                if hit:
                    out.append(f"{w} (alias of {a['domain']}) catches {hit} - it would open {a['domain']}. "
                               f"Remove the wildcard or list the aliases you need one by one.")
                    break
    return out


def _with_warnings(result, cfg=None):
    warnings = alias_conflicts(cfg or settings.load())
    return {**result, "warnings": warnings} if warnings else result


def import_sites(items: list[dict], php_version: str = "", use_ssl: bool = True) -> dict:
    """Add many sites with one config write and one Apache restart. items: [{name, root, php?, db?}]
    (db: an existing database name, "" = none, missing/None = auto-detect)."""
    def mutate(cfg):
        added, seen = [], set()
        for it in items:
            name = normalize_name(it["name"])
            if name in seen or settings.find_site(cfg, name):
                raise ValueError(f"{name}.{TLD} is used twice or already exists")
            seen.add(name)
            folder = Path(it["root"])
            if not folder.is_dir():
                raise ValueError(f"Folder not found: {folder}")
            ver = it.get("php") or php_version or cfg.get("default_php") or _default_php(cfg)
            php.php_dir(ver)
            site = {"name": name, "domain": f"{name}.{TLD}", "root": paths.fwd(folder), "php": ver, "ssl": bool(use_ssl),
                "created": int(time.time())}
            if it.get("db") is not None:
                site["db"] = it["db"]
            cfg["sites"].append(site)
            added.append(site)
        return added

    return _with_warnings({"sites": _transaction(mutate)})


def update_site(name: str, changes: dict) -> dict:
    def mutate(cfg):
        site = settings.find_site(cfg, name)
        if not site:
            raise ValueError(f"Site {name} not found")
        if "php" in changes:
            php.php_dir(changes["php"])
            site["php"] = changes["php"]
        if "root" in changes and changes["root"]:
            folder = Path(changes["root"])
            if not folder.is_dir():
                raise ValueError(f"Folder not found: {folder}")
            site["root"] = paths.fwd(folder)
        if "ssl" in changes:
            site["ssl"] = bool(changes["ssl"])
        if "db" in changes:   # None = detect from the project's config files, "" = no database
            site["db"] = changes["db"]
        if "aliases" in changes:
            aliases = []
            for a in changes["aliases"] or []:
                a = a.strip().lower()
                if not a:
                    continue
                if not _ALIAS_RE.match(a):
                    raise ValueError(f"Bad alias: {a} (use e.g. admin.{site['domain']} or *.{site['domain']})")
                aliases.append(a)
            site["aliases"] = aliases
        if "apache_extra" in changes:
            site["apache_extra"] = changes["apache_extra"]
        if "lan" in changes:
            if changes["lan"]:
                if not site.get("lan_port"):
                    site["lan_port"] = _pick_lan_port(cfg)
            else:
                site.pop("lan_port", None)
        return site

    return _with_warnings(_transaction(mutate))


def delete_site(name: str, delete_files=False):
    if name == DEFAULT_SITE:
        raise ValueError("The default site can't be deleted")
    removed = {}

    def mutate(cfg):
        site = settings.find_site(cfg, name)
        if not site:
            raise ValueError(f"Site {name} not found")
        cfg["sites"].remove(site)
        removed.update(site)

    _transaction(mutate)
    ssl.remove_site_cert(removed["domain"])
    if delete_files:
        folder = Path(removed["root"])
        # Only ever delete folders DevStack itself created under www/.
        if folder.resolve().parent == paths.WWW.resolve():
            shutil.rmtree(folder, ignore_errors=True)


# ---------------------------------------------------------------- clone / export / import (feature M)

_COPY_SKIP = shutil.ignore_patterns(".git", "node_modules")


def clone_site(job, name: str, new_name: str) -> dict:
    """Copy a site's folder to a new name, copy its database (if it has one) via dump|import, and create
    the new site with the same PHP version."""
    new_name = normalize_name(new_name)
    cfg = settings.load()
    site = settings.find_site(cfg, name)
    if not site:
        raise ValueError(f"Site {name} not found")
    if settings.find_site(cfg, new_name):
        raise ValueError(f"{new_name}.{TLD} already exists")
    src_root, dest_root = Path(site["root"]), paths.WWW / new_name
    if dest_root.exists():
        raise ValueError(f"{dest_root} already exists")
    job.update(f"Copying {src_root.name}")
    shutil.copytree(src_root, dest_root, ignore=_COPY_SKIP)

    new_db = None
    src_db = site.get("db")
    if src_db and src_db in {d["name"] for d in mysql.databases()}:
        new_db = re.sub(r"[^a-z0-9_]", "_", new_name.lower())
        tmp_sql = paths.TMP / f"clone-{name}-{int(time.time())}.sql"
        try:
            mysql.export_db(cfg, src_db, tmp_sql, job, standalone=False)
            mysql.create_database(cfg, new_db)
            mysql.import_sql(cfg, str(tmp_sql), job, database=new_db)
        finally:
            tmp_sql.unlink(missing_ok=True)

    new_site = create_site(new_name, str(dest_root), site["php"], site.get("ssl", True))
    if new_db:
        new_site = update_site(new_name, {"db": new_db})
    return new_site


def export_site(job, name: str, include_git: bool = False) -> dict:
    """data/exports/<site>-<ts>.zip: the project folder (skip node_modules, .git unless asked to keep it),
    database.sql if the site has a database, and site.json (name, php, ssl, db, aliases)."""
    cfg = settings.load()
    site = settings.find_site(cfg, name)
    if not site:
        raise ValueError(f"Site {name} not found")
    root = Path(site["root"])
    dest = paths.DB_EXPORTS / f"{name}-{time.strftime('%Y%m%d-%H%M%S')}.zip"
    dest.parent.mkdir(parents=True, exist_ok=True)
    skip = {"node_modules"} | (set() if include_git else {".git"})
    files = [f for f in root.rglob("*") if f.is_file() and not skip & set(f.relative_to(root).parts)]

    db_name = site.get("db")
    sql_path = None
    if db_name and db_name in {d["name"] for d in mysql.databases()}:
        sql_path = paths.TMP / f"export-{name}-{int(time.time())}.sql"
        mysql.export_db(cfg, db_name, sql_path, job, standalone=False)

    site_json = json.dumps({"name": site["name"], "php": site["php"], "ssl": site.get("ssl", True),
                            "db": db_name, "aliases": site.get("aliases", [])}, indent=2)
    try:
        job.update("Zipping", 0)
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
            for i, f in enumerate(files):
                z.write(f, arcname=str(Path("project") / f.relative_to(root)))
                if i % 200 == 0:
                    job.update(f"Zipping ({i}/{len(files)})", i / len(files) if files else None)
            if sql_path:
                z.write(sql_path, arcname="database.sql")
            z.writestr("site.json", site_json)
    finally:
        if sql_path:
            sql_path.unlink(missing_ok=True)
    job.update("Done", 1)
    return {"path": paths.fwd(dest), "size": dest.stat().st_size}


def import_site_zip(job, path: str, name: str = "") -> dict:
    """Extract a site exported by export_site(): project/ -> www/<name>, database.sql -> a new database."""
    cfg = settings.load()
    src = Path(path)
    if not src.is_file():
        raise ValueError(f"File not found: {src}")
    with zipfile.ZipFile(src) as z:
        entries = z.namelist()
        meta = json.loads(z.read("site.json")) if "site.json" in entries else {}
        final_name = normalize_name(name or meta.get("name") or re.split(r"-\d{8}-\d{6}$", src.stem)[0])
        if settings.find_site(cfg, final_name):
            raise ValueError(f"{final_name}.{TLD} already exists")
        dest_root = paths.WWW / final_name
        if dest_root.exists():
            raise ValueError(f"{dest_root} already exists")
        job.update("Extracting", 0)
        names = [n for n in entries if n.startswith("project/") and not n.endswith("/")]
        for i, n in enumerate(names):
            out = (dest_root / Path(n).relative_to("project")).resolve()
            if not out.is_relative_to(dest_root.resolve()):
                raise ValueError(f"Unsafe path in zip: {n}")
            out.parent.mkdir(parents=True, exist_ok=True)
            with z.open(n) as fh, open(out, "wb") as dst:
                shutil.copyfileobj(fh, dst)
            if i % 200 == 0:
                job.update(f"Extracting ({i}/{len(names)})", i / len(names) if names else None)

        db_name = None
        if "database.sql" in entries:
            job.update("Importing database")
            tmp_sql = paths.TMP / f"import-{final_name}-{int(time.time())}.sql"
            try:
                with z.open("database.sql") as fh, open(tmp_sql, "wb") as dst:
                    shutil.copyfileobj(fh, dst)
                db_name = re.sub(r"[^a-z0-9_]", "_", final_name.lower())
                mysql.create_database(cfg, db_name)
                mysql.import_sql(cfg, str(tmp_sql), job, database=db_name)
            finally:
                tmp_sql.unlink(missing_ok=True)

    ver = meta.get("php")
    if not ver or ver not in php.versions():
        ver = cfg.get("default_php") or _default_php(cfg)
    site = create_site(final_name, str(dest_root), ver, meta.get("ssl", True))
    if db_name:
        site = update_site(final_name, {"db": db_name})
    if meta.get("aliases"):
        site = update_site(final_name, {"aliases": meta["aliases"]})
    return site


def set_default_php(ver: str):
    php.php_dir(ver)
    with _lock:
        cfg = settings.load()
        cfg["default_php"] = ver
        settings.save(cfg)
        if not cfg.get("cli_php"):
            cli.write_shims(cfg)


def set_cli_php(ver: str | None):
    if ver:
        php.php_dir(ver)
    with _lock:
        cfg = settings.load()
        cfg["cli_php"] = ver
        settings.save(cfg)
        cli.write_shims(cfg)


def set_ports(http: int, https: int, mysql_port: int):
    with _lock:
        cfg = settings.load()
        running = {k: services.status(cfg, k) == "running" for k in ("apache", "mysql")}
        for k in running:
            if running[k]:
                services.stop(cfg, k)
        cfg["ports"] = {"http": int(http), "https": int(https), "mysql": int(mysql_port)}
        settings.save(cfg)
        mysql.write_my_ini(cfg)
        mysql.write_pma_config(cfg)
        apache.write_all(cfg)
        for k in running:
            if running[k]:
                services.start(cfg, k)


def set_run_mode(mode: str):
    if mode not in ("service", "process"):
        raise ValueError("mode must be service or process")
    with _lock:
        cfg = settings.load()
        if cfg["run_mode"] == mode:
            return
        for k in ("apache", "mysql"):
            services.stop(cfg, k)
        if mode == "service":
            if not is_admin():
                raise PermissionError("Windows services need administrator rights")
            cfg["run_mode"] = mode
            services.install_services()
        else:
            if is_admin():
                services.uninstall_services(cfg)
            cfg["run_mode"] = mode
        settings.save(cfg)


def open_terminal(site_name: str):
    """Open a console in a site's folder with PATH set so plain `php` is that site's PHP version."""
    cfg = settings.load()
    site = settings.find_site(cfg, site_name)
    if not site:
        raise ValueError(f"Site {site_name} not found")
    root = Path(site["root"])
    if not root.is_dir():
        raise ValueError(f"Folder not found: {root}")
    php_dir = php.php_dir(site["php"])
    env = os.environ.copy()
    # The site's own PHP dir goes first so `php` is that version even though bin/cli/php.bat is also on PATH.
    env["PATH"] = f"{php_dir};{paths.CLI};" + env.get("PATH", "")
    env["DEVSTACK_PHP"] = site["php"]
    # Plain cmd, not wt.exe: a running Windows Terminal would open the tab with its own environment, not ours.
    # Windows 11 still shows it in Terminal when that is the default console host.
    spawn_console(["cmd.exe", "/K", "php -v"], cwd=str(root), env=env)


def restart_php_sites():
    """php.ini changes apply once Apache restarts the php-cgi processes."""
    cfg = settings.load()
    if services.status(cfg, "apache") == "running":
        services.restart(cfg, "apache")


def move_php_sites(old: str, new: str) -> list[str]:
    """Point every site (and the default) that uses PHP `old` at `new`."""
    php.php_dir(new)

    def mutate(cfg):
        moved = []
        for s in cfg["sites"]:
            if s["php"] == old:
                s["php"] = new
                moved.append(s["domain"])
        if cfg.get("default_php") == old:
            cfg["default_php"] = new
        return moved

    return _transaction(mutate)


# ---------------------------------------------------------------- server versions

def switch_apache(name: str):
    """Run another installed Apache folder. Tests the config with it first; goes back to the old one on failure."""
    target = paths.APACHE_ROOT / name
    if not (target / "bin" / "httpd.exe").exists():
        raise ValueError(f"{name} is not installed")
    with _lock:
        cfg = settings.load()
        old = paths.apache_dir().name
        if old == name:
            return
        ok, out = apache.test_config(target, cfg)
        if not ok:
            raise RuntimeError(f"{name} can't run the current config:\n{out}")
        was_running = services.status(cfg, "apache") == "running"

        def use(folder):
            if cfg["run_mode"] == "service":
                services.remove_service(cfg, "apache")   # the service points at the old httpd.exe
            else:
                services.stop(cfg, "apache")
            cfg["apache"] = folder
            settings.save(cfg)
            apache.write_all(cfg)
            if cfg["run_mode"] == "service":
                services.install_services()
            if was_running:
                services.start(cfg, "apache")

        try:
            use(name)
        except Exception as e:
            try:
                use(old)
            except Exception:
                pass
            raise RuntimeError(f"Apache {name} did not start, went back to {old}.\n{e}")


def upgrade_mysql(name: str, log=print):
    """Move to a newer MySQL folder. The data folder is copied first; MySQL upgrades it on first start.
    If the new version doesn't start, the copy is put back and the old version runs again."""
    target = paths.MYSQL_ROOT / name
    if not (target / "bin" / "mysqld.exe").exists():
        raise ValueError(f"{name} is not installed")
    with _lock:
        cfg = settings.load()
        old = paths.mysql_dir().name
        if old == name:
            return
        ok, out = mysql.validate_config(target)
        if not ok:
            raise RuntimeError(f"{name} does not accept my.ini:\n{out}")
        was_running = services.status(cfg, "mysql") == "running"
        log("Stopping MySQL")
        if cfg["run_mode"] == "service":
            services.remove_service(cfg, "mysql")
        else:
            services.stop(cfg, "mysql")
        backup = paths.MYSQL_DATA.with_name(f"mysql.bak-{time.strftime('%Y%m%d-%H%M%S')}-{old}")
        log(f"Backing up the data folder to data/{backup.name}")
        shutil.copytree(paths.MYSQL_DATA, backup)

        def use(folder):
            cfg["mysql"] = folder
            settings.save(cfg)
            mysql.write_my_ini(cfg)
            if cfg["run_mode"] == "service":
                services.install_services()

        use(name)
        log(f"Starting {name} and upgrading the databases (can take a few minutes)")
        try:
            services.start(cfg, "mysql", timeout=900)
        except Exception as e:
            log("The new version did not start, restoring the backup")
            try:
                if cfg["run_mode"] == "service":
                    services.remove_service(cfg, "mysql")
                else:
                    services.stop(cfg, "mysql")
            except Exception:
                pass
            shutil.rmtree(paths.MYSQL_DATA, ignore_errors=True)
            shutil.copytree(backup, paths.MYSQL_DATA)
            use(old)
            if was_running:
                services.start(cfg, "mysql")
            raise RuntimeError(f"MySQL {name} did not start, went back to {old}. See logs/mysql_error.log.\n{e}")
        if not was_running:
            services.stop(cfg, "mysql")


# ---------------------------------------------------------------- certificates

def renew_certs(domains: list[str]):
    """Issue fresh certificates, then restart Apache so it loads them."""
    cfg = settings.load()
    with _lock:
        for d in domains:
            site = next((s for s in cfg["sites"] if s["domain"] == d), None)
            if not site:
                raise ValueError(f"{d} is not a site")
            extra = ["localhost", "127.0.0.1", "::1"] if site["name"] == DEFAULT_SITE else []
            ssl.issue(d, extra)
        if services.status(cfg, "apache") == "running":
            services.restart(cfg, "apache")
