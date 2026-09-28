"""Methods exposed to the UI as window.pywebview.api.*. Every call returns {ok, data} or {ok: False, error}."""
import functools
import os
import time
import traceback
import webbrowser
from pathlib import Path

from . import cli, core, doctor, hosts, jobs, mailcatch, mysql, paths, php, services, settings, ssl, stats, updates
from .version import AUTHOR, COMPONENTS, COPYRIGHT, GITHUB, changelog as read_changelog, current as app_version
from .winutil import font_families, is_admin


def _endpoint(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return {"ok": True, "data": fn(*args, **kwargs)}
        except Exception as e:  # surfaced to the UI as a toast
            traceback.print_exc()
            return {"ok": False, "error": str(e) or e.__class__.__name__}
    return wrapper


def _folder_created(site: dict) -> float:
    """Sites made before DevStack stored a date: fall back to the project folder's creation time."""
    try:
        return stats.project_folder(site).stat().st_ctime
    except OSError:
        return 0


class Api:
    def __init__(self):
        self._window = None   # underscore: pywebview must not crawl the native window tree (slow start)
        self._tray = None     # set by main.py when the tray icon runs
        stats.start_sampler()
        mysql.start_backup_thread()
        cfg = settings.load()
        if cfg.get("mail_catcher"):
            try:
                mailcatch.start(port=cfg.get("mail_port", 1025))
            except OSError:
                pass   # port busy - Settings will show it as not running; the user can pick another port

    # ---------------------------------------------------------------- state

    @_endpoint
    def state(self):
        setup = core.setup_state()
        if not setup["binaries"] or not setup["initialized"]:
            return {"setup": setup, "version": app_version()}
        synced = core.reconcile()
        if synced:
            setup = core.setup_state()
        cfg = settings.load()
        sites = [{**s, "urls": settings.site_urls(cfg, s), "created": s.get("created") or _folder_created(s)}
                 for s in cfg["sites"]]
        return {
            "version": app_version(),
            "synced": synced,
            "stamp": paths.SETTINGS_FILE.stat().st_mtime,
            "setup": setup,
            "ports": cfg["ports"],
            "run_mode": cfg["run_mode"],
            "mysql_password": bool(cfg.get("mysql_root_password")),
            "default_php": cfg["default_php"],
            "close_to_tray": cfg["close_to_tray"],
            "tray": self._tray is not None,
            "services": {k: services.status(cfg, k) for k in ("apache", "mysql")},
            "sites": sites,
            "php_versions": php.versions(),
            "versions": {"apache": updates.apache_version(), "mysql": updates.mysql_version()},
            "updates": updates.status(),
            "root": paths.fwd(paths.ROOT),
            "www": paths.fwd(paths.WWW),
            "pma_url": settings.site_urls(cfg, cfg["sites"][0]).get("https", "") + "phpmyadmin/"
            if cfg["sites"] else "",
            "mail_count": len(list(paths.MAIL_DIR.glob("*.eml"))) if paths.MAIL_DIR.is_dir() else 0,
        }

    @_endpoint
    def status(self):
        """Polled every few seconds. `synced` lists fixes reconcile() made, so the UI can reload state."""
        synced = core.reconcile()
        cfg = settings.load()

        def log_mtime(domain):
            f = paths.SITE_LOGS / f"{domain}-php.log"
            return f.stat().st_mtime if f.exists() else 0

        mail_files = list(paths.MAIL_DIR.glob("*.eml")) if paths.MAIL_DIR.is_dir() else []
        return {"services": {k: services.status(cfg, k) for k in ("apache", "mysql")}, "synced": synced,
                "stamp": paths.SETTINGS_FILE.stat().st_mtime if paths.SETTINGS_FILE.exists() else 0,
                "php_log_mtimes": {s["domain"]: log_mtime(s["domain"]) for s in cfg["sites"]},
                "mail_count": len(mail_files)}

    # ---------------------------------------------------------------- services

    @_endpoint
    def service(self, kind, action):
        if kind not in ("apache", "mysql") or action not in ("start", "stop", "restart"):
            raise ValueError("bad service request")
        cfg = settings.load()
        getattr(services, action)(cfg, kind)
        return services.status(cfg, kind)

    @_endpoint
    def all_services(self, action):
        cfg = settings.load()
        order = ("mysql", "apache") if action == "start" else ("apache", "mysql")
        errors = []
        for k in order:
            try:
                getattr(services, action)(cfg, k)
            except Exception as e:
                errors.append(str(e))
        if errors:
            raise RuntimeError("\n".join(errors))

    @_endpoint
    def restart_all(self):
        cfg = settings.load()
        for k in ("mysql", "apache"):
            if services.status(cfg, k) == "running":
                services.restart(cfg, k)
            else:
                services.start(cfg, k)

    # ---------------------------------------------------------------- sites

    @_endpoint
    def create_site(self, name, root="", php_version="", use_ssl=True, create_db=False, db=None):
        return core.create_site(name, root, php_version, use_ssl, create_db, db)

    @_endpoint
    def scan_folder(self, folder=""):
        return core.scan_folder(folder)

    @_endpoint
    def import_sites(self, items, php_version="", use_ssl=True):
        return core.import_sites(items, php_version, use_ssl)

    @_endpoint
    def update_site(self, name, changes):
        return core.update_site(name, changes)

    @_endpoint
    def delete_site(self, name, delete_files=False):
        core.delete_site(name, delete_files)

    # ---------------------------------------------------------------- LAN sharing (feature O)

    @_endpoint
    def set_site_lan(self, name, on):
        cfg = settings.load()
        old_port = (settings.find_site(cfg, name) or {}).get("lan_port")
        site = core.update_site(name, {"lan": bool(on)})
        if not on and old_port:
            try:
                core.remove_lan_firewall(old_port)
            except Exception:
                pass   # not admin, or the rule was never added - the port just won't be reachable from the LAN
        return site

    @_endpoint
    def lan_info(self):
        return {"ip": core.lan_ip()}

    @_endpoint
    def allow_lan_firewall(self, port):
        core.allow_lan_firewall(int(port))

    @_endpoint
    def remove_lan_firewall(self, port):
        core.remove_lan_firewall(int(port))

    @_endpoint
    def clone_site(self, name, new_name):
        return jobs.start(f"Clone {name}.{settings.TLD}", core.clone_site, name, new_name)

    @_endpoint
    def export_site(self, name, include_git=False):
        return jobs.start(f"Export {name}.{settings.TLD}", core.export_site, name, include_git)

    @_endpoint
    def import_site_zip(self, name=""):
        """Pick a .zip file, then extract/import it in the background. None if the dialog is cancelled."""
        import webview
        res = self._window.create_file_dialog(webview.FileDialog.OPEN, file_types=("Zip files (*.zip)", "All files (*.*)"))
        if not res:
            return None
        path = res if isinstance(res, str) else res[0]
        return jobs.start(f"Import {Path(path).name}", core.import_site_zip, path, name)

    # ---------------------------------------------------------------- php

    @_endpoint
    def php_config(self, ver):
        cfg = settings.load()
        data = php.get_config(ver)
        data["sites"] = [s["domain"] for s in cfg["sites"] if s["php"] == ver]
        return data

    @_endpoint
    def php_update(self, ver, values, extensions):
        php.update_config(ver, values, extensions)
        core.restart_php_sites()
        return php.get_config(ver)

    @_endpoint
    def php_timezones(self, ver):
        return php.timezones(ver)

    @_endpoint
    def xdebug_info(self, ver):
        build = php.build_info(ver)
        installed = php.enabled_extensions(php.read_ini(ver))
        dll = php.xdebug_dll(ver)
        try:
            match = updates.xdebug_match(ver, build) if build["compiler"] else None
        except OSError:   # offline: the install button then reports the error itself
            match = True
        return {"build": build, "downloaded": bool(dll), "enabled": "xdebug" in installed, "available": bool(match)}

    @_endpoint
    def install_xdebug(self, ver):
        return jobs.start(f"Install Xdebug for PHP {ver}", updates.install_xdebug, ver)

    @_endpoint
    def set_default_php(self, ver):
        core.set_default_php(ver)

    # ---------------------------------------------------------------- PHP CLI / composer

    @_endpoint
    def cli_status(self):
        cfg = settings.load()
        return {
            "cli_php": cfg.get("cli_php"),
            "default_php": cfg.get("default_php"),
            "on_path": cli.on_path(),
            "path_entry": cli.PATH_ENTRY,
            "composer_version": updates.composer_version(),
        }

    @_endpoint
    def set_cli_php(self, ver):
        core.set_cli_php(ver or None)

    @_endpoint
    def add_cli_to_path(self):
        cli.add_to_path()
        return cli.on_path()

    @_endpoint
    def remove_cli_from_path(self):
        cli.remove_from_path()
        return cli.on_path()

    @_endpoint
    def install_composer(self):
        return jobs.start("Install Composer", updates.install_composer)

    @_endpoint
    def open_terminal(self, site_name):
        core.open_terminal(site_name)

    # ---------------------------------------------------------------- settings / setup

    @_endpoint
    def set_ports(self, http, https, mysql_port):
        core.set_ports(http, https, mysql_port)

    @_endpoint
    def set_run_mode(self, mode):
        core.set_run_mode(mode)

    @_endpoint
    def changelog(self):
        return read_changelog()

    @_endpoint
    def about(self):
        versions = {
            "Apache": [updates.apache_version()] if updates.apache_version() else [],
            "PHP": php.versions(),
            "MySQL": [updates.mysql_version()] if updates.mysql_version() else [],
            "phpMyAdmin": [updates.pma_version()] if updates.pma_version() else [],
            "OpenSSL": [updates.openssl_version()] if updates.openssl_version() else [],
            "Xdebug": updates.xdebug_versions(),
            "Composer": [updates.composer_version()] if updates.composer_version() else [],
            "qrcode-generator (Kazuhiko Arase)": ["vendored"] if (paths.UI / "vendor" / "qrcode.js").exists() else [],
        }
        return {
            "version": app_version(),
            "copyright": COPYRIGHT,
            "author": AUTHOR,
            "github": GITHUB,
            "license": (paths.ROOT / "LICENSE").read_text(encoding="utf-8") if (paths.ROOT / "LICENSE").exists() else "",
            "year": time.strftime("%Y"),
            "components": [{**c, "installed": versions.get(c["name"], [])} for c in COMPONENTS],
        }

    @_endpoint
    def fonts(self):
        return font_families()

    @_endpoint
    def set_close_to_tray(self, on):
        cfg = settings.load()
        cfg["close_to_tray"] = bool(on)
        settings.save(cfg)

    @_endpoint
    def finish_setup(self):
        core.finish_admin_setup()
        return core.setup_state()

    @_endpoint
    def sync_hosts(self):
        if not is_admin():
            raise PermissionError("Run DevStack as administrator to edit the hosts file.")
        cfg = settings.load()
        hosts.sync([s["domain"] for s in cfg["sites"]], core._site_aliases(cfg))

    @_endpoint
    def trust_ca(self):
        ssl.trust_ca(machine=is_admin())
        return ssl.is_ca_trusted()

    @_endpoint
    def import_mysql(self, src):
        cfg = settings.load()
        if services.status(cfg, "mysql") == "running":
            services.stop(cfg, "mysql")
        from .winutil import port_in_use
        if port_in_use(cfg["ports"]["mysql"]):
            raise RuntimeError("Another MySQL is using the port. Stop the other server's MySQL first, "
                               "its data must not be copied while it runs.")
        mysql.import_datadir(src)
        services.start(cfg, "mysql")

    # ---------------------------------------------------------------- versions and updates

    @_endpoint
    def check_updates(self):
        return updates.check()

    @_endpoint
    def updates_status(self):
        return updates.status()

    @_endpoint
    def jobs(self):
        return jobs.listing()

    @_endpoint
    def install_php(self, version):
        return jobs.start(f"Install PHP {version}", updates.install_php, version)

    @_endpoint
    def update_php(self, old, version):
        return jobs.start(f"Update PHP {old} to {version}", updates.update_php, old, version)

    @_endpoint
    def remove_php(self, ver):
        updates.remove_php(ver)

    @_endpoint
    def update_apache(self):
        return jobs.start("Update Apache", updates.install_apache)

    @_endpoint
    def use_apache(self, name):
        return jobs.start(f"Switch to {name}", lambda job: core.switch_apache(name))

    @_endpoint
    def update_mysql(self, version):
        return jobs.start(f"Update MySQL to {version}", updates.install_mysql, version)

    @_endpoint
    def update_pma(self):
        return jobs.start("Update phpMyAdmin", updates.install_pma)

    @_endpoint
    def remove_server(self, kind, name):
        updates.remove_server(kind, name)

    # ---------------------------------------------------------------- dashboard numbers

    @_endpoint
    def stats(self, refresh_sizes=False):
        cfg = settings.load()
        dbs = mysql.databases()
        return {
            "sites": len(cfg["sites"]),
            "https_sites": sum(1 for s in cfg["sites"] if s.get("ssl")),
            "databases": len(dbs),
            "db_size": sum(d["size"] for d in dbs),
            "db_sizes": {d["name"]: d["size"] for d in dbs},
            "site_dbs": stats.detect_site_dbs(cfg, dbs),
            "sizes": stats.sizes(refresh_sizes),
            "disk": stats.disk(),
        }

    @_endpoint
    def site_icons(self):
        """{site name: favicon data URI or None} for the dashboard site cards."""
        return {s["name"]: stats.site_icon(s) for s in settings.load()["sites"]}

    @_endpoint
    def activity(self, fine_since=0, coarse_since=0):
        """Polled every second on the dashboard: live numbers and new history rows."""
        return stats.activity(fine_since, coarse_since)

    # ---------------------------------------------------------------- databases

    @_endpoint
    def databases(self):
        cfg = settings.load()
        dbs = mysql.databases()
        used = stats.detect_site_dbs(cfg, dbs)
        last_backup = mysql.last_backups()
        db_users = {}
        if services.status(cfg, "mysql") == "running":
            try:
                db_users = mysql.db_users(cfg)
            except Exception:
                pass   # MySQL running but not reachable for some reason - the rest of the page still works
        for d in dbs:
            d["sites"] = [s["domain"] for s in cfg["sites"] if d["name"] in used.get(s["name"], [])]
            d["last_backup"] = last_backup.get(d["name"])
            d["users"] = db_users.get(d["name"], [])
        paths.DB_EXPORTS.mkdir(parents=True, exist_ok=True)   # the page links to it
        return {"databases": dbs, "backups": mysql.backups(), "exports": mysql.exports(),
                "exports_dir": paths.fwd(paths.DB_EXPORTS), "backup_settings": cfg.get("backup")}

    @_endpoint
    def set_backup_settings(self, enabled, dbs, keep):
        cfg = settings.load()
        cfg["backup"] = {"enabled": bool(enabled), "dbs": list(dbs or []), "keep": max(1, int(keep or 7))}
        settings.save(cfg)

    def _mysql_running(self, cfg):
        if services.status(cfg, "mysql") != "running":
            raise RuntimeError("Start MySQL first")

    # ---------------------------------------------------------------- MySQL users

    @_endpoint
    def users(self):
        cfg = settings.load()
        self._mysql_running(cfg)
        return mysql.users(cfg)

    @_endpoint
    def set_user_password(self, user, host, password):
        cfg = settings.load()
        self._mysql_running(cfg)
        mysql.set_user_password(cfg, user, host, password)
        if user == "root":
            cfg["mysql_root_password"] = password
            settings.save(cfg)

    @_endpoint
    def drop_user(self, user, host):
        cfg = settings.load()
        self._mysql_running(cfg)
        mysql.drop_user(cfg, user, host)

    @_endpoint
    def export_db(self, name):
        """Ask where to save, then mysqldump in the background. Returns None when the dialog is cancelled."""
        import webview
        cfg = settings.load()
        self._mysql_running(cfg)
        res = self._window.create_file_dialog(webview.FileDialog.SAVE, save_filename=f"{name}.sql",
                                              file_types=("SQL files (*.sql)", "All files (*.*)"))
        if not res:
            return None
        dest = res if isinstance(res, str) else res[0]
        return jobs.start(f"Export {name}", lambda job: mysql.export_db(cfg, name, dest, job))

    @_endpoint
    def backup_db(self, name):
        cfg = settings.load()
        self._mysql_running(cfg)
        return jobs.start(f"Back up {name}", lambda job: mysql.export_db(cfg, name, mysql.backup_path(name), job))

    @_endpoint
    def import_sql(self, database="", create_db=False):
        """Pick a .sql/.sql.gz file, then stream it into MySQL in the background. None if the dialog is cancelled."""
        import webview
        cfg = settings.load()
        self._mysql_running(cfg)
        res = self._window.create_file_dialog(webview.FileDialog.OPEN,
                                              file_types=("SQL files (*.sql;*.sql.gz)", "All files (*.*)"))
        if not res:
            return None
        path = res if isinstance(res, str) else res[0]
        return jobs.start(f"Import {Path(path).name}", lambda job: mysql.import_sql(cfg, path, job, database or None, create_db))

    @_endpoint
    def delete_export(self, name):
        f = paths.DB_EXPORTS / name
        if f.parent != paths.DB_EXPORTS or f.suffix.lower() != ".sql" or not f.is_file():
            raise ValueError("not an export file")
        f.unlink()

    @_endpoint
    def delete_db_backup(self, name):
        mysql.delete_backup(name)

    @_endpoint
    def create_database(self, name, user=""):
        cfg = settings.load()
        self._mysql_running(cfg)
        return mysql.create_database(cfg, name, user or None)

    # ---------------------------------------------------------------- certificates

    @_endpoint
    def certs(self):
        cfg = settings.load()
        data = ssl.list_certs([s["domain"] for s in cfg["sites"] if s.get("ssl")])
        data["ca"] = ssl.ca_info()
        data["sites_all"] = [{"name": s["name"], "domain": s["domain"], "ssl": bool(s.get("ssl"))} for s in cfg["sites"]]
        return data

    @_endpoint
    def renew_certs(self, domains):
        core.renew_certs(domains)

    @_endpoint
    def delete_cert(self, domain):
        cfg = settings.load()
        if any(s["domain"] == domain and s.get("ssl") for s in cfg["sites"]):
            raise ValueError(f"{domain} still uses HTTPS")
        ssl.remove_site_cert(domain)

    # ---------------------------------------------------------------- logs

    @_endpoint
    def logs(self):
        files = sorted(paths.LOGS.glob("*.log")) + sorted(paths.SITE_LOGS.glob("*.log"))
        return [paths.fwd(f.relative_to(paths.LOGS)) for f in files]

    @_endpoint
    def read_log(self, rel, max_bytes=60000):
        f = (paths.LOGS / rel).resolve()
        if paths.LOGS.resolve() not in f.parents:
            raise ValueError("not a log file")
        if not f.exists():
            return ""
        with open(f, "rb") as fh:
            fh.seek(max(0, f.stat().st_size - max_bytes))
            return fh.read().decode("utf-8", errors="replace")

    @_endpoint
    def clear_all_logs(self):
        """Delete every log. Logs the servers still write to are emptied instead (deleting them under a
        running Apache would lose what it writes next)."""
        cfg = settings.load()
        live = {"apache_error.log", "apache_access.log", "mysql_error.log",
                *(f"php{v}_error.log" for v in php.versions()),
                *(f"sites/{s['domain']}-error.log" for s in cfg["sites"]),
                *(f"sites/{s['domain']}-php.log" for s in cfg["sites"])}
        deleted = emptied = 0
        for f in list(paths.LOGS.glob("*.log")) + list(paths.SITE_LOGS.glob("*.log")):
            rel = paths.fwd(f.relative_to(paths.LOGS))
            try:
                if rel in live:
                    f.write_bytes(b"")
                    emptied += 1
                else:
                    f.unlink()
                    deleted += 1
            except OSError:
                pass
        return {"deleted": deleted, "emptied": emptied}

    @_endpoint
    def clear_log(self, rel):
        f = (paths.LOGS / rel).resolve()
        if paths.LOGS.resolve() in f.parents and f.exists():
            f.write_bytes(b"")

    # ---------------------------------------------------------------- desktop helpers

    @_endpoint
    def pick_folder(self, start=""):
        import webview
        res = self._window.create_file_dialog(webview.FileDialog.FOLDER, directory=start or str(paths.WWW))
        return paths.fwd(res[0]) if res else ""

    @_endpoint
    def open_path(self, p):
        os.startfile(os.path.normpath(p))

    @_endpoint
    def open_url(self, url):
        webbrowser.open(url)

    @_endpoint
    def open_ini(self, ver):
        os.startfile(str(php.ini_path(ver)))

    # ---------------------------------------------------------------- doctor

    @_endpoint
    def doctor(self):
        return doctor.run_checks()

    # ---------------------------------------------------------------- mail catcher (feature P)

    @_endpoint
    def mail_status(self):
        cfg = settings.load()
        return {"enabled": bool(cfg.get("mail_catcher")), "port": cfg.get("mail_port", 1025), "running": mailcatch.running()}

    @_endpoint
    def set_mail_settings(self, enabled, port):
        cfg = settings.load()
        cfg["mail_catcher"] = bool(enabled)
        cfg["mail_port"] = int(port) or 1025
        settings.save(cfg)
        if cfg["mail_catcher"]:
            mailcatch.start(port=cfg["mail_port"])
            changed = False
            for v in php.versions():
                try:
                    changed |= php.set_mail_catcher(v, True, cfg["mail_port"])
                except OSError:
                    pass
            if changed:
                core.restart_php_sites()   # php-cgi reads php.ini only when Apache starts it
        else:
            mailcatch.stop()
        return {"enabled": cfg["mail_catcher"], "port": cfg["mail_port"], "running": mailcatch.running()}

    @_endpoint
    def mail_list(self):
        return mailcatch.list_messages()

    @_endpoint
    def mail_read(self, mid):
        return mailcatch.read_message(mid)

    @_endpoint
    def mail_delete(self, mid):
        mailcatch.delete_message(mid)

    @_endpoint
    def mail_clear(self):
        return mailcatch.clear_all()

    @_endpoint
    def save_attachment(self, mid, index):
        import webview
        name, data = mailcatch.read_attachment(mid, int(index))
        res = self._window.create_file_dialog(webview.FileDialog.SAVE, save_filename=name)
        if not res:
            return None
        dest = res if isinstance(res, str) else res[0]
        Path(dest).write_bytes(data)
        return dest
