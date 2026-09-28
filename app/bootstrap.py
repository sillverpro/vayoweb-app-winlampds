"""First-time install: download Apache, PHP, MySQL and phpMyAdmin, then write the config.

    python app/bootstrap.py                            # PHP 8.3 + newest PHP, ports 80/443/3306
    python app/bootstrap.py --php 8.2,8.3,8.4          # pick the PHP branches
    python app/bootstrap.py --ports 8080,8443,3307 --mode process   # next to another local server

Normally started by install.bat. Safe to run again: anything already installed is skipped,
existing sites, settings and databases are kept. More PHP versions (and updates) can be
installed later from the app.
"""
import argparse
import shutil
import socket
import subprocess
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from devstack import core, doctor, paths, php, updates  # noqa: E402


class Job:
    """Console stand-in for jobs.Job: updates.download/extract report progress through .update()."""
    def __init__(self):
        self.last = ""

    def update(self, msg, progress=None):
        line = f"  {msg}" + (f" {progress * 100:3.0f}%" if progress is not None else "")
        print("\r" + line.ljust(len(self.last)), end="", flush=True)
        self.last = line

    def done(self):
        if self.last:
            print()
        self.last = ""


def step(title):
    print(f"\n== {title}")


def vc_runtime():
    if doctor._vcredist_present():
        return
    step("Microsoft Visual C++ runtime (PHP, Apache and MySQL need it)")
    job = Job()
    exe = updates.download(updates.VC_REDIST, job, "VC++ runtime")
    job.done()
    print("  Installing - accept the Windows prompt")
    subprocess.run([str(exe), "/install", "/passive", "/norestart"])


def install_apache():
    if paths.installed_dirs(paths.APACHE_ROOT):
        print("  already installed")
        return
    r = updates._apache_remote()
    if not r.get("fcgid_url"):
        raise SystemExit("mod_fcgid download not found on apachelounge.com, try again later")
    job = Job()
    target = paths.APACHE_ROOT / f"apache{r['version']}"
    z = updates.download(r["url"], job, f"Apache {r['version']}")
    updates.extract(z, target, job, strip="Apache24/")
    z.unlink(missing_ok=True)
    fz = updates.download(r["fcgid_url"], job, "mod_fcgid")
    with zipfile.ZipFile(fz) as zf:
        name = next(n for n in zf.namelist() if n.endswith("mod_fcgid.so"))
        (target / "modules" / "mod_fcgid.so").write_bytes(zf.read(name))
    fz.unlink(missing_ok=True)
    job.done()
    print(f"  Apache {r['version']}")


def install_php(wanted: list[str]):
    """wanted: branches like "8.3", or "latest" for the newest stable branch."""
    stable = [r for r in updates._php_remote() if not r["pre"]]
    branches = []
    for w in wanted:
        br = stable[0]["branch"] if w == "latest" else w
        if br not in branches:
            branches.append(br)
    have = php.versions()
    for br in branches:
        entry = next((r for r in stable if r["branch"] == br), None)
        if not entry:
            print(f"  PHP {br}: no Windows build found, skipped")
            continue
        if any(v.startswith(br + ".") for v in have):
            print(f"  PHP {br}: already installed")
            continue
        v = entry["version"]
        job = Job()
        target = paths.PHP_ROOT / f"php{v}"
        z = updates.download(entry["url"], job, f"PHP {v}", entry.get("sha256"))
        updates.extract(z, target, job)
        z.unlink(missing_ok=True)
        job.done()
        if not (target / "php-cgi.exe").exists():
            raise SystemExit(f"PHP {v}: php-cgi.exe missing from the download")
        print(f"  PHP {v}")


def install_mysql():
    if paths.installed_dirs(paths.MYSQL_ROOT):
        print("  already installed")
        return
    rows = updates._mysql_remote()
    if not rows:
        raise SystemExit("No MySQL download found, try again later")
    r = next((x for x in rows if x["lts"]), rows[0])      # newest long-term-support series
    v = r["version"]
    job = Job()
    z = updates.download(r["url"], job, f"MySQL {v}")
    updates.extract(z, paths.MYSQL_ROOT / f"mysql{v}", job, strip=f"mysql-{v}-winx64/",
                    skip=(".pdb", "/mysql-test/", "/lib/debug/"))
    z.unlink(missing_ok=True)
    job.done()
    print(f"  MySQL {v}")


def install_pma():
    if paths.PMA.is_dir():
        print("  already installed")
        return
    v = updates._pma_remote()["version"]
    url = updates.PMA_ZIP.format(v=v)
    sha = updates.fetch(url + ".sha256").decode("ascii", "replace").split()[0]
    job = Job()
    z = updates.download(url, job, f"phpMyAdmin {v}", sha)
    updates.extract(z, paths.PMA, job, strip=f"phpMyAdmin-{v}-all-languages/")
    z.unlink(missing_ok=True)
    job.done()
    print(f"  phpMyAdmin {v}")


def ca_bundle():
    """cacert.pem for PHP's curl/openssl (curl.cainfo), taken from certifi."""
    if paths.CACERT_BUNDLE.exists():
        return
    import certifi
    paths.CACERT_BUNDLE.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(certifi.where(), paths.CACERT_BUNDLE)


def busy_ports(ports: dict) -> list[int]:
    busy = []
    for p in ports.values():
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", p)) == 0:
                busy.append(p)
    return busy


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--php", default="8.3,latest", help='PHP branches, e.g. "8.2,8.3,latest" (default: 8.3,latest)')
    ap.add_argument("--ports", help="http,https,mysql e.g. 8080,8443,3307")
    ap.add_argument("--mode", choices=["service", "process"])
    ap.add_argument("--skip-download", action="store_true", help="only write the config (binaries already in bin/)")
    a = ap.parse_args()

    if sys.platform != "win32":
        raise SystemExit("DevStack runs on Windows only.")
    paths.ensure_dirs()
    if not a.skip_download:
        vc_runtime()
        step("Apache")
        install_apache()
        step("PHP")
        install_php([x.strip() for x in a.php.split(",") if x.strip()])
        step("MySQL")
        install_mysql()
        step("phpMyAdmin")
        install_pma()
    ca_bundle()

    ports = None
    if a.ports:
        h, s, m = (int(x) for x in a.ports.split(","))
        ports = {"http": h, "https": s, "mysql": m}
    step("Setup")
    cfg = core.initialize(ports=ports, run_mode=a.mode, log=lambda m: print("  " + m))
    busy = busy_ports(cfg["ports"])
    print("\nDone. Start DevStack with DevStack.bat (it asks for administrator rights), then press Finish setup.")
    if busy:
        print(f"Note: port(s) {', '.join(map(str, busy))} are already used by another program. Stop it, or pick other "
              f"ports in DevStack > Settings (or run again with --ports 8080,8443,3307).")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit("\nCancelled.")
