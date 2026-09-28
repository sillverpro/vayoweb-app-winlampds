# DevStack

Local LAMP stack for Windows (desktop app). LAMP only: Apache 2.4, PHP 5.6–8.x (installable from the app), MySQL 9.x, phpMyAdmin.
Desktop app is Python 3.13 + pywebview 6 (WebView2). README.md has the user-facing overview, install and first-start guide.
Public-facing text (README, UI) must not name other local-server products, except the Database › Import guide.

## Goals (keep it small)
- Apache + MySQL as Windows services that auto-start at boot.
- Many sites, each `<name>.test`, each with its own PHP version, created in one click (no manual vhost/restart).
- Per-PHP-version php.ini handled by the app (short_open_tag On everywhere, sane limits).
- Local HTTPS via our own CA. One MySQL, one phpMyAdmin at `localhost.test/phpmyadmin`.
- Default site `localhost.test` = dashboard (`www/localhost`).
- A site can optionally be shared on the LAN (its own port, QR code) and PHP mail can optionally be caught
  locally instead of sent (Mail page) - both off by default, per site / globally.
Don't add features beyond this unless asked (no nginx, no Node…).

## Layout
```
DevStack.bat                 launches app/main.py with pythonw / pyw (asks for admin via UAC)
install.bat                  pip install + app/bootstrap.py + desktop shortcut
app/main.py                  window + UAC relaunch (--no-admin, --debug)
app/bootstrap.py             one-time: downloads Apache+mod_fcgid, PHP (8.3,latest), MySQL LTS, phpMyAdmin via updates.py helpers, then core.initialize
app/devstack/
  paths.py                   every path constant (ROOT = F:\devstack)
  settings.py                config/devstack.json load/save  <- source of truth
  core.py                    high-level ops: initialize, create/update/delete/import sites, ports, run mode
  apache.py                  renders config/apache/httpd.conf + sites/<domain>.conf, httpd -t
  php.py                     php.ini per version (edited in place, keeps manual edits)
  mysql.py                   my.ini, datadir init/import, phpMyAdmin config
  ssl.py                     local CA + per-site certs (cryptography lib), certutil trust
  hosts.py                   managed block "# >>> DevStack" in the Windows hosts file
  services.py                start/stop: "service" mode (Windows services) or "process" mode
  api.py                     pywebview js_api; every endpoint returns {ok,data} / {ok:false,error}
  updates.py                 version check + install: PHP (windows.php.net), Apache (apachelounge), MySQL (GitHub tags + cdn.mysql.com);
                             also Composer (getcomposer.org) and Xdebug (xdebug.org/download/historical)
  cli.py                     bin/cli/php.bat + composer.bat shims (version -> installed folder baked in at generation time),
                             HKCU\Environment PATH add/remove
  doctor.py                  read-only environment checks for Settings -> Doctor (ports, hosts, certs, PHP, MySQL, VC++ runtime...)
  mailcatch.py                stdlib SMTP server (feature P): saves each message as data/mail/<ts>-<id>.eml instead of sending it;
                             also the .eml reader for the Mail page (list/read/attachments/delete)
app/ui/vendor/qrcode.js      qrcode-generator (Kazuhiko Arase, MIT), vendored for the LAN-sharing QR code - no CDN
  jobs.py                    background jobs (downloads/installs), one at a time; UI polls `jobs`
  stats.py                   dashboard numbers: folder sizes (background, 10 min cache), site->DB detection,
                             1 s psutil sampler thread (CPU/RAM/IO per server; 15 min at 1 s + 3 h of 10 s averages, in memory)
  tray.py                    pystray icon: X hides the window here (setting close_to_tray), menu = servers / sites / quit
  version.py                 app version + release notes, parsed from CHANGELOG.md
  winutil.py                 hidden-console run/spawn, is_admin, pid/port helpers
app/ui/                      index.html, style.css, app.js (vanilla JS, no build step)
app/templates/localhost/     dashboard copied to www/localhost
CHANGELOG.md                 "## x.y.z - date" + "### Section" + "- item"; newest heading = app version (sidebar, click = popup)
bin/{apache,php,mysql}       server binaries (downloaded, one folder per version);  apps/phpmyadmin
config/  data/mysql  data/exports (.sql backups)  ssl/  logs/  tmp/  www/
```

## How things work
- PHP per site = mod_fcgid: each vhost sets `FcgidWrapper <php-cgi.exe>` + `FcgidInitialEnv PHPRC`. No mod_php.
- Every settings change goes through `core._transaction`: save → write Apache config → `httpd -t` → sync hosts (admin only) → restart Apache; rolls back on failure.
- `core.reconcile()` runs on every `state` call and on the 5s `status` poll. It catches up with changes made outside the app, e.g. by a script:
  it rewrites the Apache config if `devstack.json` is newer, syncs hosts (admin only), and restarts Apache if a conf file is newer than `logs/httpd.pid`.
- Never put a public attribute on `Api` that holds a big object (e.g. the window): pywebview walks js_api attributes
  recursively at startup, and `api.window` made it crawl the .NET form tree for 30-60 s. Use `_name`.
- Close to tray: X hides the window; after `tray.RELEASE_AFTER` (60 s) the window is destroyed so WebView2 frees its
  memory (~280 MB -> ~65 MB). webview.start() then returns and main.py waits in `tray.wait_for_show()` and opens a new
  window in the same process. So `api._window` / `tray.window` can be None; never keep references to an old window.
- UI page data: `cached(key, endpoint, args, draw)` in app.js draws the last data at once and redraws only if the fresh
  copy differs; `prefetch()` fills it after start. After a change, `delete CACHE[key]` (or pass fresh=true) first.
- Single instance: main.py listens on 127.0.0.1 (port in `tmp/app-instance.port`); a second launch asks it to show and exits.
- Dashboard Activity polls `activity(fine_since, coarse_since)` every second and only gets new history rows.
- WebView storage is persistent (`tmp/webview`), so the UI can remember things like a dismissed note in localStorage.
- Default site config is `000-localhost.test.conf` so it catches unknown hosts.
- Site dict: `{name, domain, root, php, ssl}`. `root` is the document root (e.g. `.../project/public` for Laravel).
  Optional: `db` (see below), `aliases` (ServerAlias + cert SANs + hosts, wildcards skip hosts), `apache_extra` (raw directives
  inserted in each VirtualHost, validated by the normal `_transaction` httpd-t/rollback path - no special-casing needed).
- "Add existing folders" (Sites page) = `core.scan_folder` + `core.import_sites`: bulk-adds subfolders, auto-picks `public/` or `web/` as docroot.
- Process mode: Apache has no graceful stop from outside in console mode, so stop = `taskkill /F /T`. MySQL stops via mysqladmin.
- A process started by the elevated app can't be killed by a non-elevated one (Access denied).
- Versions: each one gets its own folder (`bin/php/php8.3.35`, `bin/apache/apache2.4.68`, `bin/mysql/mysql9.7.2`).
  Active Apache/MySQL folder = `apache` / `mysql` in devstack.json (None = newest). Switching re-installs the Windows service.
  PHP update = install new patch + `php.copy_setup` (ini, extra DLLs) + move sites. MySQL update backs up `data/mysql` to
  `data/mysql.bak-<ts>-<old>` first and restores it if the new version doesn't start. Downloads use certifi (Python's store has an expired root).
- Site↔database: auto-detected from the project's config files (stats.detect_site_dbs); site `db` overrides it (null = auto, "" = none).
  `mysql.create_database` makes a utf8mb4 DB (+ optional user@localhost/@127.0.0.1 with a random password, shown once, never stored).
- `apache.write_all` only writes changed files, so a settings save doesn't make reconcile() restart Apache. It also writes each site's
  `config/php-site/<domain>/devstack.ini` (its own `error_log`) and points `PHP_INI_SCAN_DIR` there per vhost - mod_fcgid keys a
  separate php-cgi process class per distinct FcgidInitialEnv set, so this reliably gives each site its own error log even when
  several sites share the same PHP version (verified on a temp Apache: each vhost's PHP process picked up its own scan dir and log).
- mysqldump: `mysql.export_db(..., standalone=True)` (the normal Export/backup) embeds `CREATE DATABASE`/`USE`, so the file restores
  itself under its own name. `standalone=False` (clone_site, export_site) dumps tables/data only, since those import under a
  *different* database name and a baked-in USE would silently write back into the original db instead.
- Site clone/export/import (core.py): clone copies the folder (skips `.git`, `node_modules`) and the database via
  export_db|create_database|import_sql; export makes `data/exports/<site>-<ts>.zip` (`project/`, `database.sql`, `site.json`);
  import reverses it. All three are jobs with progress.
- Scheduled backups: `mysql.start_backup_thread()` (started once from `Api.__init__`, so it keeps running in tray mode) checks
  hourly and dumps any due database (last dump older than 24h) via the `backup` setting into `data/exports/auto/`,
  pruning to `keep` per database there only (manual backups in `data/exports` are never pruned).
- LAN sharing: site field `lan_port` (auto-picked from 8100, unique). `apache.render_site` adds its own `Listen <port>` +
  a third `<VirtualHost *:<port>>` (HTTP only, `Require all granted` instead of `Require local`) inside that site's own
  conf file - no changes to httpd.conf needed since each port is unique to one site. `core.lan_ip()` guesses the LAN IPv4
  via a UDP "connect" to 8.8.8.8 (no packet actually sent - it just makes the OS pick a routable local address).
  Firewall rule add/remove (`core.allow_lan_firewall` / `remove_lan_firewall`, `netsh advfirewall`) only ever runs from
  the explicit UI button, or automatically on remove when sharing is turned off - never from `_transaction`/reconcile().
- Mail catcher: `mailcatch.start()` (from `Api.__init__` if `mail_catcher` is on) runs a small stdlib SMTP server on
  `mail_port` (127.0.0.1 only), saving each message as `data/mail/<ts>-<id>.eml`. Turning it on in Settings also sets
  `SMTP`/`smtp_port`/`sendmail_from` in every installed PHP's php.ini (`php.set_mail_catcher`); turning it off leaves
  php.ini alone (mail() then fails loudly instead of silently "succeeding" into nothing).
- Speed: `php.tune` sets OPcache (revalidate_freq 0, file_cache fallback in `tmp/opcache/<ver>`) + realpath cache once per php.ini,
  guarded by the `php.TUNED` marker line. New inis get it in ensure_ini; existing ones on the first reconcile() of an app start (restarts Apache).
  HTTP/2: mod_http2 + `Protocols h2 http/1.1` (only used over TLS).
- phpMyAdmin: version read from `libraries/classes/Version.php` (6.x: `src/`). Update = `updates.install_pma` (phpmyadmin.net feed,
  sha256 checked), extracts to `apps/phpmyadmin-<v>`, copies config.inc.php over, swaps folders. It runs on the default site's PHP.
- PHP CLI: `bin/cli/php.bat` walks up from `%CD%` for a `.php-version` file (branch or full version) and resolves it against a
  version->folder map baked into the batch file when `cli.write_shims` runs (falls back to the `cli_php` setting); regenerated on
  reconcile() when the installed PHP versions change. `bin/cli/composer.bat` just calls `php <path to composer.phar> %*`, so it uses
  whichever `php` PATH resolves to (a site's own PHP dir comes first in the "Terminal here" console, ahead of `bin/cli`).
  "Terminal here" spawns plain `cmd.exe` (not wt.exe: a running Windows Terminal would ignore our environment).
  Note Windows searches the system PATH before the user PATH, so another php on the system PATH wins (Doctor warns).
- Xdebug: `php.build_info` reads TS/NTS + compiler (`Visual C++ 2019/2022` -> `vs16`/`vs17`) from `php -i`; `updates.install_xdebug`
  matches that against xdebug.org's historical download list (3.x only, PHP 8.0+) and downloads the DLL into that version's
  `zend_ext` folder. From there it's an ordinary extension (`php.set_extension` writes a `[xdebug]` block: mode, trigger, port 9003).

## Working on it (for Claude)
- User runs the app elevated; hosts file, services and CA trust need admin. The Claude shell is NOT admin.
- If the user's DevStack window is running Apache, don't start/stop/restart it from scripts. Test on a temporary copy instead:
  copy `config/apache/httpd.conf` + `sites/*.conf` to the scratchpad, change ports (e.g. 8090/8453), PidFile, and the IncludeOptional path, then run `bin/apache/<version>/bin/httpd.exe -f <copy>`.
  In Python tests, stub `services.status = lambda cfg, kind: "stopped"` so `core` doesn't restart the user's Apache.
- HTTPS with curl: add `--ssl-no-revoke` (Schannel can't check revocation for a local CA). Use `--resolve host:port:127.0.0.1` for domains not in hosts.
- Check JS with `node --check app/ui/app.js`. For UI checks, drive pywebview with `evaluate_js` in an off-screen test window
  (`x=-3000`) with `webview.start(http_port=42155, ...)`: pywebview's default port 42001 is the user's running app, and a
  test window on it silently loads the user's (old) UI. Never screen-grab (it captures the user's other windows).
- Keep the UI style: flat, dark/light tokens in style.css, escape all output with `esc()`, actions via `act(btn, endpoint, args, okMsg)`.
  Row tools are icon buttons: `iconBtn(name, title, attrs, cls)` with stroke icons from `ICONS` in app.js.
- Pages: Dashboard (activity in the right column), Servers (service cards, ports, run mode, server versions), Sites (LAN share = own dialog),
  PHP (versions card + CLI/Install card), Database (left sub-menu: Databases / Users / Backups / Import), Certificates, Mail (catcher settings on top),
  Logs, Settings (theme, tray, folders, Troubleshoot = doctor checks).
- Theme tokens: accent #00f5d4 both themes; `--accent-text` for accent-coloured text (darker in light), `--primary`/`--btn-line` for buttons (black in light).
- Site `created` (unix time) is stored on create/import; older sites fall back to the project folder's creation time.
- Report work in brief mode (global CLAUDE.md).
- User-visible changes get a bullet in CHANGELOG.md. Bump the version (new `## x.y.z - date` heading) when the user asks
  for a release; otherwise add to the newest one.

## Source control
Public repo `github.com/sillverpro/vayoweb-app-winlampds`. Git carries **only the app**: `app/`, `DevStack.bat`, `install.bat`, docs, CHANGELOG.
Not in git (see `.gitignore`): `bin/`, `apps/`, `config/`, `data/`, `ssl/`, `www/`, `logs/`, `tmp/`, `docs/chat-log/`, `CLAUDE.local.md`.
- Machine-specific notes (this install's sites, versions, history) go in `CLAUDE.local.md`, never in this public file.
- Fresh clone: `install.bat` (= pip install + `python app/bootstrap.py`) downloads everything into `bin/` + `apps/`,
  writes a new `config/devstack.json`, a new local CA (`ssl/`) and an empty MySQL datadir (root, no password);
  then run the app as admin -> Finish setup. `--skip-download` only writes the config. Tested end to end in a
  scratch copy on 2026-09-28 (Apache 2.4.68, PHP 8.3.35 + 8.5.11, MySQL 9.7.2, phpMyAdmin 5.2.3).
- Databases move with Database -> Export/Import (or a copy of `data/mysql` while MySQL is stopped), never via this repo.
- Sites (`www/`) are separate repos; re-add them with Sites -> Add existing folders.
- Mac: the app is Windows-only. A macOS port lives in `for_mackbook/` (gitignored here, its own repo; see its agent.md).
- Line endings: `.gitattributes` (`text=auto`, `.bat` = CRLF) + `core.autocrlf=input`. Set `git config core.autocrlf input` on each new clone.

## Ideas not started (only if asked)
- PyInstaller single .exe (`--uac-admin`) so Python isn't required (paths.py already handles `sys.frozen`).
