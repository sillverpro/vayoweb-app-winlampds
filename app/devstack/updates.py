"""Check for and install PHP, Apache, MySQL and phpMyAdmin versions.

Sources: windows.php.net (PHP), apachelounge.com (Apache + mod_fcgid), GitHub tags + cdn.mysql.com (MySQL),
phpmyadmin.net (phpMyAdmin, replaced in place: apps/phpmyadmin).
Every version goes into its own folder next to the others (bin/php/php8.3.35, bin/apache/apache2.4.68, ...),
so an old version stays usable until it is removed.
"""
import hashlib
import json
import re
import shutil
import ssl
import time
import urllib.request
import zipfile
from pathlib import Path

from . import core, mysql, paths, php, settings
from .winutil import run

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) DevStack"
PHP_REL = "https://windows.php.net/downloads/releases/"
PHP_QA = "https://windows.php.net/downloads/qa/"
PHP_OLDEST = (5, 6)
APACHE_PAGE = "https://www.apachelounge.com/download/"
MYSQL_TAGS = "https://api.github.com/repos/mysql/mysql-server/git/matching-refs/tags/mysql-"
MYSQL_CDN = ("https://cdn.mysql.com/Downloads/MySQL-{series}/mysql-{v}-winx64.zip",
             "https://cdn.mysql.com/archives/mysql-{series}/mysql-{v}-winx64.zip")
MYSQL_LTS = {"8.0", "8.4", "9.7"}     # Oracle's long-term support series; the others are Innovation releases
PMA_FEED = "https://www.phpmyadmin.net/home_page/version.json"
PMA_ZIP = "https://files.phpmyadmin.net/phpMyAdmin/{v}/phpMyAdmin-{v}-all-languages.zip"
CACHE = paths.TMP / "updates.json"
VC_REDIST = "https://aka.ms/vs/17/release/vc_redist.x64.exe"

vkey = paths.version_key


# ---------------------------------------------------------------- network

def _ctx():
    # Python's own store can hold stale roots on Windows; certifi's bundle is current.
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _open(url, method="GET", timeout=30):
    req = urllib.request.Request(url, method=method, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=timeout, context=_ctx())


def fetch(url) -> bytes:
    with _open(url) as r:
        return r.read()


def exists(url) -> bool:
    try:
        with _open(url, "HEAD", timeout=15) as r:
            return r.status == 200
    except Exception:
        return False


def download(url, job, label, sha256=None) -> Path:
    """Download into tmp/downloads with progress. Returns the file path."""
    paths.DOWNLOADS.mkdir(parents=True, exist_ok=True)
    dest = paths.DOWNLOADS / url.rsplit("/", 1)[1]
    part = dest.with_name(dest.name + ".part")
    with _open(url, timeout=60) as r:
        total = int(r.headers.get("Content-Length") or 0)
        got, last = 0, 0.0
        with open(part, "wb") as fh:
            while chunk := r.read(1 << 17):
                fh.write(chunk)
                got += len(chunk)
                if time.time() - last > 0.3:
                    last = time.time()
                    size = f"{got / 1e6:.0f} / {total / 1e6:.0f} MB" if total else f"{got / 1e6:.0f} MB"
                    job.update(f"Downloading {label} ({size})", got / total if total else None)
    if total and got != total:
        part.unlink(missing_ok=True)
        raise RuntimeError(f"Download of {label} was cut off, try again")
    if sha256:
        h = hashlib.sha256()
        with open(part, "rb") as fh:
            while chunk := fh.read(1 << 20):
                h.update(chunk)
        if h.hexdigest().lower() != sha256.lower():
            part.unlink(missing_ok=True)
            raise RuntimeError(f"Checksum of {label} does not match, the download is damaged")
    part.replace(dest)
    return dest


def extract(zip_path: Path, target: Path, job, strip="", skip=()):
    """Unzip into target via a hidden ".name" folder, so a half-extracted version never shows up as installed.
    strip: a top folder inside the zip to drop (e.g. "Apache24/"). skip: path fragments to leave out."""
    tmp = target.with_name("." + target.name)
    shutil.rmtree(tmp, ignore_errors=True)
    with zipfile.ZipFile(zip_path) as z:
        names = [n for n in z.namelist() if n.startswith(strip) and not n.endswith("/")
                 and not any(s in n for s in skip)]
        for i, n in enumerate(names):
            out = tmp / n[len(strip):]
            out.parent.mkdir(parents=True, exist_ok=True)
            with z.open(n) as src, open(out, "wb") as dst:
                shutil.copyfileobj(src, dst)
            if i % 50 == 0:
                job.update(f"Extracting {target.name}", i / len(names))
    if target.exists():
        shutil.rmtree(tmp, ignore_errors=True)
        raise RuntimeError(f"{target} already exists")
    tmp.rename(target)


# ---------------------------------------------------------------- remote catalogs

def _php_remote() -> list[dict]:
    """Newest release of every PHP branch from 5.6 on, plus pre-releases newer than the branch's stable one."""
    branches = {}
    listing = fetch(PHP_REL + "archives/").decode("utf-8", "replace")
    for fname, ver in re.findall(r"(php-(\d+\.\d+\.\d+)-Win32-v[cs]\d+-x64\.zip)", listing, re.I):
        br = ".".join(ver.split(".")[:2])
        if vkey(br)[:2] >= PHP_OLDEST and (br not in branches or vkey(ver) > vkey(branches[br]["version"])):
            branches[br] = {"branch": br, "version": ver, "url": PHP_REL + "archives/" + fname, "sha256": None}

    def ts_build(entry):
        # Thread-safe x64 build (the flavour Apache + mod_fcgid setups commonly use, and xdebug.org ships for).
        return next((v for k, v in entry.items() if k.startswith("ts-") and k.endswith("-x64")), None)

    for br, e in json.loads(fetch(PHP_REL + "releases.json")).items():
        b = ts_build(e)
        if b and (br not in branches or vkey(e["version"]) >= vkey(branches[br]["version"])):
            branches[br] = {"branch": br, "version": e["version"], "url": PHP_REL + b["zip"]["path"],
                            "sha256": b["zip"].get("sha256")}
    out = [dict(x, pre=False) for x in branches.values()]
    for br, e in json.loads(fetch(PHP_QA + "releases.json")).items():
        b = ts_build(e)
        stable = branches.get(br)
        if b and (not stable or vkey(e["version"]) > vkey(stable["version"])):
            out.append({"branch": br, "version": e["version"], "url": PHP_QA + b["zip"]["path"],
                        "sha256": b["zip"].get("sha256"), "pre": True})
    return sorted(out, key=lambda x: vkey(x["version"]), reverse=True)


def _apache_remote() -> dict:
    page = fetch(APACHE_PAGE).decode("utf-8", "replace")
    m = re.search(r'href="([^"]*/binaries/httpd-(2\.4\.\d+)-\d+-Win64-VS\d+\.zip)"', page, re.I)
    if not m:
        raise RuntimeError("No Win64 build found on apachelounge.com")
    fcgid = re.search(r'href="([^"]*/modules/mod_fcgid-[\d.]+-win64-VS\d+\.zip)"', page, re.I)
    base = "https://www.apachelounge.com"
    return {"version": m.group(2), "url": base + m.group(1), "fcgid_url": base + fcgid.group(1) if fcgid else None}


def _mysql_remote() -> list[dict]:
    """Newest release of each MySQL series from 8.4 on that has a Windows zip."""
    tags = []
    for prefix in ("8.4", "9", "1", "2", "3"):
        try:
            refs = json.loads(fetch(MYSQL_TAGS + prefix))
        except Exception:
            continue
        tags += [m.group(1) for r in refs if (m := re.fullmatch(r"refs/tags/mysql-(\d+\.\d+\.\d+)", r["ref"]))]
    newest = {}
    for v in tags:
        series = ".".join(v.split(".")[:2])
        if series not in newest or vkey(v) > vkey(newest[series]):
            newest[series] = v
    out = []
    for series, v in sorted(newest.items(), key=lambda x: vkey(x[1]), reverse=True)[:6]:
        url = next((u for t in MYSQL_CDN if exists(u := t.format(series=series, v=v))), None)
        if url:
            out.append({"series": series, "version": v, "url": url, "lts": series in MYSQL_LTS})
    return out


def _pma_remote() -> dict:
    feed = json.loads(fetch(PMA_FEED))
    rel = next((r for r in feed.get("releases", []) if r["version"] == feed["version"]), {})
    return {"version": feed["version"], "date": feed.get("date"), "php_versions": rel.get("php_versions", "")}


KINDS = ("php", "apache", "mysql", "pma")


def check() -> dict:
    """Ask every source for its newest versions and cache the answer."""
    data = {"checked": time.time(), "errors": {}}
    for kind, fn in (("php", _php_remote), ("apache", _apache_remote), ("mysql", _mysql_remote), ("pma", _pma_remote)):
        try:
            data[kind] = fn()
        except Exception as e:
            data[kind] = None
            data["errors"][kind] = f"{e.__class__.__name__}: {e}"
    old = _cached()
    for kind in KINDS:     # keep the last good answer if a source is down
        if data[kind] is None and old.get(kind):
            data[kind] = old[kind]
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(data), encoding="utf-8")
    return status()


def _cached() -> dict:
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


# ---------------------------------------------------------------- installed versions

_ver_cache = {}


def _binary_version(exe: Path, args, pattern) -> str | None:
    key = (str(exe), exe.stat().st_mtime if exe.exists() else 0)
    if key not in _ver_cache:
        m = re.search(pattern, run([str(exe), *args], timeout=20).stdout) if exe.exists() else None
        _ver_cache[key] = m.group(1) if m else None
    return _ver_cache[key]


def apache_version(d: Path | None = None) -> str | None:
    d = d or paths.apache_dir()
    return _binary_version(d / "bin" / "httpd.exe", ["-v"], r"Apache/(\d+\.\d+\.\d+)") if d else None


def mysql_version(d: Path | None = None) -> str | None:
    d = d or paths.mysql_dir()
    return _binary_version(d / "bin" / "mysqld.exe", ["--version"], r"Ver (\d+\.\d+\.\d+)") if d else None


def pma_version() -> str | None:
    for f in ("libraries/classes/Version.php", "src/Version.php"):   # 5.x, 6.x
        try:
            m = re.search(r"VERSION = '(\d+\.\d+\.\d+[^']*)'", (paths.PMA / f).read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if m:
            return m.group(1)
    return None


def openssl_version() -> str | None:
    d = paths.apache_dir()
    exe = d / "bin" / "openssl.exe" if d else None
    return _binary_version(exe, ["version"], r"OpenSSL (\S+)") if exe else None


def composer_version() -> str | None:
    phar = paths.ROOT / "bin" / "composer" / "composer.phar"
    if not phar.exists() or not php.versions():
        return None
    ver = php.versions()[-1]
    exe = php.php_dir(ver) / "php.exe"
    key = (str(phar), phar.stat().st_mtime)
    if key not in _ver_cache:
        m = re.search(r"Composer version (\S+)", run([str(exe), "-n", str(phar), "--version"], timeout=20).stdout)
        _ver_cache[key] = m.group(1) if m else None
    return _ver_cache[key]


def xdebug_versions() -> list[str]:
    """Installed Xdebug DLL versions, one per PHP version that has one (from the DLL file name, e.g. php_xdebug-3.3.2-8.3-vs16-x86_64.dll)."""
    found = []
    for ver in php.versions():
        dlls = sorted((php.php_dir(ver) / "zend_ext").glob("php_xdebug*.dll")) if (php.php_dir(ver) / "zend_ext").is_dir() else []
        if dlls:
            m = re.search(r"xdebug-([\d.]+)", dlls[-1].name)
            found.append(f"{m.group(1)} (PHP {ver})" if m else f"? (PHP {ver})")
    return found


def php_fits(spec: str, ver: str) -> bool:
    """Does PHP `ver` match a constraint like ">=7.2,<8.4"? Unknown parts count as a match."""
    for part in filter(None, (x.strip() for x in (spec or "").split(","))):
        m = re.fullmatch(r"(>=|<=|>|<)\s*([\d.]+)", part)
        if not m:
            continue
        b = tuple(int(x) for x in m.group(2).split(".") if x)
        a = vkey(ver)[:len(b)]
        if not {">=": a >= b, "<=": a <= b, ">": a > b, "<": a < b}[m.group(1)]:
            return False
    return True


def _installed(root: Path, version_fn) -> list[dict]:
    active = (paths.apache_dir() if root == paths.APACHE_ROOT else paths.mysql_dir())
    return [{"name": d.name, "version": version_fn(d), "active": d == active} for d in paths.installed_dirs(root)]


def status() -> dict:
    """Installed versions merged with the last check."""
    c = _cached()
    cfg = settings.load()
    installed_php = php.versions()
    used = {v: [s["domain"] for s in cfg["sites"] if s["php"] == v] for v in installed_php}

    php_rows = []
    for r in c.get("php") or []:
        mine = [v for v in installed_php if v.startswith(r["branch"] + ".")]
        stable_mine = [v for v in mine if vkey(v)[-1] == 1]
        row = {**r, "installed": mine}
        if r["version"] in mine:
            row["state"] = "installed"
        elif not r["pre"] and stable_mine and vkey(r["version"]) > vkey(stable_mine[-1]):
            row["state"] = "update"
        else:
            row["state"] = "available"
        php_rows.append(row)
    known = {r["branch"] for r in php_rows}
    for v in installed_php:          # installed branches the feed doesn't list (e.g. before the first check)
        br = ".".join(v.split(".")[:2])
        if br not in known:
            known.add(br)
            php_rows.append({"branch": br, "version": None, "pre": False, "state": "installed",
                             "installed": [x for x in installed_php if x.startswith(br + ".")]})
    php_rows.sort(key=lambda r: (vkey(r["branch"]), r["pre"]), reverse=True)

    a_now = apache_version()
    a_remote = c.get("apache")
    m_now = mysql_version()
    m_rows = [dict(r, newer=vkey(r["version"]) > vkey(m_now or "0")) for r in c.get("mysql") or []]
    # Recommended: the newest LTS we can move to (MySQL can't go back to an older series).
    rec = next((r for r in m_rows if r["lts"] and r["newer"]), None)
    for r in m_rows:
        r["recommended"] = r is rec
    p_now, p_remote = pma_version(), c.get("pma")
    site_php = cfg["sites"][0]["php"] if cfg["sites"] else None     # phpMyAdmin runs on the default site
    return {
        "checked": c.get("checked"),
        "errors": c.get("errors", {}),
        "php": php_rows,
        "php_used": used,
        "apache": {"version": a_now, "latest": a_remote,
                   "update": bool(a_remote and a_now and vkey(a_remote["version"]) > vkey(a_now)),
                   "installed": _installed(paths.APACHE_ROOT, apache_version)},
        "mysql": {"version": m_now, "available": [r for r in m_rows if r["newer"]],
                  "installed": _installed(paths.MYSQL_ROOT, mysql_version)},
        "pma": {"version": p_now, "latest": p_remote, "php": site_php,
                "update": bool(p_remote and vkey(p_remote["version"]) > vkey(p_now or "0")),
                "php_ok": bool(not p_remote or not site_php or php_fits(p_remote.get("php_versions"), site_php))},
    }


# ---------------------------------------------------------------- PHP

def _php_entry(version):
    e = next((r for r in _cached().get("php") or [] if r["version"] == version), None)
    if not e:
        raise ValueError(f"PHP {version} is not in the list, press Check for updates first")
    return e


def install_php(job, version) -> str:
    e = _php_entry(version)
    target = paths.PHP_ROOT / f"php{version}"
    if (target / "php-cgi.exe").exists():
        raise ValueError(f"PHP {version} is already installed")
    z = download(e["url"], job, f"PHP {version}", e.get("sha256"))
    extract(z, target, job)
    job.update(f"Testing PHP {version}")
    r = run([str(target / "php.exe"), "-n", "-v"], timeout=30)
    if r.returncode != 0 or "PHP" not in r.stdout:
        shutil.rmtree(target, ignore_errors=True)
        raise RuntimeError(f"PHP {version} does not start on this PC. It probably needs the Microsoft "
                           f"Visual C++ Redistributable: {VC_REDIST}\n{(r.stdout + r.stderr)[-400:]}")
    job.update("Writing php.ini")
    php.ensure_ini(version)
    z.unlink(missing_ok=True)
    return version


def update_php(job, old, version) -> dict:
    """Install a newer release of the same branch, carry over php.ini and extra extensions, move the sites."""
    if version.split(".")[:2] != old.split(".")[:2]:
        raise ValueError("Updates stay within one branch (e.g. 8.3.x)")
    install_php(job, version)
    job.update("Copying php.ini settings")
    php.copy_setup(old, version)
    job.update("Moving sites to the new version")
    moved = core.move_php_sites(old, version)
    return {"version": version, "moved": moved}


def remove_php(ver):
    cfg = settings.load()
    users = [s["domain"] for s in cfg["sites"] if s["php"] == ver]
    if users:
        raise ValueError(f"PHP {ver} is used by {', '.join(users)}")
    if cfg.get("default_php") == ver:
        raise ValueError(f"PHP {ver} is the default for new sites, pick another default first")
    shutil.rmtree(php.php_dir(ver))


# ---------------------------------------------------------------- Apache

def install_apache(job) -> str:
    c = _cached().get("apache")
    if not c:
        raise ValueError("Press Check for updates first")
    name = f"apache{c['version']}"
    target = paths.APACHE_ROOT / name
    _pin("apache", paths.apache_dir())
    if not target.exists():
        z = download(c["url"], job, f"Apache {c['version']}")
        extract(z, target, job, strip="Apache24/")
        z.unlink(missing_ok=True)
        fcgid = target / "modules" / "mod_fcgid.so"
        if c.get("fcgid_url"):
            job.update("Downloading mod_fcgid")
            fz = download(c["fcgid_url"], job, "mod_fcgid")
            with zipfile.ZipFile(fz) as zf:
                n = next((n for n in zf.namelist() if n.endswith("mod_fcgid.so")), None)
                if n:
                    fcgid.write_bytes(zf.read(n))
            fz.unlink(missing_ok=True)
        if not fcgid.exists():
            shutil.copy2(paths.apache_dir() / "modules" / "mod_fcgid.so", fcgid)
    job.update(f"Switching to Apache {c['version']}")
    core.switch_apache(name)
    return name


# ---------------------------------------------------------------- MySQL

def install_mysql(job, version) -> str:
    e = next((r for r in _cached().get("mysql") or [] if r["version"] == version), None)
    if not e:
        raise ValueError(f"MySQL {version} is not in the list, press Check for updates first")
    now = mysql_version()
    if now and vkey(version) <= vkey(now):
        raise ValueError(f"MySQL can't go back from {now} to {version}")
    name = f"mysql{version}"
    target = paths.MYSQL_ROOT / name
    _pin("mysql", paths.mysql_dir())
    if not target.exists():
        z = download(e["url"], job, f"MySQL {version}")
        # Debug symbols and the test suite are most of the zip and never needed here.
        extract(z, target, job, strip=f"mysql-{version}-winx64/", skip=(".pdb", "/mysql-test/", "/lib/debug/"))
        z.unlink(missing_ok=True)
    core.upgrade_mysql(name, log=lambda m: job.update(m))
    return name


# ---------------------------------------------------------------- phpMyAdmin

def install_pma(job) -> str:
    """Replace apps/phpmyadmin with the newest release, keeping config.inc.php (and so everyone's login cookie)."""
    c = _cached().get("pma")
    if not c:
        raise ValueError("Press Check for updates first")
    v = c["version"]
    url = PMA_ZIP.format(v=v)
    sha = fetch(url + ".sha256").decode("ascii", "replace").split()[0]
    z = download(url, job, f"phpMyAdmin {v}", sha)
    new = paths.PMA.with_name(f"phpmyadmin-{v}")
    old = paths.PMA.with_name("phpmyadmin.old")
    shutil.rmtree(new, ignore_errors=True)     # left over from a failed try
    extract(z, new, job, strip=f"phpMyAdmin-{v}-all-languages/")
    z.unlink(missing_ok=True)
    job.update(f"Switching to phpMyAdmin {v}")
    had = paths.PMA.is_dir()
    shutil.rmtree(old, ignore_errors=True)
    if had:
        conf = paths.PMA / "config.inc.php"
        if conf.exists():
            shutil.copy2(conf, new / "config.inc.php")
        paths.PMA.rename(old)
    try:
        new.rename(paths.PMA)
    except OSError:
        if had:
            old.rename(paths.PMA)
        raise
    cfg = settings.load()
    mysql.write_pma_config(cfg)
    if not had:          # the /phpmyadmin alias is only written when the folder exists
        core.apply(cfg)
    shutil.rmtree(old, ignore_errors=True)
    return v


XDEBUG_HISTORICAL = "https://xdebug.org/download/historical"
_XDEBUG_LINK = re.compile(
    r"""href=['"]/files/php_xdebug-([\d.]+)-(\d+\.\d+)-(ts|nts)-(vs\d+)-x86_64\.dll['"]""")


_xdebug_cache = (0.0, [])


def xdebug_catalog() -> list[dict]:
    """[{version, php_minor, ts, compiler}] for every stable 3.x Windows x86_64 build listed on xdebug.org.
    Cached for a day: the PHP page asks for it every time a version is opened."""
    global _xdebug_cache
    if time.time() - _xdebug_cache[0] < 86400:
        return _xdebug_cache[1]
    html = fetch(XDEBUG_HISTORICAL).decode("utf-8", errors="replace")
    out = []
    for ver, minor, ts, vs in _XDEBUG_LINK.findall(html):
        if not ver.startswith("3.") or re.search(r"(alpha|beta|rc)", ver, re.I):
            continue
        out.append({"version": ver, "php_minor": minor, "ts": ts == "ts", "compiler": vs})
    _xdebug_cache = (time.time(), out)
    return out


def xdebug_match(php_ver: str, build) -> dict | None:
    """The newest stable 3.x Xdebug build that fits an installed PHP's minor/TS/compiler, if any."""
    minor = ".".join(php_ver.split(".")[:2])
    candidates = [x for x in xdebug_catalog()
                  if x["php_minor"] == minor and x["ts"] == build["ts"] and x["compiler"] == build["compiler"]]
    if not candidates:
        return None
    return max(candidates, key=lambda x: vkey(x["version"]))


def install_xdebug(job, ver: str) -> str:
    """Download the matching Xdebug build for PHP `ver` into its zend_ext folder. Returns the Xdebug version."""
    build = php.build_info(ver)
    if not build["compiler"]:
        raise RuntimeError(f"Can't tell which Visual C++ runtime PHP {ver} was built with")
    job.update("Looking up the matching Xdebug build")
    match = xdebug_match(ver, build)
    if not match:
        raise RuntimeError(f"No Xdebug 3.x build for PHP {ver} ({'TS' if build['ts'] else 'NTS'}, "
                           f"{build['compiler']}) - it may be a pre-release PHP that Xdebug doesn't support yet")
    ts = "ts" if build["ts"] else "nts"
    name = f"php_xdebug-{match['version']}-{match['php_minor']}-{ts}-{match['compiler']}-x86_64.dll"
    url = f"https://xdebug.org/files/{name}"
    dest_dir = php.php_dir(ver) / "zend_ext"
    dest_dir.mkdir(exist_ok=True)
    dl = download(url, job, f"Xdebug {match['version']}")
    for old in dest_dir.glob("php_xdebug*.dll"):
        old.unlink(missing_ok=True)
    shutil.copy2(dl, dest_dir / name)
    return match["version"]


COMPOSER_URL = "https://getcomposer.org/download/latest-stable/composer.phar"
COMPOSER_SHA_URL = COMPOSER_URL + ".sha256"


def install_composer(job) -> str:
    """Download the latest composer.phar, verified against its published sha256, to bin/composer."""
    job.update("Checking latest version")
    sha256 = fetch(COMPOSER_SHA_URL).decode().strip().split()[0]
    dl = download(COMPOSER_URL, job, "Composer", sha256)
    paths.COMPOSER.mkdir(parents=True, exist_ok=True)
    shutil.move(dl, paths.COMPOSER_PHAR)
    from . import cli
    cli.write_shims(settings.load())
    return composer_version()


def _pin(key, current: Path | None):
    """Remember the running version explicitly, so a newly unpacked folder doesn't become active by itself."""
    cfg = settings.load()
    if current and not cfg.get(key):
        cfg[key] = current.name
        settings.save(cfg)


def remove_server(kind, name):
    root = paths.APACHE_ROOT if kind == "apache" else paths.MYSQL_ROOT
    target = root / name
    active = paths.apache_dir() if kind == "apache" else paths.mysql_dir()
    if not target.is_dir() or target.parent != root:
        raise ValueError(f"{name} is not installed")
    if target == active:
        raise ValueError(f"{name} is in use")
    shutil.rmtree(target)
