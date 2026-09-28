"""Start/stop Apache and MySQL.

Two modes:
  service - registered Windows services (start automatically at boot). Needs admin.
  process - plain background processes owned by the current user. No admin, no auto-start.
"""
import time

from . import apache, mysql, paths
from .winutil import pid_alive, port_in_use, run, spawn

SERVICE_NAMES = {"apache": "devstack-apache", "mysql": "devstack-mysql"}
PID_FILES = {"apache": paths.LOGS / "httpd.pid", "mysql": paths.LOGS / "mysql.pid"}


def _port(cfg, kind):
    return cfg["ports"]["http"] if kind == "apache" else cfg["ports"]["mysql"]


# ---------------------------------------------------------------- Windows services

def service_state(kind: str) -> str:
    r = run(["sc", "query", SERVICE_NAMES[kind]])
    if r.returncode == 1060 or "1060" in r.stdout:
        return "not-installed"
    for line in r.stdout.splitlines():
        if "STATE" in line:
            return {"1": "stopped", "2": "starting", "3": "stopping", "4": "running"}.get(
                line.split(":")[1].split()[0], "unknown")
    return "unknown"


def install_services():
    if service_state("apache") == "not-installed":
        r = run([str(apache.httpd_exe()), "-k", "install", "-n", SERVICE_NAMES["apache"],
                 "-f", str(paths.APACHE_CONF)], cwd=str(paths.apache_dir()))
        if service_state("apache") == "not-installed":
            raise RuntimeError("Could not install Apache service:\n" + r.stdout + r.stderr)
    if service_state("mysql") == "not-installed":
        r = run([str(mysql.mysqld_exe()), "--install", SERVICE_NAMES["mysql"],
                 f"--defaults-file={paths.MY_INI}"])
        if service_state("mysql") == "not-installed":
            raise RuntimeError("Could not install MySQL service:\n" + r.stdout + r.stderr)
    for name in SERVICE_NAMES.values():
        run(["sc", "config", name, "start=", "auto"])


def remove_service(cfg, kind):
    """Stop and delete one service, e.g. before re-installing it for a new Apache/MySQL folder."""
    if service_state(kind) != "not-installed":
        _service_stop(cfg, kind)
        run(["sc", "delete", SERVICE_NAMES[kind]])
        _wait(lambda: service_state(kind) == "not-installed", 15)


def uninstall_services(cfg):
    for kind in ("apache", "mysql"):
        remove_service(cfg, kind)


def _wait(pred, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.4)
    return False


def _service_start(cfg, kind, timeout=40):
    r = run(["sc", "start", SERVICE_NAMES[kind]])
    if not _wait(lambda: service_state(kind) == "running", timeout):
        raise RuntimeError(f"{kind} service did not start. {r.stdout.strip()}\nCheck the {kind} log.")


def _service_stop(cfg, kind):
    if service_state(kind) in ("stopped", "not-installed"):
        return
    run(["sc", "stop", SERVICE_NAMES[kind]])
    if not _wait(lambda: service_state(kind) == "stopped", 60):
        raise RuntimeError(f"{kind} service did not stop")


# ---------------------------------------------------------------- background processes

def _pid(kind):
    try:
        return int(PID_FILES[kind].read_text().strip())
    except (OSError, ValueError):
        return None


def _process_running(kind):
    pid = _pid(kind)
    return bool(pid and pid_alive(pid))


def _process_start(cfg, kind, timeout=40):
    if _process_running(kind):
        return
    PID_FILES[kind].unlink(missing_ok=True)
    if kind == "apache":
        proc = spawn([str(apache.httpd_exe()), "-f", str(paths.APACHE_CONF)], cwd=str(paths.apache_dir()))
    else:
        proc = spawn([str(mysql.mysqld_exe()), f"--defaults-file={paths.MY_INI}"], cwd=str(paths.mysql_dir()))
    # Stop waiting as soon as the process exits, instead of sitting out a long (upgrade) timeout.
    _wait(lambda: (_process_running(kind) and port_in_use(_port(cfg, kind))) or proc.poll() is not None, timeout)
    if not (_process_running(kind) and port_in_use(_port(cfg, kind))):
        raise RuntimeError(f"{kind} did not start. Check the {kind} log.")


def _process_stop(cfg, kind):
    pid = _pid(kind)
    if not pid or not pid_alive(pid):
        return
    # A console-mode httpd has no graceful stop from outside (-k shutdown only talks to services),
    # so Apache is killed with its worker child. MySQL gets a clean mysqladmin shutdown first.
    if kind == "mysql":
        mysql.shutdown(cfg)
        _wait(lambda: not pid_alive(pid), 30)
    if pid_alive(pid):
        r = run(["taskkill", "/F", "/T", "/PID", str(pid)])
        if not _wait(lambda: not pid_alive(pid), 10):
            raise RuntimeError(f"Could not stop {kind} (PID {pid}). If another DevStack window started it "
                               f"as administrator, stop it there.\n{r.stdout.strip()}")
    _wait(lambda: not port_in_use(_port(cfg, kind)), 10)
    PID_FILES[kind].unlink(missing_ok=True)


# ---------------------------------------------------------------- public API

def status(cfg, kind) -> str:
    if cfg["run_mode"] == "service":
        return service_state(kind)
    return "running" if _process_running(kind) else "stopped"


def start(cfg, kind, timeout=40):
    if status(cfg, kind) == "running":
        return
    port = _port(cfg, kind)
    if port_in_use(port):
        from .winutil import port_owner
        raise RuntimeError(f"Port {port} is already used by {port_owner(port) or 'another program'}. "
                           "Stop it or change the port in Settings.")
    if kind == "apache":
        ok, out = apache.test_config()
        if not ok:
            raise RuntimeError("Apache config error:\n" + out)
    if cfg["run_mode"] == "service":
        _service_start(cfg, kind, timeout)
    else:
        _process_start(cfg, kind, timeout)


def stop(cfg, kind):
    if cfg["run_mode"] == "service":
        _service_stop(cfg, kind)
    else:
        _process_stop(cfg, kind)


def restart(cfg, kind):
    stop(cfg, kind)
    start(cfg, kind)
