# Changelog

The newest `## x.y.z - date` heading is the app version shown under the DevStack logo.
Bullets can wrap onto the next line with two spaces of indent.

## 1.0.0 - 2026-09-25

### Install
- `install.bat`: one command installs the Python packages, downloads Apache, PHP 8.3 + the newest PHP, MySQL (LTS)
  and phpMyAdmin, writes the config and adds a desktop shortcut. No other local server needed.
- Installs the Visual C++ runtime if it's missing.

### Servers
- Apache 2.4 and MySQL 9.x run as Windows services that start with Windows, or as background processes.
- Servers page: status, ports, run mode, and Apache / MySQL / phpMyAdmin version updates.
- MySQL updates back up the data folder first and roll back if the new version doesn't start.
- MySQL listens on both 127.0.0.1 and ::1, so connecting to `localhost` no longer waits 2 s on IPv6.
- HTTP/2 on HTTPS sites.

### Sites
- One click creates `<name>.test` with its own PHP version, HTTPS certificate and hosts entry. No manual vhost or restart.
- Add existing folders in bulk; `public/` or `web/` is picked as the document root.
- Sites table: PHP picker, database, SSL, size, created date, edit and delete.
- New site: optional "Create a database and user" (random password, shown once).
- Site aliases (`admin.shop.test`, `*.shop.test`): added to ServerAlias, the certificate and the hosts file
  (wildcards can't go in hosts - noted in the dialog). Edit in the site edit dialog.
- Per-site extra Apache directives (advanced): a bad one rolls back with `httpd -t`'s error shown, nothing else changes.
- Per-site PHP error log (`logs/sites/<domain>-php.log`), separate from every other site. A red dot on the site row
  when it has new errors since you last looked; click it to jump to that log.
- Add existing folders: pick the served folder per project (e.g. `web/production`, `production`, or any folder
  via the folder button) and link an existing database per site. A project's other docroots (e.g. `web/staging`)
  stay listed after one is added.
- New site: Database dropdown - auto-detect, none, create a new database and user, or pick an existing one.
- Warning when a wildcard alias (e.g. `*.adphealth.test`) would catch another site (`staging.adphealth.test`).
- Clone a site (folder + database, same PHP), export one to a .zip (project + database.sql + site.json), and
  import a site from a .zip - all as background jobs.
- Share a site on the LAN: its own port, a QR code and URL for other devices on your network, and an
  "Allow in firewall" button - now its own dialog from a row icon, with a compact "LAN :port" tag on shared sites.
- Aliases and extra Apache directives use a proper textarea (matches the other inputs) with examples moved into
  the placeholder text.

### PHP
- PHP 5.6 up to the newest release and pre-releases, installable and updatable from the app.
- Per-version php.ini editor: common settings, timezone list, extensions.
- OPcache and realpath cache tuned on every version.
- PHP CLI: a shared `php` (and `composer`) on PATH via `bin/cli`, picking a site's own version from a `.php-version`
  file or a chosen fallback version. PHP page › CLI & Composer.
- One-click Xdebug install: downloads the matching build from xdebug.org for the version's thread safety and
  compiler, then it's a normal checkbox in Extensions (port 9003, `XDEBUG_TRIGGER`).
- Sites page: Terminal icon opens a console in the project folder with that site's PHP version on PATH.

### Database
- Database list with size, tables, last change and the site that uses it.
- Export to .sql, back up to the exports folder, open in phpMyAdmin.
- Import a whole MySQL data folder from another local server.
- Create a database (+ optional user with a random password) from a new site or from the Database page.
- Export/backup show real progress; Import .sql (also .sql.gz) with a file picker and progress, with the option
  to create the target database first.
- Scheduled backups: once every 24 h per database into `data/exports/auto`, keeping the last N; last-backup time
  shown per row. Moved to its own section on the Database page.
- Database page: left sub-menu (Databases, Users, Backups, Import), like the PHP page.
- Backups tab: scheduled backups, SQL backups and data folder backups in one place (moved off the Databases tab).
- Import tab: Import .sql, Import Database (data folder), and a short guide for moving databases in from another
  local server.
- Users section: every MySQL user with the databases it can access, change password, delete user (root is shown
  as the main user and can't be deleted). The Databases table now shows which user(s) have access to each one.

### Mail
- Local mail catcher: turn it on (now from the Mail page itself) and PHP's `mail()` lands on a Mail page instead of
  actually sending - headers, text and HTML (in a sandboxed preview), attachments with a save button. Unread count
  in the nav.

### Certificates
- Local certificate authority trusted by Windows, Chrome and Edge.
- Per-site certificate status, renew, HTTPS on/off, leftover cleanup.

### App
- Dashboard with overview, quick links and live CPU / RAM / disk activity for Apache, PHP and MySQL (15 min to 3 h history).
- Dashboard sites are cards (6 per row): the site's favicon (found in its folder, globe if none), name, HTTPS shield and
  PHP version; click opens the site. The Activity column is wider.
- Settings › Storage (replaces Folders): space used by sites, databases, apps & programs, logs and SQL backups, each with
  its folder, plus the space per site. Linked from the dashboard overview ("details").
- Tray icon: start / stop servers, open sites and phpMyAdmin. Closing the window keeps DevStack in the tray.
- Logs page with Clear all.
- Changelog: click the version under the DevStack logo.
- The window always loads the current UI after an update (the WebView cache is cleared at start).
  Launching DevStack while an older copy still runs in the tray now closes that copy and starts the updated one.
- About popup (`v1.0.0 | About` under the logo) with About, License and Components tabs: credits, the full license
  text and bundled component versions (Apache, PHP, MySQL, phpMyAdmin, OpenSSL, Xdebug, Composer).
- Settings › Appearance: System, Dark or Light theme. Accent color is teal (`#00f5d4`) in both themes; Light theme
  logo is flat black/teal. UI font is Segoe UI.
- Settings › Appearance: pick any installed font for the UI (Reset goes back to Segoe UI), and a font size:
  Compact, Default, Large or Extra large.
- Three button styles in both themes: light outline for general actions, solid (black in Light, white in Dark)
  for submit/save, and teal for updates and other important actions (Start all, Finish setup, Trust CA).
- Start-up screen covers the window until DevStack has fully loaded, so no page opens half-ready.
- Settings › Troubleshoot (was "Doctor"): checks ports, other local servers' services, the VC++ runtime, the CA, hosts entries,
  `httpd -t`, each site's folder/PHP/certificate, and MySQL - with a Fix button where it's safe to act automatically.
- PHP page: CLI & Composer and + Install / update moved into their own card, separate from the version list.

### Faster
- Pages show their last data instantly and refresh in the background, instead of a "Loading…" screen on every visit.
- Certificates page opens in about 1 ms instead of 300 ms (CA check is cached).
- About 60 s after closing the window to the tray, its WebView is closed too, bringing DevStack down from about 280 MB to about 65 MB of RAM.
  Opening it again from the tray takes about a second.
