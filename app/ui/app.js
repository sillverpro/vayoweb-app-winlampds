"use strict";

const main = document.getElementById("main");
let S = null;             // last state from the backend
let view = "dashboard";
let phpVer = null;        // selected version on the PHP view ("install" = the versions list)
let logFile = null;
let PHP_LOG_MTIMES = {};   // {domain: mtime}, from the 5s status poll - drives the Sites page error badge
let MAIL_COUNT_LAST = 0;   // last mail_count seen (from status poll), to know when to redraw the Mail page

// Nav badge: number of messages since the last time the Mail page was opened (count stored in localStorage).
function updateMailBadge(count) {
  MAIL_COUNT_LAST = count;
  const badge = document.getElementById("mail-badge");
  if (!badge) return;
  let seen = 0;
  try { seen = Number(localStorage.getItem("mail-seen-count") || 0); } catch { /* no storage */ }
  const unread = Math.max(0, count - seen);
  badge.textContent = unread > 99 ? "99+" : String(unread);
  badge.hidden = !unread;
}

function markMailSeen(count) {
  try { localStorage.setItem("mail-seen-count", String(count)); } catch { /* no storage */ }
}
let ST = null;            // last dashboard numbers (stats endpoint)

// ------------------------------------------------------------------ helpers

function fmtBytes(n) {
  if (n == null) return "…";
  const u = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return `${n >= 100 || i === 0 ? Math.round(n) : n.toFixed(1)} ${u[i]}`;
}

function fmtAgo(ts) {
  if (!ts) return "never";
  const s = Date.now() / 1000 - ts;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} days ago`;
}

function fmtUptime(since) {
  if (!since) return "";
  const s = Date.now() / 1000 - since;
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))} min`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ${Math.round((s % 3600) / 60)} min`;
  return `${Math.floor(s / 86400)} d ${Math.round((s % 86400) / 3600)} h`;
}

const fmtDate = (ts) => (ts ? new Date(ts * 1000).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" }) : "");

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// Stroke icons (24 x 24). icon(name) -> inline svg, iconBtn(name, title, attrs) -> square button with a tooltip.
const ICONS = {
  edit: '<path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
  trash: '<path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M10 11v6M14 11v6"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/>',
  archive: '<rect x="2" y="3" width="20" height="5" rx="1"/><path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8M10 12h4"/>',
  pma: '<path d="M11 3v13H4zM13 6l6 10h-6z"/><path d="M2 18h20l-2.5 3h-15z"/>',   // phpMyAdmin's sailboat
  table: '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M3 15h18M9 3v18"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
  folder: '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.7-.9l-.8-1.2A2 2 0 0 0 7.9 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2z"/>',
  globe: '<circle cx="12" cy="12" r="9"/><path d="M12 3a13.5 13.5 0 0 0 0 18 13.5 13.5 0 0 0 0-18M3 12h18"/>',
  db: '<ellipse cx="12" cy="5.5" rx="8" ry="2.8"/><path d="M4 5.5v13c0 1.5 3.6 2.8 8 2.8s8-1.3 8-2.8v-13M4 12c0 1.5 3.6 2.8 8 2.8s8-1.3 8-2.8"/>',
  layers: '<path d="m12 2 10 5-10 5L2 7z"/><path d="m2 17 10 5 10-5M2 12l10 5 10-5"/>',
  drive: '<path d="M22 12H2M5.5 5.1 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.5-6.9A2 2 0 0 0 16.8 4H7.2a2 2 0 0 0-1.7 1.1zM6 16h.01M10 16h.01"/>',
  server: '<rect x="3" y="3" width="18" height="7" rx="2"/><rect x="3" y="14" width="18" height="7" rx="2"/><path d="M7 6.5h.01M7 17.5h.01"/>',
  play: '<path d="M7 4v16l13-8z"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="1.5"/>',
  restart: '<path d="M21 12a9 9 0 1 1-2.6-6.4L21 8M21 3v5h-5"/>',
  external: '<path d="M15 3h6v6M10 14 21 3M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
  terminal: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="m7 9 3 3-3 3M13 15h4"/>',
  copy: '<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1"/>',
  share: '<path d="M2 8.5a15 15 0 0 1 20 0M5 12.5a10 10 0 0 1 14 0M8.5 16.5a5 5 0 0 1 7 0"/><circle cx="12" cy="20" r="1"/>',
};
const icon = (n) => `<svg class="ic" viewBox="0 0 24 24" aria-hidden="true">${ICONS[n]}</svg>`;
const iconBtn = (n, title, attrs = "", cls = "") =>
  `<button type="button" class="btn icon-btn ${cls}" title="${esc(title)}" aria-label="${esc(title)}" ${attrs}>${icon(n)}</button>`;

function toast(msg, error = false) {
  const el = document.createElement("div");
  el.className = "toast" + (error ? " error" : "");
  el.textContent = msg;
  el.onclick = () => el.remove();
  document.getElementById("toasts").append(el);
  setTimeout(() => el.remove(), error ? 12000 : 3500);
}

async function call(name, ...args) {
  const res = await window.pywebview.api[name](...args);
  if (!res.ok) throw new Error(res.error);
  return res.data;
}

// Page data cache: a page draws its last data at once, then again only when the fresh copy differs.
// draw() must check that its page is still open. Drop the key (delete CACHE[key]) after a change.
const CACHE = {};
async function cached(key, name, args, draw) {
  const old = CACHE[key];
  if (old) draw(old.data);
  let data;
  try { data = await call(name, ...args); } catch (e) { if (!old) toast(e.message, true); return; }
  const json = JSON.stringify(data);
  if (CACHE[key]?.json === json) return;
  CACHE[key] = { data, json };
  draw(data);
}

// Fill the cache in the background after start, so the first visit to each page is instant too.
function prefetch() {
  const v = S.default_php;
  [["certs", "certs", []], ["databases", "databases", []], ["logs", "logs", []], [`php:${v}`, "php_config", [v]]]
    .forEach(([k, n, a]) => CACHE[k] || cached(k, n, a, () => {}));
  if (!tzCache) call("php_timezones", v).then((t) => (tzCache ||= t)).catch(() => {});
}

// Run an API call with a busy button and an error toast. Returns the data or undefined.
async function act(btn, name, args = [], okMsg = "") {
  btn?.classList.add("busy");
  try {
    const data = await call(name, ...args);
    if (okMsg) toast(okMsg);
    return data ?? true;
  } catch (e) {
    toast(e.message, true);
  } finally {
    btn?.classList.remove("busy");
  }
}

async function refresh() {
  try {
    S = await call("state");
    if (S.synced?.length) toast(S.synced.join(", "));
  } catch (e) {
    main.innerHTML = `<div class="empty">${esc(e.message)}</div>`;
    return;
  }
  updateMailBadge(S.mail_count || 0);
  renderFoot();
  render();
}

function statusLabel(s) {
  return { running: "Running", stopped: "Stopped", "not-installed": "Not installed", starting: "Starting", stopping: "Stopping" }[s] || s;
}

function phpOptions(selected) {
  return S.php_versions.map((v) => `<option value="${v}" ${v === selected ? "selected" : ""}>PHP ${v}</option>`).join("");
}

// A site's PHP error log changed since it was last viewed on the Logs page (tracked in localStorage,
// since it's a per-viewer thing and not worth a round trip through the backend).
function hasUnreadLog(domain) {
  const mtime = PHP_LOG_MTIMES[domain];
  if (!mtime) return false;
  try { return mtime > Number(localStorage.getItem(`phplog-viewed-${domain}`) || 0); } catch { return false; }
}

function markLogViewed(domain) {
  try { localStorage.setItem(`phplog-viewed-${domain}`, String(PHP_LOG_MTIMES[domain] || Date.now() / 1000)); } catch { /* no storage */ }
}

function siteLink(site) {
  return site.urls.https || site.urls.http;
}

// Host plus port as the user must type it, e.g. localhost.test:8443
function siteHost(site) {
  return siteLink(site).replace(/^https?:\/\//, "").replace(/\/$/, "");
}

// Yes/no dialog. Resolves true when confirmed.
function confirmDialog(title, bodyHtml, okLabel = "OK") {
  return new Promise((resolve) => {
    let ok = false;
    openDialog(`<h3>${esc(title)}</h3><div class="muted">${bodyHtml}</div>
      <div class="actions"><button type="button" class="btn ghost" data-cancel>Cancel</button><button type="submit" class="btn primary">${esc(okLabel)}</button></div>`,
      async () => (ok = true));
    document.getElementById("dialog").addEventListener("close", () => resolve(ok), { once: true });
  });
}

// ------------------------------------------------------------------ background jobs (downloads, installs)

const seenJobs = new Set();
let jobsTimer = null;

async function startJob(btn, name, args = []) {
  if (await act(btn, name, args)) pollJobs();
}

async function pollJobs(first = false) {
  clearTimeout(jobsTimer);
  let list = [];
  try { list = await call("jobs"); } catch { return; }
  if (first) list.filter((j) => j.done).forEach((j) => seenJobs.add(j.id));   // finished before this window opened
  const box = document.getElementById("jobs");
  const active = list.filter((j) => !j.done);
  box.innerHTML = active.map((j) => `
    <div class="job card">
      <div class="row between"><b class="small">${esc(j.title)}</b>${j.progress == null ? "" : `<span class="faint small">${Math.round(j.progress * 100)}%</span>`}</div>
      <div class="muted small ellipsis">${esc(j.message)}</div>
      <div class="bar"><span style="width:${j.progress == null ? 100 : Math.round(j.progress * 100)}%" class="${j.progress == null ? "indeterminate" : ""}"></span></div>
    </div>`).join("");
  let finished = false;
  for (const j of list.filter((x) => x.done && !seenJobs.has(x.id))) {
    seenJobs.add(j.id);
    finished = true;
    toast(j.error ? `${j.title} failed:\n${j.error}` : `${j.title}: done`, !!j.error);
  }
  if (finished) refresh();
  if (active.length) jobsTimer = setTimeout(pollJobs, 800);
}

// ------------------------------------------------------------------ navigation

function go(v) {
  view = v;
  document.querySelectorAll(".side a").forEach((x) => x.classList.toggle("active", x.dataset.view === v));
  render();
}

document.querySelectorAll(".side a").forEach((a) => a.addEventListener("click", () => go(a.dataset.view)));

function render() {
  if (!S) return;
  if (!S.setup.binaries || !S.setup.initialized) return renderNotInstalled();
  ({ dashboard: renderDashboard, servers: renderServers, sites: renderSites, php: renderPhp, database: renderDatabase, certs: renderCerts,
    mail: renderMail, logs: renderLogs, settings: renderSettings })[view]();
}

function renderFoot() {
  const ver = document.getElementById("ver");
  if (S.version) { ver.textContent = `v${S.version}`; ver.hidden = false; }
  if (!S.services) return;
  document.getElementById("side-foot").innerHTML = ["apache", "mysql"].map((k) =>
    `<div class="row"><span class="dot ${S.services[k]}"></span>${k === "apache" ? "Apache" : "MySQL"}</div>`).join("") +
    `<div class="faint">${S.setup.admin ? "Administrator" : "Not elevated"}</div>`;
}

// Release notes from CHANGELOG.md, opened from the version under the logo.
async function changelogDialog() {
  let log;
  try { log = await call("changelog"); } catch (e) { return toast(e.message, true); }
  const md = (t) => esc(t).replace(/`([^`]+)`/g, '<span class="mono">$1</span>');
  const dlg = document.getElementById("dialog");
  dlg.classList.add("wide");
  dlg.addEventListener("close", () => dlg.classList.remove("wide"), { once: true });
  openDialog(`<h3>What's new</h3>
    <div class="changelog">${log.map((r, i) => `<section class="rel">
      <div class="row"><b>Version ${esc(r.version)}</b>${i === 0 ? `<span class="tag accent">current</span>` : ""}<span class="faint small">${esc(r.date)}</span></div>
      ${r.sections.map((sec) => `<div>${sec.title ? `<h4>${esc(sec.title)}</h4>` : ""}<ul>${sec.items.map((x) => `<li>${md(x)}</li>`).join("")}</ul></div>`).join("")}
    </section>`).join("") || `<div class="muted">No changelog found.</div>`}</div>
    <div class="actions"><button type="button" class="btn" data-cancel>Close</button></div>`, async () => true);
}

document.getElementById("ver").onclick = changelogDialog;

// About popup, three tabs: About (app + credit), License (full text), Components (bundled software).
async function aboutDialog() {
  let a;
  try { a = await call("about"); } catch (e) { return toast(e.message, true); }
  const dlg = document.getElementById("dialog");
  dlg.classList.add("wide");
  dlg.addEventListener("close", () => dlg.classList.remove("wide"), { once: true });
  const form = openDialog(`<h3>About DevStack</h3>
    <div class="tabs" role="tablist">
      <button type="button" class="on" data-tab="about">About</button>
      <button type="button" data-tab="license">License</button>
      <button type="button" data-tab="components">Components</button>
    </div>
    <div class="tab-body stack" data-body="about">
      <div class="about-head"><span class="logo">DS</span>
        <div><b>DevStack</b> <span class="muted">v${esc(a.version)}</span>
          <div class="muted small">Local Apache, PHP and MySQL server for Windows</div></div></div>
      <div>Many <span class="mono">.test</span> sites, each with its own PHP version and HTTPS, created in one click.
        Apache and MySQL run as Windows services, with phpMyAdmin, a local mail catcher and LAN sharing built in.</div>
      <div class="stack" style="gap:4px">
        <div>Created by <b>${esc(a.author)}</b></div>
        <div class="row small">${icon("external")}<a data-url="${esc(a.github)}">${esc(a.github.replace(/^https?:\/\//, ""))}</a></div>
      </div>
      <div class="faint small">Copyright &copy; ${esc(a.year)} ${esc(a.copyright)} &middot; MIT License</div>
    </div>
    <div class="tab-body" data-body="license" hidden>
      <pre class="license-text">${esc(a.license) || `<span class="faint">LICENSE file not found.</span>`}</pre>
    </div>
    <div class="tab-body" data-body="components" hidden>
      <table class="compact"><tbody>${a.components.map((c) => `<tr>
        <td>${esc(c.name)}</td>
        <td class="muted">${c.installed.length ? c.installed.map(esc).join(", ") : `<span class="faint">not installed</span>`}</td>
        <td class="r nowrap"><a data-url="${esc(c.url)}">${esc(c.license)}</a></td>
      </tr>`).join("")}</tbody></table>
    </div>
    <div class="actions"><button type="button" class="btn" data-cancel>Close</button></div>`, async () => true);
  form.querySelectorAll("[data-tab]").forEach((t) => (t.onclick = () => {
    form.querySelectorAll("[data-tab]").forEach((x) => x.classList.toggle("on", x === t));
    form.querySelectorAll("[data-body]").forEach((b) => (b.hidden = b.dataset.body !== t.dataset.tab));
  }));
  bindLinks(dlg);
}

document.getElementById("about-link").onclick = aboutDialog;

function renderNotInstalled() {
  main.innerHTML = `
    <div class="head"><div><h1>Welcome to DevStack</h1><div class="sub">Binaries or config are missing.</div></div></div>
    <div class="card pad stack">
      <div>Run <code>install.bat</code> in the DevStack folder once: it downloads Apache, PHP, MySQL and phpMyAdmin and creates the config.</div>
      <div class="muted small">Then reopen this window.</div>
      <div><button class="btn" onclick="refresh()">Check again</button></div>
    </div>`;
}

// ------------------------------------------------------------------ dashboard

function setupBanner() {
  const s = S.setup, todo = [];
  if (!s.ca_trusted) todo.push("Trust the local SSL certificate authority (browsers show HTTPS as secure)");
  if (!s.hosts_ok) todo.push("Add *.test domains to the Windows hosts file");
  if (S.run_mode === "service" && !s.services_installed) todo.push("Install Apache and MySQL as Windows services (auto-start at boot)");
  if (!todo.length) return "";
  return `<div class="banner"><div class="grow"><b>Finish setup</b><ul>${todo.map((t) => `<li>${t}</li>`).join("")}</ul>
    ${s.admin ? "" : `<div class="small faint" style="margin-top:6px">Needs administrator rights. Restart DevStack and accept the Windows prompt.</div>`}</div>
    <button class="btn hl" id="finish" ${s.admin ? "" : "disabled"}>Finish setup</button></div>`;
}

function portsBanner() {
  if (S.ports.http === 80 && S.ports.https === 443) return "";
  const key = `ports-note-${S.ports.http}-${S.ports.https}`;   // shows again if the ports change
  try { if (localStorage.getItem(key)) return ""; } catch { /* no storage */ }
  return `<div class="banner" id="ports-note"><div class="grow"><b>Running on test ports ${S.ports.http} / ${S.ports.https}</b>
    <div class="small muted" style="margin-top:4px">Open sites with the port, e.g. <span class="mono">${esc(S.sites[0].urls.https || S.sites[0].urls.http)}</span>.
    Plain <span class="mono">${esc(S.sites[0].domain)}</span> goes to port 80. Switch to 80 / 443 in Settings once nothing else uses them.</div></div>
    <button class="btn" data-dismiss="${key}">Got it</button></div>`;
}

function updateTag(k) {
  const u = S.updates?.[k];
  const has = k === "apache" ? u?.update : u?.available?.length;
  return has ? `<button class="tag accent linkish" data-go="servers" title="See Servers > Server versions">update available</button>` : "";
}

// Apache + MySQL cards with start/stop/restart, used on the dashboard and the Servers page.
function svcCards() {
  const svc = (k, name, detail, color) => `
    <div class="card svc">
      <span class="chip" style="--c:${color}">${icon(k === "apache" ? "server" : "db")}</span>
      <div class="grow"><div class="name">${name} ${updateTag(k)}</div>
        <div class="muted small"><span class="svc-state"><span class="dot ${S.services[k]}"></span>${statusLabel(S.services[k])}</span> · ${detail}</div></div>
      <div class="tools">${S.services[k] === "running"
        ? iconBtn("restart", "Restart", `data-svc="${k}" data-act="restart"`) + iconBtn("stop", "Stop", `data-svc="${k}" data-act="stop"`, "danger")
        : iconBtn("play", "Start", `data-svc="${k}" data-act="start" ${S.services[k] === "not-installed" ? "disabled" : ""}`, "go")}</div>
    </div>`;
  return `<div class="grid">
      ${svc("apache", `Apache ${esc(S.versions.apache || "2.4")}`, `ports ${S.ports.http} / ${S.ports.https}`, "var(--s1)")}
      ${svc("mysql", `MySQL ${esc(S.versions.mysql || "")}`, `port ${S.ports.mysql}`, "var(--s3)")}
    </div>`;
}

function bindSvc() {
  main.querySelectorAll("[data-svc]").forEach((b) => (b.onclick = async () => {
    if (await act(b, "service", [b.dataset.svc, b.dataset.act])) refresh();
  }));
  const all = document.getElementById("all");
  if (all) all.onclick = async () => {
    await act(all, "all_services", [all.dataset.running ? "stop" : "start"]);
    refresh();
  };
}

function allButton() {
  const on = S.services.apache === "running" && S.services.mysql === "running";
  return `<button class="btn ${on ? "" : "hl"}" id="all" ${on ? "data-running=1" : ""}>${icon(on ? "stop" : "play")}${on ? "Stop all" : "Start all"}</button>`;
}

function renderDashboard() {
  const def = S.sites[0];
  const phpUpdates = (S.updates?.php || []).filter((r) => r.state === "update").length;
  const link = (ic, color, label, value, attr) => `
    <a class="card link-tile" ${attr}><span class="chip" style="--c:${color}">${icon(ic)}</span>
      <span class="grow"><span class="muted small">${label}</span><b class="ellipsis">${value}</b></span></a>`;
  main.innerHTML = `
    <div class="head">
      <div><h1>Dashboard</h1><div class="sub">${S.run_mode === "service" ? "Windows services, start automatically with Windows" : "Background processes, start from this app"}</div></div>
      ${allButton()}
    </div>
    ${setupBanner()}
    ${portsBanner()}
    <div class="dash">
      <div class="dash-main">
        ${svcCards()}
        ${phpUpdates ? `<div class="note small">PHP updates are available for ${phpUpdates} installed branch${phpUpdates > 1 ? "es" : ""}. <a data-go="php" data-php="install">See PHP versions</a></div>` : ""}
        <div id="stats">${statsHtml()}</div>
        <h2>Quick links</h2>
        <div class="grid links">
          ${link("globe", "var(--accent-text)", "Default site", esc(siteHost(def)), `data-url="${esc(siteLink(def))}"`)}
          ${link("pma", "var(--s2)", "Database admin", "phpMyAdmin", `data-url="${esc(S.pma_url)}"`)}
          ${link("folder", "var(--warn)", "Sites folder", `<span class="mono">${esc(S.www)}</span>`, `data-path="${esc(S.www)}" title="${esc(S.www)}"`)}
        </div>
        <h2 class="row between">Sites ${S.sites.length > 12 ? `<a class="small" data-go="sites" style="font-weight:400">All ${S.sites.length} sites</a>` : ""}</h2>
        ${siteCards(S.sites.slice(0, 12))}
      </div>
      <aside class="card pad dash-side">
        <h2 class="row between">Activity <span class="live-pill"><span class="dot running"></span>live</span></h2>
        <div id="activity"></div>
      </aside>
    </div>`;

  bindSvc();
  const fin = document.getElementById("finish");
  if (fin) fin.onclick = async () => { if (await act(fin, "finish_setup", [], "Setup complete")) refresh(); };
  main.querySelectorAll("[data-dismiss]").forEach((b) => (b.onclick = () => {
    try { localStorage.setItem(b.dataset.dismiss, "1"); } catch { /* no storage */ }
    b.closest(".banner").remove();
  }));
  bindLinks();
  loadStats();
  cached("site_icons", "site_icons", [], drawSiteIcons);
  drawActivity();
  pollActivity();
}

// Dashboard site cards: favicon (filled in by drawSiteIcons) or a globe, name, HTTPS badge, PHP version. Click = open.
function siteCards(sites) {
  if (!sites.length) return `<div class="card empty">No sites yet</div>`;
  return `<div class="site-cards">${sites.map((s) => `
    <a class="card site-card" data-url="${esc(siteLink(s))}" title="${esc(siteLink(s))}">
      <span class="fav" data-fav="${esc(s.name)}">${icon("globe")}</span>
      <span class="sc-name"><b class="ellipsis">${esc(s.name)}</b>${s.ssl ? `<span class="sc-ssl" title="HTTPS">${icon("shield")}</span>` : ""}</span>
      <span class="tag">PHP ${esc(s.php)}</span>
    </a>`).join("")}</div>`;
}

function drawSiteIcons(icons) {
  if (view !== "dashboard") return;
  main.querySelectorAll("[data-fav]").forEach((el) => {
    const uri = icons[el.dataset.fav];
    if (uri) el.innerHTML = `<img src="${esc(uri)}" alt="">`;
  });
}

async function loadStats(refreshSizes = false) {
  try { ST = await call("stats", refreshSizes); } catch { return; }
  const box = document.getElementById("stats");
  if (box) { box.innerHTML = statsHtml(); bindLinks(box); }
  const st = document.getElementById("storage");
  if (st) { st.innerHTML = storageHtml(); bindLinks(st); bindStorage(); }
  fillDbCells();
  // Folder sizes are counted in the background the first time; pick them up when ready.
  const v = view;
  if (ST.sizes.counting && ["dashboard", "sites", "settings"].includes(v)) setTimeout(() => view === v && loadStats(), 2500);
}

function statsHtml() {
  const cell = (label, big, sub) => `
    <div class="ov-cell"><div class="muted small">${label}</div><div class="big">${big}</div><div class="muted small">${sub}</div></div>`;
  if (!ST) return `<h2>Overview</h2><div class="card pad overview"><div class="faint small">…</div></div>`;
  const sz = ST.sizes, d = ST.disk;
  const pct = Math.round(((d.total - d.free) / d.total) * 100);
  const total = sz.projects == null ? null : sz.projects + sz.mysql + sz.logs + sz.bin;
  const phps = new Set(S.sites.map((s) => s.php)).size;
  const parts = [["Sites", sz.projects, "var(--accent-text)"], ["MySQL", sz.mysql, "var(--s3)"],
    ["Programs", sz.bin, "var(--s2)"], ["Logs", sz.logs, "var(--warn)"]];
  const storage = total ? `
      <div class="ov-storage">
        <div class="ov-bar">${parts.map(([, n, c]) => `<span style="width:${(n / total) * 100}%;background:${c}"></span>`).join("")}</div>
        <div class="ov-legend small">${parts.map(([l, n, c]) => `<span><i class="sw" style="background:${c}"></i>${l} <b>${fmtBytes(n)}</b></span>`).join("")}
          ${sz.logs > 0 ? `<a data-go="logs">Clear logs</a>` : ""}</div>
      </div>` : "";
  return `
    <h2>Overview</h2>
    <div class="card pad overview">
      <div class="ov-cells">
        ${cell("Sites", ST.sites, `${ST.https_sites} with HTTPS · ${phps} PHP version${phps === 1 ? "" : "s"}`)}
        ${cell("Databases", ST.databases, `${fmtBytes(ST.db_size)} of data · <a data-go="database">list</a>`)}
        ${cell("Storage used", fmtBytes(total), `sites, MySQL, programs, logs · <a data-go="settings" data-anchor="storage-h">details</a>`)}
        ${cell(`Drive ${esc(d.drive)}`, `${fmtBytes(d.free)} <span class="unit">free</span>`,
          `<div class="bar ${pct > 90 ? "bad" : ""}"><span style="width:${pct}%"></span></div><span class="faint">${pct}% of ${fmtBytes(d.total)} used</span>`)}
      </div>${storage}
    </div>`;
}

// ------------------------------------------------------------------ live activity: meters + history chart

const SERIES = [["apache", "Apache"], ["php", "PHP"], ["mysql", "MySQL"]];   // colors --s1..--s3, fixed per server
const fmtPct = (x) => `${x < 10 ? x.toFixed(1) : Math.round(x)}%`;
const fmtRate = (b) => `${fmtBytes(b)}/s`;
const METRICS = {     // col = first column of the metric in a history row [t, cpu x3, mem x3, io x3]
  cpu: { label: "CPU", col: 1, fmt: fmtPct },
  mem: { label: "Memory", col: 4, fmt: fmtBytes },
  io: { label: "Disk I/O", col: 7, fmt: fmtRate },
};
const RANGES = [[900, "15 min"], [3600, "1 h"], [10800, "3 h"]];
const A = { fine: [], coarse: [], now: null, ram: 0, off: false, metric: "cpu", range: 900, hoverX: null };
let actTimer = null;
try {
  A.metric = METRICS[localStorage.getItem("act-metric")] ? localStorage.getItem("act-metric") : "cpu";
  A.range = RANGES.some(([r]) => r === +localStorage.getItem("act-range")) ? +localStorage.getItem("act-range") : 900;
} catch { /* no storage */ }

async function pollActivity() {
  clearTimeout(actTimer);
  if (view !== "dashboard") return;
  if (!document.hidden) {
    try {
      const d = await call("activity", A.fine.at(-1)?.[0] || 0, A.coarse.at(-1)?.[0] || 0);
      A.off = !d;
      if (d) {
        A.now = d.now;
        A.ram = d.ram;
        A.fine = A.fine.concat(d.fine).slice(-900);
        A.coarse = A.coarse.concat(d.coarse).slice(-1080);
      }
    } catch { /* keep the last numbers */ }
    if (view !== "dashboard") return;
    drawActivity();
  }
  actTimer = setTimeout(pollActivity, 1000);
}

// Half-circle meter; pathLength=100 so the dash length is the percentage.
const ARC = "M 14 64 A 46 46 0 0 1 106 64";
const gaugeSvg = (id, color) => `
  <svg class="gauge" viewBox="0 0 120 74" aria-hidden="true">
    <path d="${ARC}" pathLength="100" class="g-track" style="stroke:${color}"/>
    <path d="${ARC}" pathLength="100" class="g-val" id="${id}-arc" style="stroke:${color}"/>
    <text x="60" y="58" class="g-num" id="${id}-num">–</text><text x="60" y="72" class="g-unit" id="${id}-unit"></text>
  </svg>`;

function activitySkeleton() {
  const seg = (id, items, cur) => `<div class="seg" id="${id}">${items.map(([v, l]) =>
    `<button type="button" data-v="${v}" class="${String(v) === String(cur) ? "on" : ""}">${l}</button>`).join("")}</div>`;
  return `
    <div class="grid gauge-grid">
      ${SERIES.map(([k, name], i) => `
        <div class="gauge-card">
          <div class="row between small"><span class="muted"><i class="sw" style="background:var(--s${i + 1})"></i>${name}</span><span class="faint ellipsis" id="g-${k}-meta"></span></div>
          ${gaugeSvg(`g-${k}`, `var(--s${i + 1})`)}
          <div class="meter small"><span class="muted">RAM</span><div class="bar"><span id="g-${k}-ram" style="background:var(--s${i + 1})"></span></div><span id="g-${k}-mem" class="num"></span></div>
        </div>`).join("")}
      <div class="gauge-card">
        <div class="row between small"><span class="muted">Disk I/O</span><span class="faint">log</span></div>
        ${gaugeSvg("g-io", "var(--accent)")}
        <div class="meter small muted" id="g-io-rw"></div>
      </div>
    </div>
    <div class="chart-card">
      <div class="chart-head">${seg("act-metric", Object.entries(METRICS).map(([k, m]) => [k, m.label]), A.metric)}${seg("act-range", RANGES, A.range)}</div>
      <div class="legend small" id="act-legend"></div>
      <div class="chart" id="act-chart"><svg></svg><div class="tip" hidden></div></div>
    </div>`;
}

function drawActivity() {
  const box = document.getElementById("activity");
  if (!box) return;
  if (A.off) {
    box.innerHTML = `<div class="muted small">Install psutil for live numbers: <span class="mono">pip install psutil</span></div>`;
    return;
  }
  if (!box.querySelector(".gauge-grid")) {
    box.innerHTML = activitySkeleton();
    box.querySelectorAll(".seg").forEach((seg) => seg.querySelectorAll("button").forEach((b) => (b.onclick = () => {
      const key = seg.id === "act-metric" ? "metric" : "range";
      A[key] = key === "range" ? +b.dataset.v : b.dataset.v;
      try { localStorage.setItem(seg.id, b.dataset.v); } catch { /* no storage */ }
      seg.querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b));
      drawChart();
    })));
    const chart = document.getElementById("act-chart");
    chart.onmousemove = (e) => { A.hoverX = e.clientX - chart.getBoundingClientRect().left; drawChart(); };
    chart.onmouseleave = () => { A.hoverX = null; drawChart(); };
  }
  drawGauges();
  drawChart();
}

function setGauge(id, frac, num, unit) {
  document.getElementById(`${id}-arc`).style.strokeDasharray = `${Math.max(0, Math.min(1, frac)) * 100} 100`;
  document.getElementById(`${id}-num`).textContent = num;
  document.getElementById(`${id}-unit`).textContent = unit;
}

function drawGauges() {
  const N = A.now;
  if (!N) return;
  let read = 0, write = 0;
  for (const [k] of SERIES) {
    const x = N[k], on = x.count > 0;
    read += x.read;
    write += x.write;
    setGauge(`g-${k}`, x.cpu / 100, on ? fmtPct(x.cpu) : "off", on ? "CPU" : "not running");
    document.getElementById(`g-${k}-meta`).textContent = !on ? "" : k === "php" ? `${x.count} process${x.count > 1 ? "es" : ""}` : `up ${fmtUptime(x.since)}`;
    document.getElementById(`g-${k}-ram`).style.width = `${A.ram ? Math.min(100, (x.mem / A.ram) * 100) : 0}%`;
    document.getElementById(`g-${k}-mem`).textContent = on ? fmtBytes(x.mem) : "–";
  }
  // Log scale from 1 KB/s to 100 MB/s: small bursts stay visible next to big imports.
  const io = read + write;
  setGauge("g-io", (Math.log10(Math.max(io, 1)) - 3) / 5, fmtRate(io), "all servers");
  document.getElementById("g-io-rw").textContent = `read ${fmtRate(read)} · write ${fmtRate(write)}`;
}

// Tick values for 0..max: 4-5 round steps (binary units for bytes).
function niceTicks(max, metric) {
  const floor = { cpu: 1, mem: 1024 ** 2, io: 1024 }[metric];
  max = Math.max(max, floor);
  const base = metric === "cpu" ? 1 : 1024 ** Math.floor(Math.log(max) / Math.log(1024));
  const raw = max / base / 4, mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].find((k) => k * mag >= raw) * mag * base;
  const out = [];
  for (let v = 0; v < max + step * 0.001; v += step) out.push(v);
  if (out.at(-1) < max) out.push(out.at(-1) + step);
  return out;
}

const hhmm = (t) => new Date(t * 1000).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });

function drawChart() {
  const el = document.getElementById("act-chart");
  if (!el) return;
  const svg = el.querySelector("svg"), tip = el.querySelector(".tip");
  const m = METRICS[A.metric], fine = A.range <= 900, rows = fine ? A.fine : A.coarse;
  const W = el.clientWidth, H = 200, L = 64, R = 10, T = 10, B = 22;
  const tEnd = A.fine.at(-1)?.[0] ?? Date.now() / 1000, tStart = tEnd - A.range;
  const vis = rows.filter((r) => r[0] >= tStart);
  let max = 0;
  for (const r of vis) for (let i = 0; i < 3; i++) max = Math.max(max, r[m.col + i]);
  const ticks = niceTicks(max, A.metric), top = ticks.at(-1);
  const x = (t) => L + ((t - tStart) / A.range) * (W - L - R);
  const y = (v) => H - B - (v / top) * (H - T - B);
  const maxGap = (fine ? 1 : 10) * 3.5;   // longer gaps (sampler paused) break the line

  let g = ticks.map((v) => `<line class="grid" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/>
    <text class="axis" x="${L - 8}" y="${y(v) + 4}" text-anchor="end">${esc(A.metric === "cpu" ? `${+v.toFixed(2)}%` : m.fmt(v))}</text>`).join("");
  const tStep = { 900: 300, 3600: 900, 10800: 1800 }[A.range];
  for (let t = Math.ceil(tStart / tStep) * tStep; t <= tEnd; t += tStep) {
    g += `<text class="axis" x="${x(t)}" y="${H - 5}" text-anchor="middle">${hhmm(t)}</text>`;
  }
  SERIES.forEach((_, i) => {
    let d = "", prev = null;
    for (const r of vis) {
      d += `${prev && r[0] - prev <= maxGap ? "L" : "M"}${x(r[0]).toFixed(1)} ${y(r[m.col + i]).toFixed(1)}`;
      prev = r[0];
    }
    g += `<path class="line" d="${d}" style="stroke:var(--s${i + 1})"/>`;
  });
  if (vis.length < 2) {
    g += `<text class="axis" x="${(L + W) / 2}" y="${H / 2}" text-anchor="middle">${fine ? "Collecting samples…" : "The first 10-second averages appear shortly…"}</text>`;
  }

  // Hover: crosshair at the nearest sample, a dot per series and a tooltip.
  tip.hidden = true;
  if (A.hoverX != null && vis.length) {
    const t = tStart + ((A.hoverX - L) / (W - L - R)) * A.range;
    const r = vis.reduce((a, b) => (Math.abs(b[0] - t) < Math.abs(a[0] - t) ? b : a));
    const cx = x(r[0]);
    g += `<line class="cross" x1="${cx}" x2="${cx}" y1="${T}" y2="${H - B}"/>`;
    SERIES.forEach((_, i) => (g += `<circle class="pt" cx="${cx}" cy="${y(r[m.col + i])}" r="4" style="fill:var(--s${i + 1})"/>`));
    tip.innerHTML = `<div class="faint">${new Date(r[0] * 1000).toLocaleTimeString()}${fine ? "" : " · 10 s average"}</div>` +
      SERIES.map(([, name], i) => `<div class="row between"><span><i class="sw" style="background:var(--s${i + 1})"></i>${name}</span><b>${esc(m.fmt(r[m.col + i]))}</b></div>`).join("");
    tip.hidden = false;
    tip.style.left = `${cx > W / 2 ? cx - tip.offsetWidth - 12 : cx + 12}px`;
  }
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("height", H);
  svg.innerHTML = g;

  const last = A.fine.at(-1);
  document.getElementById("act-legend").innerHTML = SERIES.map(([, name], i) =>
    `<span><i class="sw" style="background:var(--s${i + 1})"></i>${name} <b>${last ? esc(m.fmt(last[m.col + i])) : "–"}</b></span>`).join("");
}

// Fill the Database column of a sites table from the last stats.
function fillDbCells() {
  if (!ST) return;
  main.querySelectorAll("[data-dbcell]").forEach((td) => {
    const names = ST.site_dbs[td.dataset.dbcell] || [];
    td.innerHTML = names.length
      ? names.map((n) => `<span class="mono">${esc(n)}</span>` + ("dbsize" in td.dataset ? ` <span class="faint small">${fmtBytes(ST.db_sizes[n])}</span>` : "")).join("<br>")
      : `<span class="faint">–</span>`;
  });
  main.querySelectorAll("[data-sizecell]").forEach((td) => {
    const n = ST.sizes.sites?.[td.dataset.sizecell];
    td.innerHTML = n == null ? `<span class="faint">…</span>` : fmtBytes(n);
  });
}

function bindLinks(root = main) {
  root.querySelectorAll("[data-url]").forEach((a) => (a.onclick = () => call("open_url", a.dataset.url)));
  root.querySelectorAll("[data-path]").forEach((a) => (a.onclick = () => call("open_path", a.dataset.path)));
  root.querySelectorAll("[data-go]").forEach((a) => (a.onclick = () => {
    if (a.dataset.php) phpVer = a.dataset.php;
    go(a.dataset.go);
    if (a.dataset.anchor) document.getElementById(a.dataset.anchor)?.scrollIntoView({ block: "start" });
  }));
}

// ------------------------------------------------------------------ sites

// Sites table. actions=false is the short version on the dashboard (no size, date or tools).
function sitesTable(sites, actions = true) {
  if (!sites.length) return `<div class="card empty">No sites yet</div>`;
  return `<div class="card"><table>
    <thead><tr><th>Site</th><th>PHP</th><th>Database</th><th class="c">SSL</th>${actions ? `<th class="r">Size</th><th>Created</th><th></th>` : ""}</tr></thead>
    <tbody>${sites.map((s) => `
      <tr>
        <td><a data-url="${esc(siteLink(s))}">${esc(siteHost(s))}</a> ${s.name === "localhost" ? `<span class="tag accent">default</span>` : ""}
            ${s.lan_port ? `<span class="tag" title="Shared on the LAN">LAN :${s.lan_port}</span>` : ""}
            ${actions && hasUnreadLog(s.domain) ? `<span class="dot stopped" title="New PHP errors" data-errdot="${esc(s.domain)}" style="cursor:pointer"></span>` : ""}
            ${actions ? `<a data-path="${esc(s.root)}" class="mono ellipsis site-path" title="Open ${esc(s.root)}">${esc(s.root)}</a>` : ""}</td>
        <td>${actions ? `<select class="php-pick" data-site="${esc(s.name)}" style="width:auto">${phpOptions(s.php)}</select>` : `<span class="tag">${esc(s.php)}</span>`}</td>
        <td data-dbcell="${esc(s.name)}" ${actions ? "data-dbsize" : ""}><span class="faint">…</span></td>
        <td class="c">${s.ssl ? `<span class="yes" title="HTTPS on">${icon("check")}</span>` : `<span class="faint" title="HTTPS off">–</span>`}</td>
        ${actions ? `<td class="r nowrap num" data-sizecell="${esc(s.name)}"><span class="faint">…</span></td>
          <td class="muted small nowrap">${esc(fmtDate(s.created))}</td>
          <td class="r"><div class="tools">
            ${iconBtn("terminal", "Terminal here", `data-term="${esc(s.name)}"`)}
            ${iconBtn("share", s.lan_port ? "Shared on LAN" : "Share on LAN", `data-lan="${esc(s.name)}"`, s.lan_port ? "on" : "")}
            ${iconBtn("copy", "Clone", `data-clone="${esc(s.name)}"`)}
            ${iconBtn("archive", "Export to .zip", `data-siteexport="${esc(s.name)}"`)}
            ${iconBtn("edit", "Edit", `data-edit="${esc(s.name)}"`)}
            ${s.name === "localhost" ? "" : iconBtn("trash", "Delete", `data-del="${esc(s.name)}"`, "danger")}</div></td>` : ""}
      </tr>`).join("")}
    </tbody></table></div>`;
}

function renderSites() {
  main.innerHTML = `
    <div class="head">
      <div><h1>Sites</h1><div class="sub">Each site gets its own .test domain, HTTPS certificate and PHP version.</div></div>
      <div class="row"><button class="btn" id="import">Add existing folders</button><button class="btn" id="importzip">Import from .zip</button>
        <button class="btn primary" id="add">+ New site</button></div>
    </div>
    ${sitesTable(S.sites)}`;
  document.getElementById("add").onclick = () => siteDialog();
  document.getElementById("import").onclick = () => importDialog();
  document.getElementById("importzip").onclick = () => importZipDialog();
  main.querySelectorAll(".php-pick").forEach((sel) => (sel.onchange = async () => {
    sel.disabled = true;
    if (await act(null, "update_site", [sel.dataset.site, { php: sel.value }], `${sel.dataset.site}.test now uses PHP ${sel.value}`)) await refresh();
    else { sel.disabled = false; refresh(); }
  }));
  main.querySelectorAll("[data-edit]").forEach((b) => (b.onclick = () => siteDialog(S.sites.find((s) => s.name === b.dataset.edit))));
  main.querySelectorAll("[data-del]").forEach((b) => (b.onclick = () => deleteDialog(S.sites.find((s) => s.name === b.dataset.del))));
  main.querySelectorAll("[data-term]").forEach((b) => (b.onclick = () => act(b, "open_terminal", [b.dataset.term])));
  main.querySelectorAll("[data-errdot]").forEach((b) => (b.onclick = () => {
    markLogViewed(b.dataset.errdot);
    logFile = `sites/${b.dataset.errdot}-php.log`;
    go("logs");
  }));
  main.querySelectorAll("[data-lan]").forEach((b) => (b.onclick = () => lanDialog(b.dataset.lan)));
  main.querySelectorAll("[data-clone]").forEach((b) => (b.onclick = () => cloneDialog(b.dataset.clone)));
  main.querySelectorAll("[data-siteexport]").forEach((b) => (b.onclick = () => exportSiteDialog(b.dataset.siteexport)));
  bindLinks();
  fillDbCells();
  loadStats();
}

function openDialog(html, onSubmit) {
  const dlg = document.getElementById("dialog");
  const form = document.getElementById("dialog-form");
  form.innerHTML = html;
  form.onsubmit = async (e) => {
    e.preventDefault();
    const submit = form.querySelector("[type=submit]");
    if (await onSubmit(form, submit)) dlg.close();
  };
  form.querySelector("[data-cancel]").onclick = () => dlg.close();
  dlg.showModal();
  form.querySelector("input:not([type=checkbox]), select")?.focus();
  return form;
}

function siteDialog(site = null) {
  const editing = !!site;
  const form = openDialog(`
    <h3>${editing ? `Edit ${esc(site.domain)}` : "New site"}</h3>
    <label class="field">Domain
      <div class="input-affix"><input type="text" name="name" required placeholder="myshop" value="${esc(site?.name ?? "")}" ${editing ? "disabled" : ""} autocomplete="off" spellcheck="false"><span>.test</span></div>
    </label>
    <label class="field">Folder
      <div class="row"><input type="text" name="root" placeholder="${esc(S.www)}/<name>" value="${esc(site?.root ?? "")}" spellcheck="false"><button type="button" class="btn" id="browse">Browse</button></div>
    </label>
    <label class="field">PHP version<select name="php">${phpOptions(site?.php ?? S.default_php)}</select></label>
    <label class="field">Database<select name="db"><option value="auto">Loading…</option></select>
      <span class="faint small">${editing ? "Shown on the dashboard. " : ""}Auto-detect reads the project's config files (.env, config.php …).${editing ? "" : " A new database needs MySQL running."}</span></label>
    <label class="check"><input type="checkbox" name="ssl" ${site?.ssl ?? true ? "checked" : ""}> HTTPS with a local certificate</label>
    ${editing ? `<label class="field">Aliases (one per line)
      <textarea name="aliases" rows="2" class="mono" spellcheck="false" placeholder="admin.${esc(site.domain)}&#10;*.${esc(site.domain)}">${esc((site.aliases || []).join("\n"))}</textarea></label>
      <div class="faint small">A wildcard alias can't be added to the hosts file - only plain aliases resolve without extra DNS setup.</div>
    <label class="field">Extra Apache directives
      <textarea name="apache_extra" rows="3" class="mono" spellcheck="false" placeholder='Header set X-Frame-Options "SAMEORIGIN"'>${esc(site.apache_extra || "")}</textarea></label>` : ""}
    <div class="actions"><button type="button" class="btn ghost" data-cancel>Cancel</button><button type="submit" class="btn primary">${editing ? "Save" : "Create site"}</button></div>`,
    async (f, btn) => {
      const root = f.root.value.trim();
      const changes = { root, php: f.php.value, ssl: f.ssl.checked };
      const db = f.db.dataset.loaded ? dbChoice(f.db.value) : null;
      if (editing && f.db.dataset.loaded) changes.db = db;
      if (editing) {
        changes.aliases = f.aliases.value.split("\n").map((s) => s.trim()).filter(Boolean);
        changes.apache_extra = f.apache_extra.value;
        const ok = await act(btn, "update_site", [site.name, changes], "Saved");
        if (ok) { refresh(); showWarnings(ok); }
        return !!ok;
      }
      const createDb = f.db.value === "new";
      const data = await act(btn, "create_site", [f.name.value, root, f.php.value, f.ssl.checked, createDb, createDb ? null : db],
        `Created ${f.name.value.replace(/\.test$/, "")}.test`);
      if (!data) return false;
      refresh();
      showWarnings(data);
      if (data.db_credentials?.user) dbCredentialsDialog(data.db_credentials);
      return true;
    });
  form.querySelector("#browse").onclick = async () => {
    const p = await act(null, "pick_folder", [form.root.value]);
    if (p) form.root.value = p;
  };
  call("databases").then((d) => {
    const found = editing ? (ST?.site_dbs?.[site.name] || []).join(", ") : "";
    form.db.innerHTML = dbOptions(d.databases, site?.db, found, !editing);
    form.db.dataset.loaded = "1";
  }).catch((e) => toast(e.message, true));
}

// <option>s for a site's database: auto-detect / none / (create new) / every existing database.
// cur: the site's `db` (undefined/null = auto, "" = none, else a name).
function dbOptions(dbs, cur, found = "", withNew = false) {
  return `<option value="auto">Auto-detect${cur == null && found ? ` (${esc(found)})` : ""}</option>` +
    `<option value="none" ${cur === "" ? "selected" : ""}>No database</option>` +
    (withNew ? `<option value="new">+ Create a new database and user</option>` : "") +
    dbs.map((x) => `<option value="${esc(x.name)}" ${cur === x.name ? "selected" : ""}>${esc(x.name)} (${fmtBytes(x.size)})</option>`).join("");
}

// A dbOptions() value -> the site's `db` field.
const dbChoice = (v) => (v === "auto" || v === "new" ? null : v === "none" ? "" : v);

// create_site / update_site / import_sites return `warnings` (e.g. a wildcard alias that catches another site).
function showWarnings(data) {
  (data?.warnings || []).forEach((w) => toast(w, true));
}

// LAN sharing dialog, opened from its own row icon in the sites table.
function lanDialog(name) {
  const site = S.sites.find((s) => s.name === name);
  if (!site) return;
  if (!site.lan_port) {
    openDialog(`
      <h3>Share ${esc(site.domain)} on LAN</h3>
      <div class="muted small">Other devices on your network (phone, laptop…) can open this site over plain HTTP, on its own port. Apps with a hardcoded <span class="mono">.test</span> URL may not work over it.</div>
      <div class="actions"><button type="button" class="btn ghost" data-cancel>Cancel</button><button type="submit" class="btn primary">Create share</button></div>`,
      async (f, btn) => {
        const updated = await act(btn, "set_site_lan", [name, true], `${site.domain} shared on LAN`);
        if (!updated) return false;
        refresh().then(() => lanDialog(name));   // reopen with the URL + QR code
        return true;
      });
    return;
  }
  const form = openDialog(`
    <h3>${esc(site.domain)} on LAN</h3>
    <div id="lan-info"></div>
    <div class="actions"><button type="button" class="btn ghost danger" id="lan-remove">Remove share</button><button type="button" class="btn" data-cancel>Close</button></div>`,
    async () => true);
  drawLanInfo(form.querySelector("#lan-info"), site);
  form.querySelector("#lan-remove").onclick = async (e) => {
    if (await act(e.target, "set_site_lan", [name, false], `${site.domain} no longer shared`)) { document.getElementById("dialog").close(); refresh(); }
  };
}

// URL + QR code + firewall button for a shared site, or nothing if it isn't shared.
async function drawLanInfo(box, site) {
  if (!box) return;
  if (!site.lan_port) { box.innerHTML = ""; return; }
  box.innerHTML = `<div class="muted small">Loading…</div>`;
  let ip;
  try { ip = (await call("lan_info")).ip; } catch { ip = null; }
  if (!box.isConnected) return;
  if (!ip) { box.innerHTML = `<div class="muted small">Could not detect a LAN IP address.</div>`; return; }
  const url = `http://${ip}:${site.lan_port}/`;
  box.innerHTML = `
    <div class="muted small">Open on another device on your network: <a data-url="${esc(url)}" class="mono">${esc(url)}</a></div>
    <div id="lan-qr"></div>
    <div class="faint small">Apps with a hardcoded <span class="mono">.test</span> URL (e.g. WordPress' siteurl) may redirect back to it.</div>
    <div><button type="button" class="btn sm" id="lan-fw">Allow in firewall</button></div>`;
  bindLinks(box);
  try {
    const qr = qrcode(0, "M");
    qr.addData(url);
    qr.make();
    document.getElementById("lan-qr").innerHTML = qr.createSvgTag(4);
  } catch { /* qrcode lib missing - the link above still works */ }
  document.getElementById("lan-fw").onclick = (e) => act(e.target, "allow_lan_firewall", [site.lan_port], "Firewall rule added");
}

// Shown right after a database + user is created: a copyable box with the one-time password.
function dbCredentialsDialog(c) {
  const lines = [`Database: ${c.database}`, c.user ? `User: ${c.user}` : "", c.password ? `Password: ${c.password}` : "",
    c.host ? `Host: ${c.host}:${c.port}` : ""].filter(Boolean).join("\n");
  openDialog(`
    <h3>Database created</h3>
    <div class="muted small">Save this now - the password is not stored anywhere and won't be shown again.</div>
    <textarea readonly rows="4" class="mono" style="width:100%;resize:vertical" id="creds-box">${esc(lines)}</textarea>
    <div class="actions"><button type="button" class="btn" id="copy-creds">Copy</button><button type="button" class="btn" data-cancel>Close</button></div>`,
    async () => true);
  document.getElementById("copy-creds").onclick = async () => {
    try { await navigator.clipboard.writeText(document.getElementById("creds-box").value); toast("Copied"); }
    catch { document.getElementById("creds-box").select(); toast("Select and copy manually", true); }
  };
}

function createDatabaseDialog() {
  const form = openDialog(`
    <h3>Create database</h3>
    <label class="field">Name<input type="text" name="name" required placeholder="myapp" autocomplete="off" spellcheck="false"></label>
    <label class="field">User (optional)<input type="text" name="user" placeholder="leave blank for no user" autocomplete="off" spellcheck="false"></label>
    <div class="faint small">Letters, numbers and underscore only. A random password is generated if you add a user.</div>
    <div class="actions"><button type="button" class="btn ghost" data-cancel>Cancel</button><button type="submit" class="btn primary">Create</button></div>`,
    async (f, btn) => {
      const data = await act(btn, "create_database", [f.name.value.trim(), f.user.value.trim()], "Database created");
      if (!data) return false;
      loadDatabases(true);
      if (data.user) dbCredentialsDialog(data);
      return true;
    });
}

function importSqlDialog() {
  const form = openDialog(`
    <h3>Import .sql</h3>
    <div class="muted small">Pick a .sql or .sql.gz file next, then choose which database to import it into.</div>
    <label class="field">Database<input type="text" name="db" placeholder="existing or new name" autocomplete="off" spellcheck="false"></label>
    <label class="check"><input type="checkbox" name="create" checked> Create the database if it doesn't exist</label>
    <div class="actions"><button type="button" class="btn ghost" data-cancel>Cancel</button><button type="submit" class="btn primary">Choose file and import</button></div>`,
    async (f, btn) => {
      if (!f.db.value.trim()) return toast("Enter a database name", true), false;
      if (await act(btn, "import_sql", [f.db.value.trim(), f.create.checked])) pollJobs();
      return true;
    });
}

function importDialog() {
  let found = [];
  const form = openDialog(`
    <h3>Add existing folders</h3>
    <div class="muted small">Every subfolder becomes a site. Pick which folder inside it is served (e.g. <span class="mono">web/production</span>) and which existing database it uses.</div>
    <label class="field">Folder with projects
      <div class="row"><input type="text" name="base" value="${esc(S.www)}" spellcheck="false"><button type="button" class="btn" id="browse">Browse</button><button type="button" class="btn" id="scan">Scan</button></div>
    </label>
    <label class="field">PHP version for all<select name="php">${phpOptions(S.default_php)}</select></label>
    <label class="check"><input type="checkbox" name="ssl" checked> HTTPS with a local certificate</label>
    <div id="found" class="import-list"></div>
    <div class="actions"><button type="button" class="btn ghost" data-cancel>Cancel</button><button type="submit" class="btn primary" disabled>Add sites</button></div>`,
    async (f, btn) => {
      const items = [...f.querySelectorAll("#found tbody tr")].filter((tr) => tr.querySelector(".pick").checked).map((tr) => ({
        name: tr.querySelector(".nm").value, root: tr.querySelector(".rt").value, php: tr.querySelector(".pv").value,
        db: dbChoice(tr.querySelector(".db").value),
      }));
      if (!items.length) return toast("Nothing selected", true), false;
      const ok = await act(btn, "import_sites", [items, f.php.value, f.ssl.checked], `Added ${items.length} sites`);
      if (ok) { refresh(); showWarnings(ok); }
      return !!ok;
    });
  const box = form.querySelector("#found"), submit = form.querySelector("[type=submit]");
  const dbs = call("databases").then((d) => d.databases).catch(() => []);
  // A docroot shown relative to its project folder: "web/production", or "(project folder)".
  const rel = (folder, p) => p.toLowerCase() === folder.toLowerCase() ? "(project folder)"
    : p.toLowerCase().startsWith(folder.toLowerCase() + "/") ? p.slice(folder.length + 1) : p;
  const rootOpt = (folder, p, sel) => `<option value="${esc(p)}" title="${esc(p)}" ${sel ? "selected" : ""}>${esc(rel(folder, p))}</option>`;
  const scan = async () => {
    box.innerHTML = `<div class="loading">Scanning…</div>`;
    const res = await act(null, "scan_folder", [form.base.value.trim()]);
    found = res || [];
    const dbOpts = dbOptions(await dbs);
    submit.disabled = !found.length;
    box.innerHTML = found.length ? `<table>
      <thead><tr><th><input type="checkbox" id="all-pick" checked></th><th>Domain</th><th>PHP</th><th>Database</th><th>Serves from</th></tr></thead>
      <tbody>${found.map((x) => `<tr data-folder="${esc(x.folder)}">
        <td><input type="checkbox" class="pick" ${x.taken ? "" : "checked"}></td>
        <td><div class="input-affix"><input type="text" class="nm" value="${esc(x.name)}" spellcheck="false"><span>.test</span></div></td>
        <td><select class="pv" style="width:auto">${phpOptions(form.php.value)}</select></td>
        <td><select class="db" style="width:auto;max-width:170px">${dbOpts}</select></td>
        <td><div class="row nowrap" title="${esc(x.folder)}"><select class="rt mono small" style="width:auto;max-width:200px">${x.roots.map((p) => rootOpt(x.folder, p, p === x.root)).join("")}</select>
          ${iconBtn("folder", "Pick another folder", "data-pickroot")}</div></td></tr>`).join("")}</tbody></table>`
      : `<div class="empty small">No new folders found</div>`;
    const all = box.querySelector("#all-pick");
    if (all) all.onchange = () => box.querySelectorAll(".pick").forEach((c) => (c.checked = all.checked));
    box.querySelectorAll("[data-pickroot]").forEach((b) => (b.onclick = async () => {
      const tr = b.closest("tr"), sel = tr.querySelector(".rt");
      const p = await act(null, "pick_folder", [sel.value]);
      if (!p) return;
      const path = p.replace(/\\/g, "/");
      if (![...sel.options].some((o) => o.value === path)) sel.insertAdjacentHTML("beforeend", rootOpt(tr.dataset.folder, path, false));
      sel.value = path;
    }));
  };
  form.php.onchange = () => box.querySelectorAll(".pv").forEach((s) => (s.value = form.php.value));
  form.querySelector("#scan").onclick = scan;
  form.querySelector("#browse").onclick = async () => {
    const p = await act(null, "pick_folder", [form.base.value]);
    if (p) { form.base.value = p; scan(); }
  };
  scan();
}

function cloneDialog(name) {
  openDialog(`
    <h3>Clone ${esc(name)}.test</h3>
    <label class="field">New domain
      <div class="input-affix"><input type="text" name="name" required placeholder="${esc(name)}-copy" autocomplete="off" spellcheck="false"><span>.test</span></div>
    </label>
    <div class="muted small">Copies the project folder (skipping .git and node_modules) and its database, if it has one.</div>
    <div class="actions"><button type="button" class="btn ghost" data-cancel>Cancel</button><button type="submit" class="btn primary">Clone</button></div>`,
    async (f, btn) => {
      if (await act(btn, "clone_site", [name, f.name.value.trim()])) { pollJobs(); toast("Cloning started"); }
      return true;
    });
}

function exportSiteDialog(name) {
  openDialog(`
    <h3>Export ${esc(name)}.test</h3>
    <div class="muted small">Saves the project folder, its database and site.json to <span class="mono">data/exports/${esc(name)}-&lt;date&gt;.zip</span>.</div>
    <label class="check"><input type="checkbox" name="git"> Include .git</label>
    <div class="actions"><button type="button" class="btn ghost" data-cancel>Cancel</button><button type="submit" class="btn primary">Export</button></div>`,
    async (f, btn) => {
      if (await act(btn, "export_site", [name, f.git.checked])) { pollJobs(); toast("Export started"); }
      return true;
    });
}

function importZipDialog() {
  openDialog(`
    <h3>Import from .zip</h3>
    <div class="muted small">Pick a .zip made by Export next. Its project folder, database.sql and site.json (if present) become a new site.</div>
    <label class="field">Domain (optional, uses the name from the zip if left blank)
      <div class="input-affix"><input type="text" name="name" placeholder="auto" autocomplete="off" spellcheck="false"><span>.test</span></div>
    </label>
    <div class="actions"><button type="button" class="btn ghost" data-cancel>Cancel</button><button type="submit" class="btn primary">Choose file and import</button></div>`,
    async (f, btn) => {
      if (await act(btn, "import_site_zip", [f.name.value.trim()])) { pollJobs(); toast("Import started"); }
      return true;
    });
}

function deleteDialog(site) {
  openDialog(`
    <h3>Delete ${esc(site.domain)}?</h3>
    <div class="muted">Removes the domain, certificate and Apache config. Your files stay unless you tick the box.</div>
    <label class="check"><input type="checkbox" name="files"> Also delete the folder <code>${esc(site.root)}</code></label>
    <div class="actions"><button type="button" class="btn ghost" data-cancel>Cancel</button><button type="submit" class="btn primary">Delete</button></div>`,
    async (f, btn) => {
      const ok = await act(btn, "delete_site", [site.name, f.files.checked], `Deleted ${site.domain}`);
      if (ok) refresh();
      return ok;
    });
}

// ------------------------------------------------------------------ php

// Newer release of the same branch, if the last check found one.
function phpUpdateFor(v) {
  const r = (S.updates?.php || []).find((x) => x.state === "update" && x.installed.includes(v));
  return r && r.installed[r.installed.length - 1] === v ? r.version : null;
}

function renderPhp() {
  if (!["install", "cli"].includes(phpVer)) phpVer = S.php_versions.includes(phpVer) ? phpVer : S.default_php;
  main.innerHTML = `
    <div class="head"><div><h1>PHP</h1><div class="sub">Each version has its own php.ini. Changes restart Apache.</div></div></div>
    <div class="split">
      <div class="stack">
        <div class="card vlist">${[...S.php_versions].reverse().map((v) => `<button data-v="${v}" class="${v === phpVer ? "active" : ""}">
            <span>${v}${phpUpdateFor(v) ? ` <span class="upd" title="Update ${esc(phpUpdateFor(v))} available">●</span>` : ""}</span>
            ${v === S.default_php ? `<span class="faint small">default</span>` : ""}</button>`).join("")}</div>
        <div class="card vlist">
          <button data-v="cli" class="${phpVer === "cli" ? "active" : ""}">CLI &amp; Composer</button>
          <button data-v="install" class="${phpVer === "install" ? "active" : ""}">+ Install / update</button>
        </div>
      </div>
      <div id="php-body"><div class="loading">Loading…</div></div>
    </div>`;
  main.querySelectorAll(".vlist button").forEach((b) => (b.onclick = () => { phpVer = b.dataset.v; renderPhp(); }));
  if (phpVer === "install") return renderPhpCatalog();
  if (phpVer === "cli") return renderPhpCli();
  const ver = phpVer;
  cached(`php:${ver}`, "php_config", [ver], (c) => view === "php" && phpVer === ver && drawPhp(c));
}

// CLI version + PATH + Composer, one setting for the whole install (not per PHP version).
function renderPhpCli() {
  cached("cli_status", "cli_status", [], (c) => view === "php" && phpVer === "cli" && drawPhpCli(c));
}

function drawPhpCli(c) {
  document.getElementById("php-body").innerHTML = `
    <div class="card pad stack">
      <b>PHP CLI</b>
      <div class="muted small">Used by <span class="mono">php</span> in a console when a folder has no <span class="mono">.php-version</span> file
        (put one with e.g. <span class="mono">8.3</span> to pin a project to a version).</div>
      <label class="field" style="max-width:260px">CLI version<select id="cli-ver">${phpOptions(c.cli_php || c.default_php)}</select></label>
      <div class="row">
        <span class="mono small">${esc(c.path_entry)}</span>
        ${c.on_path ? `<span class="tag accent">on PATH</span><button class="btn sm" id="rm-path">Remove from PATH</button>`
          : `<span class="faint small">not on PATH</span><button class="btn sm primary" id="add-path">Add to PATH</button>`}
      </div>
      <div class="faint small">PATH changes need a new console window (and are per-user, no restart needed).</div>
    </div>
    <div class="card pad stack" style="margin-top:12px">
      <div class="row between"><b>Composer</b>
        <button class="btn sm ${c.composer_version ? "" : "primary"}" id="composer-btn">${c.composer_version ? "Update Composer" : "Install Composer"}</button></div>
      <div class="muted small">${c.composer_version ? `Installed: ${esc(c.composer_version)}` : "Not installed."} Runs as <span class="mono">bin/cli/composer.bat</span>, using whatever <span class="mono">php</span> resolves to.</div>
    </div>`;
  const sel = document.getElementById("cli-ver");
  sel.onchange = async () => { if (await act(sel, "set_cli_php", [sel.value], `CLI PHP set to ${sel.value}`)) { delete CACHE["cli_status"]; renderPhpCli(); } };
  const addBtn = document.getElementById("add-path"), rmBtn = document.getElementById("rm-path");
  if (addBtn) addBtn.onclick = async () => { if (await act(addBtn, "add_cli_to_path", [], "Added to PATH")) { delete CACHE["cli_status"]; renderPhpCli(); } };
  if (rmBtn) rmBtn.onclick = async () => { if (await act(rmBtn, "remove_cli_from_path", [], "Removed from PATH")) { delete CACHE["cli_status"]; renderPhpCli(); } };
  document.getElementById("composer-btn").onclick = (e) => startJob(e.target, "install_composer");
}

function drawPhp(c) {
  const labels = {
    short_open_tag: "short_open_tag", display_errors: "display_errors", error_reporting: "error_reporting",
    memory_limit: "memory_limit", upload_max_filesize: "upload_max_filesize", post_max_size: "post_max_size",
    max_execution_time: "max_execution_time", max_input_time: "max_input_time", max_input_vars: "max_input_vars", "date.timezone": "date.timezone",
  };
  const onOff = (k, v) => `<label class="field">${k}<select name="${k}">${["On", "Off"].map((o) => `<option ${String(v).toLowerCase() === o.toLowerCase() || (o === "On" && v === "1") || (o === "Off" && (v === "0" || v === "")) ? "selected" : ""}>${o}</option>`).join("")}</select></label>`;
  document.getElementById("php-body").innerHTML = `
    <form id="php-form" class="stack">
      <div class="card pad stack">
        <div class="row between">
          <div><b>PHP ${esc(c.version)}</b><div class="muted small">${c.sites.length ? "Used by " + c.sites.map(esc).join(", ") : "Not used by any site"}</div></div>
          <div class="row">
            ${phpUpdateFor(phpVer) ? `<button type="button" class="btn sm hl" id="upd">Update to ${esc(phpUpdateFor(phpVer))}</button>` : ""}
            ${phpVer === S.default_php ? "" : `<button type="button" class="btn sm" id="mkdef">Make default</button>`}
            <button type="button" class="btn sm" id="ini">Open php.ini</button>
            ${!c.sites.length && phpVer !== S.default_php ? `<button type="button" class="btn sm ghost danger" id="rm">Remove</button>` : ""}
          </div>
        </div>
        <div class="form-grid">
          ${Object.keys(labels).map((k) => ["short_open_tag", "display_errors"].includes(k) ? onOff(k, c.settings[k])
            : k === "date.timezone" ? `<label class="field">${k}<select name="${k}"><option>${esc(c.settings[k])}</option></select></label>`
            : `<label class="field">${k}<input type="text" name="${k}" value="${esc(c.settings[k])}" spellcheck="false"></label>`).join("")}
        </div>
      </div>
      <div class="card pad stack">
        <b>Extensions</b>
        <div class="ext-grid">${c.extensions.map((x) => `<label class="check small"><input type="checkbox" data-ext="${esc(x.name)}" ${x.enabled ? "checked" : ""}>${esc(x.name)}</label>`).join("")}</div>
      </div>
      <div class="card pad stack" id="xdebug-card"><b>Xdebug</b><div class="muted small">Checking…</div></div>
      <div><button type="submit" class="btn primary">Save and restart Apache</button></div>
    </form>`;
  cached(`xdebug:${phpVer}`, "xdebug_info", [phpVer], (x) => view === "php" && phpVer === c.version && drawXdebug(x));

  const form = document.getElementById("php-form");
  fillTimezones(form.elements["date.timezone"], c.settings["date.timezone"]);
  document.getElementById("ini").onclick = () => call("open_ini", phpVer);
  const mk = document.getElementById("mkdef");
  if (mk) mk.onclick = async () => { if (await act(mk, "set_default_php", [phpVer], `PHP ${phpVer} is the default for new sites`)) refresh(); };
  const upd = document.getElementById("upd");
  if (upd) upd.onclick = () => phpUpdateDialog(upd, phpVer, phpUpdateFor(phpVer), c.sites);
  const rm = document.getElementById("rm");
  if (rm) rm.onclick = async () => {
    if (!(await confirmDialog(`Remove PHP ${phpVer}?`, `Deletes <span class="mono">bin/php/php${esc(phpVer)}</span> including its php.ini.`, "Remove"))) return;
    if (await act(rm, "remove_php", [phpVer], `PHP ${phpVer} removed`)) { phpVer = null; refresh(); }
  };
  form.onsubmit = async (e) => {
    e.preventDefault();
    const values = {}, exts = {};
    Object.keys(labels).forEach((k) => {
      const now = form.elements[k].value, before = c.settings[k];
      const same = ["short_open_tag", "display_errors"].includes(k)
        ? (now === "On") === ["1", "on"].includes(String(before).toLowerCase())
        : now === before;
      if (!same) values[k] = now;
    });
    form.querySelectorAll("[data-ext]").forEach((cb) => {
      const was = c.extensions.find((x) => x.name === cb.dataset.ext).enabled;
      if (cb.checked !== was) exts[cb.dataset.ext] = cb.checked;
    });
    if (!Object.keys(values).length && !Object.keys(exts).length) return toast("Nothing changed");
    if (await act(e.submitter, "php_update", [phpVer, values, exts], `PHP ${phpVer} saved`)) { delete CACHE[`php:${phpVer}`]; renderPhp(); }
  };
}

// Xdebug status/install card on the PHP page. Enable/disable itself is just the "xdebug" checkbox
// in the Extensions grid once it's downloaded (that goes through the normal php_update save).
function drawXdebug(x) {
  const box = document.getElementById("xdebug-card");
  if (!box) return;
  const hint = `<div class="faint small">PhpStorm: Settings &rsaquo; PHP &rsaquo; Debug, port 9003. Trigger a session with the
    "Xdebug helper" browser extension or a <span class="mono">XDEBUG_TRIGGER</span> cookie/query param.</div>`;
  if (!x.build.compiler) {
    box.innerHTML = `<b>Xdebug</b><div class="muted small">Could not detect the Visual C++ runtime this PHP build uses.</div>`;
  } else if (!x.available && !x.downloaded) {
    box.innerHTML = `<b>Xdebug</b><div class="muted small">No Xdebug 3.x build for PHP ${esc(phpVer)}
      (${x.build.ts ? "TS" : "NTS"}, ${esc(x.build.compiler)}). Likely a pre-release or too old a PHP version.</div>`;
  } else if (!x.downloaded) {
    box.innerHTML = `<b>Xdebug</b><div class="muted small">Not installed for this PHP version (${x.build.ts ? "TS" : "NTS"}, ${esc(x.build.compiler)}).</div>
      <div><button type="button" class="btn sm primary" id="xdebug-install">Install Xdebug</button></div>`;
    document.getElementById("xdebug-install").onclick = (e) => startJob(e.target, "install_xdebug", [phpVer]);
  } else {
    box.innerHTML = `<b>Xdebug</b><div class="muted small">Downloaded. Use the checkbox above to enable it (restarts Apache).</div>${hint}`;
  }
}

// date.timezone picker: PHP's own list, grouped by region (Asia/Bangkok -> Asia).
let tzCache = null;
async function fillTimezones(sel, cur) {
  try { tzCache ||= await call("php_timezones", phpVer); } catch (e) { return toast(e.message, true); }
  if (!sel.isConnected) return;
  const groups = {};
  for (const z of tzCache) (groups[z.includes("/") ? z.split("/")[0] : "Other"] ||= []).push(z);
  sel.innerHTML = (cur && !tzCache.includes(cur) ? `<option selected>${esc(cur)}</option>` : !cur ? `<option value="" selected>(not set)</option>` : "") +
    Object.entries(groups).map(([g, list]) => `<optgroup label="${esc(g)}">${list.map((z) =>
      `<option ${z === cur ? "selected" : ""}>${esc(z)}</option>`).join("")}</optgroup>`).join("");
}

async function phpUpdateDialog(btn, old, version, sites) {
  const ok = await confirmDialog(`Update PHP ${old} to ${version}?`,
    `Installs PHP ${esc(version)} next to ${esc(old)}, copies its php.ini settings and extensions,
     ${sites.length ? `and moves ${sites.length} site${sites.length > 1 ? "s" : ""} (${sites.map(esc).join(", ")}) to it. Apache restarts.` : "."}
     <br><br>PHP ${esc(old)} stays installed until you remove it.`, "Update");
  if (ok) startJob(btn, "update_php", [old, version]);
}

function preLabel(v) {
  return /RC/i.test(v) ? "release candidate" : /beta/i.test(v) ? "beta" : /alpha/i.test(v) ? "alpha" : "preview";
}

function renderPhpCatalog() {
  const U = S.updates;
  const rows = U.php.filter((r) => r.version);
  document.getElementById("php-body").innerHTML = `
    <div class="card pad row between">
      <div><b>PHP versions for Windows</b><div class="muted small">From windows.php.net (thread-safe x64 builds).
        Last checked ${esc(fmtAgo(U.checked))}${U.errors.php ? ` · <span class="bad-text">${esc(U.errors.php)}</span>` : ""}</div></div>
      <button class="btn ${U.checked ? "" : "primary"}" id="check">Check for updates</button>
    </div>
    ${rows.length ? `<div class="card" style="margin-top:12px"><table>
      <thead><tr><th>Branch</th><th>Latest</th><th>Installed</th><th></th></tr></thead>
      <tbody>${rows.map((r) => {
        const last = r.installed.filter((v) => !/RC|alpha|beta|dev/i.test(v)).pop();
        const users = last ? (U.php_used[last] || []) : [];
        return `<tr>
          <td><b>${esc(r.branch)}</b> ${r.pre ? `<span class="tag accent">${preLabel(r.version)}</span>` : ""}</td>
          <td class="mono">${esc(r.version)}</td>
          <td>${r.installed.length ? r.installed.map((v) => `<span class="tag">${esc(v)}</span>`).join(" ") : `<span class="faint">–</span>`}</td>
          <td style="text-align:right">${
            r.state === "installed" ? `<span class="faint small">up to date</span>`
            : r.state === "update" ? `<button class="btn sm hl" data-upd="${esc(last)}" data-to="${esc(r.version)}" data-users="${esc(users.join(","))}">Update to ${esc(r.version)}</button>`
            : `<button class="btn sm" data-inst="${esc(r.version)}">Install</button>`}</td>
        </tr>`;
      }).join("")}</tbody></table></div>
      <div class="faint small" style="margin-top:8px">Old branches (5.6 – 8.0) get no security fixes any more; fine for running old projects locally.
        Pre-releases are for testing only.</div>`
    : `<div class="card empty" style="margin-top:12px">Press <b>Check for updates</b> to see every PHP version from 5.6 to the newest.</div>`}`;
  const chk = document.getElementById("check");
  chk.onclick = async () => { if (await act(chk, "check_updates", [], "Version list updated")) refresh(); };
  main.querySelectorAll("[data-inst]").forEach((b) => (b.onclick = () => startJob(b, "install_php", [b.dataset.inst])));
  main.querySelectorAll("[data-upd]").forEach((b) => (b.onclick = () =>
    phpUpdateDialog(b, b.dataset.upd, b.dataset.to, b.dataset.users ? b.dataset.users.split(",") : [])));
}

// ------------------------------------------------------------------ database

let dbFilter = "";
let dbSort = "name";
let dbSection = "databases";   // "databases" | "users" | "backups" | "import" (left vlist, same style as the PHP page)

function renderDatabase() {
  main.innerHTML = `
    <div class="head"><div><h1>Database</h1><div class="sub">MySQL ${esc(S.versions.mysql || "")}, one server for all sites.</div></div>
      <div class="row">${dbSection === "databases" ? `<button class="btn" id="newdb">+ Create database</button><button class="btn" id="importsql">Import .sql</button>` : ""}
        <button class="btn primary" data-url="${esc(S.pma_url)}">Open phpMyAdmin</button></div></div>
    <div class="split">
      <div class="card vlist" style="position:sticky;top:0">${[["databases", "Databases"], ["users", "Users"], ["backups", "Backups"], ["import", "Import"]]
        .map(([k, l]) => `<button data-sec="${k}" class="${dbSection === k ? "active" : ""}">${l}</button>`).join("")}</div>
      <div id="db-body"><div class="loading">Loading…</div></div>
    </div>`;
  bindLinks();
  const newdb = document.getElementById("newdb");
  if (newdb) newdb.onclick = createDatabaseDialog;
  const impsql = document.getElementById("importsql");
  if (impsql) impsql.onclick = importSqlDialog;
  main.querySelectorAll("[data-sec]").forEach((b) => (b.onclick = () => { dbSection = b.dataset.sec; renderDatabase(); }));
  if (dbSection === "databases") renderDbSectionDatabases();
  else if (dbSection === "users") renderDbSectionUsers();
  else if (dbSection === "backups") renderDbSectionBackups();
  else renderDbSectionImport();
}

function renderDbSectionDatabases() {
  document.getElementById("db-body").innerHTML = `
    <div class="card"><table><tbody>
      <tr><td class="muted">Status</td><td><span class="row"><span class="dot ${S.services.mysql}"></span>${statusLabel(S.services.mysql)}</span></td>
          <td class="muted">Host</td><td class="mono">127.0.0.1 : ${S.ports.mysql}</td></tr>
      <tr><td class="muted">User</td><td class="mono">root <span class="faint">${S.mysql_password ? "(password in Settings file)" : "(no password)"}</span></td>
          <td class="muted">Data folder</td><td><a class="mono" data-path="${esc(S.root)}/data/mysql">${esc(S.root)}/data/mysql</a></td></tr>
    </tbody></table></div>
    <div class="row between" style="margin:28px 0 10px"><h2 style="margin:0">Databases</h2>
      <input type="text" id="dbq" placeholder="Filter…" value="${esc(dbFilter)}" style="width:220px" spellcheck="false"></div>
    <div id="dblist"><div class="card loading">Loading…</div></div>`;
  bindLinks();
  loadDatabases();
}

function renderDbSectionImport() {
  document.getElementById("db-body").innerHTML = `
    <div class="sub" style="margin-bottom:16px">Bring databases in from another local server.</div>
    <h2 style="margin-top:0">Import a .sql file</h2>
    <div class="card pad stack">
      <div class="muted">Works from any MySQL or MariaDB server, any version.</div>
      <div><button class="btn" id="importsql2">Import .sql</button></div>
    </div>
    <h2>Import Database (data folder)</h2>
    <div class="card pad stack">
      <div class="muted">Copies a whole MySQL data folder (all databases and users) into DevStack. The current DevStack data is kept as a backup folder.
        <b>Stop the other server's MySQL first</b>, its data must not be copied while it runs. Only works when that MySQL has the same major
        version as DevStack's (${esc(S.versions.mysql || "")}). MariaDB data folders are not compatible - use a .sql file instead.</div>
      <div class="row"><input type="text" id="src" value="" placeholder="Path to the other server's MySQL data folder" spellcheck="false"><button class="btn" id="browse">Browse</button><button class="btn" id="imp">Import</button></div>
    </div>
    <h2>Guide: moving databases from another local server</h2>
    <div class="card pad stack">
      <div class="muted small">Recommended way: export a .sql file, then import it here.</div>
      <ol class="small" style="margin:0;padding-left:20px">
        <li>In the old server's phpMyAdmin: select the database &gt; Export &gt; Quick, format SQL &gt; Go.
          Or from a terminal: <span class="mono">mysqldump -u root -p --databases mydb &gt; mydb.sql</span></li>
        <li>Here: <b>Import .sql</b> above, type the database name, keep "Create the database if it doesn't exist" checked.</li>
        <li>Point your site's config (DB name/user/password) at DevStack: host <span class="mono">127.0.0.1</span>,
          port <span class="mono">${esc(String(S.ports.mysql))}</span>, user <span class="mono">root</span>.</li>
      </ol>
      <div class="faint small">Users and passwords come along only with the data-folder method above; with a .sql file, create users in the
        Users tab or in Sites &gt; Create database.</div>
      <div class="muted small" style="margin-top:8px">Where the data folder usually is (only needed for the data-folder method):</div>
      <table class="small"><tbody>
        <tr><td class="muted">XAMPP</td><td class="mono">C:\\xampp\\mysql\\data</td><td class="faint">(MariaDB - use .sql instead)</td></tr>
        <tr><td class="muted">WAMP</td><td class="mono">C:\\wamp64\\bin\\mysql\\mysql&lt;version&gt;\\data</td><td></td></tr>
        <tr><td class="muted">Laragon</td><td class="mono">C:\\laragon\\data\\mysql-8</td><td class="faint">(or similar)</td></tr>
        <tr><td class="muted">ServBay</td><td>its database data folder (see its settings)</td><td class="faint">(.sql export is easier)</td></tr>
      </tbody></table>
    </div>`;
  bindLinks();
  document.getElementById("importsql2").onclick = importSqlDialog;
  document.getElementById("browse").onclick = async () => {
    const p = await act(null, "pick_folder", [document.getElementById("src").value]);
    if (p) document.getElementById("src").value = p;
  };
  document.getElementById("imp").onclick = async (e) => {
    const src = document.getElementById("src").value.trim();
    if (!src) return toast("Pick a data folder first", true);
    if (await act(e.currentTarget, "import_mysql", [src], "Databases imported, MySQL restarted")) refresh();
  };
}

function loadDatabases(fresh = false) {
  if (fresh) delete CACHE.databases;
  cached("databases", "databases", [], drawDatabases);
}

function drawDatabases(d) {
  const box = document.getElementById("dblist");
  if (!box || view !== "database" || dbSection !== "databases") return;
  const pma = (db) => `${S.pma_url}index.php?route=/database/structure&db=${encodeURIComponent(db)}`;
  const draw = () => {
    const q = dbFilter.toLowerCase();
    const list = d.databases.filter((x) => !q || x.name.toLowerCase().includes(q) || x.sites.some((s) => s.includes(q)))
      .sort(dbSort === "size" ? (a, b) => b.size - a.size : dbSort === "modified" ? (a, b) => b.modified - a.modified
        : (a, b) => a.name.localeCompare(b.name));
    const total = d.databases.reduce((a, x) => a + x.size, 0);
    const th = (k, label) => `<th class="sortable ${dbSort === k ? "sorted" : ""}" data-sort="${k}">${label}</th>`;
    box.innerHTML = `<div class="card"><table>
      <thead><tr>${th("name", "Name")}<th>Tables</th>${th("size", "Size")}${th("modified", "Last change")}<th>Last backup</th><th>Used by</th><th>User</th><th></th></tr></thead>
      <tbody>${list.map((x) => `<tr>
        <td class="mono">${esc(x.name)}</td>
        <td class="muted">${x.tables}</td>
        <td>${fmtBytes(x.size)}</td>
        <td class="muted small">${esc(fmtDate(x.modified))}</td>
        <td class="muted small">${x.last_backup ? esc(fmtAgo(x.last_backup)) : `<span class="faint">never</span>`}</td>
        <td>${x.sites.map((s) => `<span class="tag">${esc(s)}</span>`).join(" ") || `<span class="faint">–</span>`}</td>
        <td class="small muted">${(x.users || []).length ? x.users.map(esc).join(", ") : `<span class="faint">–</span>`}</td>
        <td class="r"><div class="tools">
          ${iconBtn("pma", "Open in phpMyAdmin", `data-url="${esc(pma(x.name))}"`)}
          ${iconBtn("download", "Export: download as .sql", `data-export="${esc(x.name)}"`)}
          ${iconBtn("archive", "Back up to the exports folder", `data-backup="${esc(x.name)}"`)}</div></td>
      </tr>`).join("") || `<tr><td colspan="8" class="empty">No databases match</td></tr>`}</tbody>
      <tfoot><tr><td class="muted small" colspan="8">${d.databases.length} databases · ${fmtBytes(total)} on disk.
        "Used by" comes from each project's config files; set it by hand in Sites › Edit.</td></tr></tfoot>
    </table></div>`;
    box.querySelectorAll("[data-sort]").forEach((h) => (h.onclick = () => { dbSort = h.dataset.sort; draw(); }));
    box.querySelectorAll("[data-export]").forEach((b) => (b.onclick = () => startJob(b, "export_db", [b.dataset.export])));   // asks where to save first
    box.querySelectorAll("[data-backup]").forEach((b) => (b.onclick = () => startJob(b, "backup_db", [b.dataset.backup])));
    bindLinks(box);
  };
  document.getElementById("dbq").oninput = (e) => { dbFilter = e.target.value; draw(); };
  draw();
}

// MySQL users (mysql.user), with the databases each one has privileges on. Needs MySQL running.
async function renderDbSectionUsers() {
  const box = document.getElementById("db-body");
  box.innerHTML = `<div class="card loading">Loading…</div>`;
  let list;
  try { list = await call("users"); } catch (e) { box.innerHTML = `<div class="card empty">${esc(e.message)}</div>`; return; }
  if (view !== "database" || dbSection !== "users") return;
  drawDbUsers(list);
}

function drawDbUsers(list) {
  const box = document.getElementById("db-body");
  if (!box) return;
  box.innerHTML = `<div class="card"><table>
    <thead><tr><th>User</th><th>Databases</th><th></th></tr></thead>
    <tbody>${list.map((u) => `<tr>
      <td><span class="mono">${esc(u.user)}@${esc(u.host)}</span> ${u.root ? `<span class="tag accent">main</span>` : ""}</td>
      <td>${u.databases.length ? u.databases.map((d) => `<span class="tag">${esc(d)}</span>`).join(" ") : `<span class="faint">–</span>`}</td>
      <td class="r"><div class="tools">
        ${iconBtn("edit", "Change password", `data-pwuser="${esc(u.user)}" data-pwhost="${esc(u.host)}"`)}
        ${u.root ? "" : iconBtn("trash", "Delete user", `data-deluser="${esc(u.user)}" data-delhost="${esc(u.host)}"`, "danger")}
      </div></td>
    </tr>`).join("") || `<tr><td colspan="3" class="empty">No users</td></tr>`}</tbody></table></div>`;
  box.querySelectorAll("[data-pwuser]").forEach((b) => (b.onclick = () => userPasswordDialog(b.dataset.pwuser, b.dataset.pwhost)));
  box.querySelectorAll("[data-deluser]").forEach((b) => (b.onclick = async () => {
    if (!(await confirmDialog(`Delete ${esc(b.dataset.deluser)}@${esc(b.dataset.delhost)}?`, "This MySQL user is removed for good.", "Delete"))) return;
    if (await act(b, "drop_user", [b.dataset.deluser, b.dataset.delhost], "User deleted")) { delete CACHE.databases; renderDbSectionUsers(); }
  }));
}

function userPasswordDialog(user, host) {
  openDialog(`
    <h3>Change password for ${esc(user)}@${esc(host)}</h3>
    <label class="field">New password<input type="text" name="password" required autocomplete="off" spellcheck="false"></label>
    <div class="actions"><button type="button" class="btn ghost" data-cancel>Cancel</button><button type="submit" class="btn primary">Save</button></div>`,
    async (f, btn) => {
      if (!(await act(btn, "set_user_password", [user, host, f.password.value], user === "root" ? "Password changed (all root accounts)" : "Password changed"))) return false;
      if (user === "root") refresh();   // the Databases section shows whether root has a password
      return true;
    });
}

// Scheduled backups (used to be on Settings) now lives in its own Database sub-section.
function renderDbSectionBackups() {
  document.getElementById("db-body").innerHTML = `
    <h2 style="margin-top:0">Scheduled backups</h2>
    <div class="card pad stack" id="backup-settings"><div class="loading">Loading…</div></div>
    <div id="dbbackups"></div>`;
  cached("databases", "databases", [], (d) => { if (view === "database" && dbSection === "backups") { drawBackupSettings(d); drawBackupsLists(d); } });
}

// SQL backups (d.exports) and data folder backups (d.backups), shown on the Backups tab under the scheduled-backup form.
function drawBackupsLists(d) {
  const bk = document.getElementById("dbbackups");
  if (!bk || view !== "database" || dbSection !== "backups") return;
  bk.innerHTML = `<div class="row between" style="margin:28px 0 10px"><h2 style="margin:0">SQL backups</h2>
      <button class="btn sm" data-path="${esc(d.exports_dir)}">${icon("folder")}Open folder</button></div>
    ${d.exports.length ? `<div class="card"><table><tbody>${d.exports.map((f) => `<tr>
      <td class="mono">${esc(f.name)}</td><td class="num">${fmtBytes(f.size)}</td><td class="muted small">${esc(fmtAgo(f.modified))}</td>
      <td class="r">${iconBtn("trash", "Delete", `data-delexp="${esc(f.name)}"`, "danger")}</td></tr>`).join("")}</tbody></table></div>`
    : `<div class="card empty small">No backups yet. Use ${icon("archive")} on a database (Databases tab) to save one to <span class="mono">${esc(d.exports_dir)}</span>.</div>`}` +
    (d.backups.length ? `<h2>Data folder backups</h2><div class="card"><table><tbody>${d.backups.map((b) => `<tr>
      <td><a class="mono" data-path="${esc(b.path)}">${esc(b.name)}</a></td><td>${fmtBytes(b.size)}</td>
      <td class="r">${iconBtn("trash", "Delete", `data-delbk="${esc(b.name)}"`, "danger")}</td></tr>`).join("")}</tbody></table></div>
    <div class="faint small" style="margin-top:6px">Made by data folder imports and by MySQL updates. Delete them once everything works.</div>` : "");
  bindLinks(bk);
  bk.querySelectorAll("[data-delbk]").forEach((b) => (b.onclick = async () => {
    if (!(await confirmDialog("Delete backup?", `Deletes <span class="mono">data/${esc(b.dataset.delbk)}</span> for good.`, "Delete"))) return;
    if (await act(b, "delete_db_backup", [b.dataset.delbk], "Backup deleted")) { delete CACHE.databases; cached("databases", "databases", [], (d2) => drawBackupsLists(d2)); }
  }));
  bk.querySelectorAll("[data-delexp]").forEach((b) => (b.onclick = async () => {
    if (!(await confirmDialog("Delete backup?", `Deletes <span class="mono">${esc(b.dataset.delexp)}</span>.`, "Delete"))) return;
    if (await act(b, "delete_export", [b.dataset.delexp], "Backup deleted")) { delete CACHE.databases; cached("databases", "databases", [], (d2) => drawBackupsLists(d2)); }
  }));
}

// ------------------------------------------------------------------ certificates

function renderCerts(fresh = false) {
  if (fresh) delete CACHE.certs;
  main.innerHTML = `
    <div class="head"><div><h1>Certificates</h1><div class="sub">Local HTTPS: one certificate authority (CA) signs a certificate for every site.</div></div>
      <div class="row"><button class="btn" data-path="${esc(S.root)}/ssl">Open folder</button><button class="btn primary" id="renew-all">Renew all</button></div></div>
    <div id="certs"><div class="card loading">Loading…</div></div>`;
  bindLinks();
  cached("certs", "certs", [], (c) => view === "certs" && document.getElementById("certs") && drawCerts(c));
}

function drawCerts(c) {
  const ca = c.ca;
  const stateTag = (s) => ({
    ok: `<span class="tag ok">valid</span>`, expiring: `<span class="tag warn">expires soon</span>`, expired: `<span class="tag bad">expired</span>`,
    missing: `<span class="tag bad">missing</span>`, foreign: `<span class="tag warn">not from this CA</span>`,
  }[s] || esc(s));
  const byDomain = Object.fromEntries(c.sites.map((x) => [x.domain, x]));
  document.getElementById("certs").innerHTML = `
    <div class="card pad row between">
      <div class="grow"><b>${esc(ca?.name || "No CA yet")}</b>
        ${ca ? `<div class="muted small">Valid until ${esc(fmtDate(ca.expires))} · SHA-1 <span class="mono">${esc(ca.fingerprint)}</span></div>
        <div class="muted small">${ca.trusted ? "Trusted by Windows, Chrome and Edge." : "Not trusted yet, so browsers warn on https:// sites."}
          Firefox: set security.enterprise_roots.enabled. Phones/other PCs: install <a data-path="${esc(S.root)}/ssl/ca">devstack-ca.crt</a>.</div>` : ""}</div>
      ${ca?.trusted ? `<span class="tag ok">Trusted</span>` : `<button class="btn hl" id="trust">Trust</button>`}
    </div>
    <h2>Sites</h2>
    <div class="card"><table>
      <thead><tr><th>Domain</th><th>HTTPS</th><th>Status</th><th>Covers</th><th>Expires</th><th></th></tr></thead>
      <tbody>${c.sites_all.map((s) => {
        const x = byDomain[s.domain];
        return `<tr>
          <td>${esc(s.domain)}</td>
          <td><label class="check"><input type="checkbox" data-ssl="${esc(s.name)}" ${s.ssl ? "checked" : ""}></label></td>
          <td>${x ? stateTag(x.state) : `<span class="faint">off</span>`}</td>
          <td class="small muted">${x?.names ? x.names.map(esc).join(", ") : ""}</td>
          <td class="small">${x?.expires ? `${esc(fmtDate(x.expires))} <span class="faint">(${x.days_left} days)</span>` : ""}</td>
          <td style="text-align:right">${s.ssl ? `<button class="btn sm ghost" data-renew="${esc(s.domain)}">Renew</button>` : ""}</td>
        </tr>`;
      }).join("")}</tbody></table></div>
    <div class="faint small" style="margin-top:6px">Certificates last 825 days and are renewed automatically when fewer than 30 are left. Renewing restarts Apache.</div>
    ${c.orphans.length ? `<h2>Left over</h2><div class="card"><table><tbody>${c.orphans.map((d) => `<tr>
      <td class="mono">${esc(d)}</td><td class="muted small">certificate of a site that no longer uses HTTPS</td>
      <td style="text-align:right"><button class="btn sm ghost danger" data-delcert="${esc(d)}">Delete</button></td></tr>`).join("")}</tbody></table></div>` : ""}`;
  bindLinks();
  const trust = document.getElementById("trust");
  if (trust) trust.onclick = async () => { if (await act(trust, "trust_ca", [], "Certificate authority trusted")) { delete CACHE.certs; await refresh(); } };
  document.getElementById("renew-all").onclick = async (e) => {
    const all = c.sites.map((x) => x.domain);
    if (await act(e.currentTarget, "renew_certs", [all], `Renewed ${all.length} certificates`)) renderCerts(true);
  };
  main.querySelectorAll("[data-renew]").forEach((b) => (b.onclick = async () => {
    if (await act(b, "renew_certs", [[b.dataset.renew]], `Renewed ${b.dataset.renew}`)) renderCerts(true);
  }));
  main.querySelectorAll("[data-ssl]").forEach((cb) => (cb.onchange = async () => {
    cb.disabled = true;
    await act(null, "update_site", [cb.dataset.ssl, { ssl: cb.checked }], `HTTPS ${cb.checked ? "on" : "off"} for ${cb.dataset.ssl}.test`);
    delete CACHE.certs;
    await refresh();
  }));
  main.querySelectorAll("[data-delcert]").forEach((b) => (b.onclick = async () => {
    if (await act(b, "delete_cert", [b.dataset.delcert], "Deleted")) renderCerts(true);
  }));
}

// ------------------------------------------------------------------ mail

let mailId = null;

function renderMail(fresh = false) {
  if (fresh) delete CACHE.mail;
  if (!CACHE.mail) main.innerHTML = `<div class="head"><div><h1>Mail</h1></div></div><div class="card loading">Loading…</div>`;
  cached("mail", "mail_list", [], (list) => view === "mail" && drawMail(list));
}

function drawMail(list) {
  markMailSeen(list.length);
  updateMailBadge(MAIL_COUNT_LAST);
  if (!list.some((m) => m.id === mailId)) mailId = list[0]?.id || null;
  main.innerHTML = `
    <div class="head"><div><h1>Mail</h1><div class="sub">Local SMTP catcher - nothing is actually sent.</div></div>
      <button class="btn ghost danger" id="mail-clear" ${list.length ? "" : "disabled"}>Clear all</button></div>
    <div class="card pad stack" id="mail-settings"><div class="loading">Loading…</div></div>
    ${list.length ? `
    <div class="split" style="margin-top:16px">
      <div class="card vlist" style="max-height:70vh;overflow:auto">${list.map((m) => `
        <button data-m="${esc(m.id)}" class="${m.id === mailId ? "active" : ""}">
          <span class="ellipsis" style="max-width:220px">${esc(m.subject)}</span>
          <span class="faint small">${esc(fmtAgo(m.date))}</span>
        </button>`).join("")}</div>
      <div id="mail-body"><div class="empty">Pick a message</div></div>
    </div>` : `<div class="empty" style="padding:60px 20px">Sent mail from your projects will show up here once the mail catcher is on above.</div>`}`;
  main.querySelectorAll("[data-m]").forEach((b) => (b.onclick = () => { mailId = b.dataset.m; drawMailBody(); }));
  document.getElementById("mail-clear").onclick = async () => {
    if (!(await confirmDialog("Clear all mail?", `Deletes all ${list.length} messages.`, "Clear all"))) return;
    if (await act(null, "mail_clear", [], "Cleared")) renderMail(true);
  };
  if (mailId) drawMailBody();
  cached("mail_status", "mail_status", [], (m) => view === "mail" && drawMailSettings(m));
}

async function drawMailBody() {
  const box = document.getElementById("mail-body");
  if (!box) return;
  const id = mailId;
  let m;
  try { m = await call("mail_read", id); } catch (e) { box.innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
  if (mailId !== id || !box.isConnected) return;
  box.innerHTML = `
    <div class="card pad stack">
      <div class="row between"><b class="ellipsis">${esc(m.subject)}</b>
        <div class="tools">${iconBtn("trash", "Delete", `data-mdel="${esc(m.id)}"`, "danger")}</div></div>
      <table><tbody>
        <tr><td class="muted small">From</td><td class="mono small">${esc(m.from)}</td></tr>
        <tr><td class="muted small">To</td><td class="mono small">${esc(m.to)}</td></tr>
        ${m.cc ? `<tr><td class="muted small">Cc</td><td class="mono small">${esc(m.cc)}</td></tr>` : ""}
        <tr><td class="muted small">Date</td><td class="small">${esc(fmtDate(m.date))} ${esc(new Date(m.date * 1000).toLocaleTimeString())}</td></tr>
      </tbody></table>
      ${m.attachments.length ? `<div><b class="small">Attachments</b><div class="row" style="flex-wrap:wrap">${m.attachments.map((a) =>
        `<button class="btn sm" data-att="${a.index}">${esc(a.filename)} (${fmtBytes(a.size)})</button>`).join("")}</div></div>` : ""}
      ${m.html ? `<iframe sandbox="" srcdoc="${esc(m.html)}" style="width:100%;height:400px;border:1px solid var(--border);border-radius:8px;background:#fff"></iframe>`
        : `<pre class="log" style="max-height:400px">${esc(m.text || "(empty body)")}</pre>`}
    </div>`;
  box.querySelector("[data-mdel]").onclick = async () => {
    if (await act(null, "mail_delete", [m.id], "Deleted")) renderMail(true);
  };
  box.querySelectorAll("[data-att]").forEach((b) => (b.onclick = () => act(b, "save_attachment", [m.id, Number(b.dataset.att)], "Saved")));
}

// ------------------------------------------------------------------ logs

function renderLogs(fresh = false) {
  if (fresh) delete CACHE.logs;
  if (!CACHE.logs) main.innerHTML = `<div class="head"><div><h1>Logs</h1></div></div><div class="card loading">Loading…</div>`;
  cached("logs", "logs", [], (files) => view === "logs" && drawLogs(files));
}

function drawLogs(files) {
  if (!files.includes(logFile)) logFile = files[0] || null;
  main.innerHTML = `
    <div class="head"><div><h1>Logs</h1></div>
      <div class="row">
        <select id="lf" style="width:auto">${files.map((f) => `<option ${f === logFile ? "selected" : ""}>${esc(f)}</option>`).join("")}</select>
        <button class="btn" id="reload">Reload</button><button class="btn ghost" id="clear">Clear</button>
        <button class="btn ghost danger" id="clear-all" ${files.length ? "" : "disabled"}>Clear all logs</button>
      </div></div>
    <div class="card"><pre class="log" id="log">${files.length ? "Loading…" : "No log files yet"}</pre></div>`;
  const load = (fresh = false) => {
    if (!logFile) return;
    const f = logFile;
    const m = f.match(/^sites\/(.+)-php\.log$/);
    if (m) markLogViewed(m[1]);
    if (fresh) delete CACHE[`log:${f}`];
    cached(`log:${f}`, "read_log", [f], (txt) => {
      const pre = document.getElementById("log");
      if (!pre || logFile !== f) return;
      pre.textContent = txt || "(empty)";
      pre.scrollTop = pre.scrollHeight;
    });
  };
  document.getElementById("lf").onchange = (e) => { logFile = e.target.value; load(); };
  document.getElementById("reload").onclick = () => load(true);
  document.getElementById("clear").onclick = async () => { await act(null, "clear_log", [logFile]); load(true); };
  document.getElementById("clear-all").onclick = async (e) => {
    const btn = e.currentTarget;
    if (!(await confirmDialog("Clear all logs?", `Deletes all ${files.length} log files. Logs that Apache, MySQL or PHP are writing to right now are emptied instead.`, "Clear all"))) return;
    const r = await act(btn, "clear_all_logs");
    if (r) { toast(`Deleted ${r.deleted}, emptied ${r.emptied} log files`); Object.keys(CACHE).forEach((k) => k.startsWith("log:") && delete CACHE[k]); renderLogs(true); }
  };
  load();
}

// ------------------------------------------------------------------ servers

function renderServers() {
  main.innerHTML = `
    <div class="head"><div><h1>Servers</h1><div class="sub">Apache and MySQL: status, ports, how they run and their versions.</div></div>${allButton()}</div>
    ${svcCards()}
    <h2>Ports</h2>
    <form id="ports" class="card pad stack">
      <div class="form-grid">
        <label class="field">HTTP<input type="number" name="http" value="${S.ports.http}"></label>
        <label class="field">HTTPS<input type="number" name="https" value="${S.ports.https}"></label>
        <label class="field">MySQL<input type="number" name="mysql" value="${S.ports.mysql}"></label>
      </div>
      <div class="row between"><span class="muted small">Use 80 / 443 / 3306 once no other local server uses them. Other ports need them in the URL (e.g. https://shop.test:8443).</span>
        <button class="btn primary" type="submit">Save ports</button></div>
    </form>
    <h2>How servers run</h2>
    <div class="grid">
      <label class="opt"><input type="radio" name="mode" value="service" ${S.run_mode === "service" ? "checked" : ""}>
        <span><b>Windows services</b><div class="muted small">Start automatically with Windows. Needs admin.</div></span></label>
      <label class="opt"><input type="radio" name="mode" value="process" ${S.run_mode === "process" ? "checked" : ""}>
        <span><b>Background processes</b><div class="muted small">Start and stop from this app only.</div></span></label>
    </div>
    ${serverVersionsHtml()}`;
  bindLinks();
  bindSvc();
  document.getElementById("ports").onsubmit = async (e) => {
    e.preventDefault();
    const f = e.target;
    if (await act(e.submitter, "set_ports", [+f.http.value, +f.https.value, +f.mysql.value], "Ports saved")) refresh();
  };
  main.querySelectorAll("[name=mode]").forEach((r) => (r.onchange = async () => {
    if (await act(null, "set_run_mode", [r.value], "Run mode changed. Start the services again.")) refresh();
    else refresh();
  }));
  bindServerVersions();
}

// ------------------------------------------------------------------ settings

// Theme: "system" (follow Windows), "dark" or "light". Kept in localStorage; index.html applies it before first paint.
function getTheme() {
  try { return localStorage.getItem("theme") || "system"; } catch { return "system"; }
}

function setTheme(t) {
  try { localStorage.setItem("theme", t); } catch { /* no storage */ }
  if (t === "system") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = t;
}

// Font + scale: also localStorage, applied before first paint by index.html. Empty font = the default Segoe UI stack.
const SCALES = [["compact", "Compact"], ["default", "Default"], ["large", "Large"], ["xlarge", "Extra large"]];

function getPref(key, dflt) {
  try { return localStorage.getItem(key) || dflt; } catch { return dflt; }
}

function setPref(key, v) {
  try { if (v) localStorage.setItem(key, v); else localStorage.removeItem(key); } catch { /* no storage */ }
}

function setFont(f) {
  setPref("font", f);
  if (f) document.documentElement.style.setProperty("--font", JSON.stringify(f) + ", system-ui, sans-serif");
  else document.documentElement.style.removeProperty("--font");
}

function setScale(z) {
  setPref("scale", z === "default" ? "" : z);
  if (z === "default") delete document.documentElement.dataset.scale;
  else document.documentElement.dataset.scale = z;
}

async function bindFontPicker() {
  const sel = document.getElementById("font-sel");
  if (!sel) return;
  const cur = getPref("font", "");
  let list = [];
  try { list = await call("fonts"); } catch { /* keep just the default */ }
  if (cur && !list.includes(cur)) list.unshift(cur);  // saved font was uninstalled: still show it
  sel.innerHTML = `<option value="">Segoe UI (default)</option>` +
    list.filter((f) => f !== "Segoe UI").map((f) => `<option value="${esc(f)}" style="font-family:${esc(JSON.stringify(f))}">${esc(f)}</option>`).join("");
  sel.value = cur;
  sel.disabled = false;
  const reset = document.getElementById("font-reset");
  reset.disabled = !cur;
  sel.onchange = () => { setFont(sel.value); reset.disabled = !sel.value; };
  reset.onclick = () => { sel.value = ""; setFont(""); reset.disabled = true; toast("Font reset to Segoe UI"); };
}

function renderSettings() {
  const theme = getTheme(), scale = getPref("scale", "default");
  main.innerHTML = `
    <div class="head"><div><h1>Settings</h1><div class="sub">Ports, run mode and server versions are on the <a data-go="servers">Servers</a> page.</div></div></div>
    <h2>Appearance</h2>
    <div class="card pad row between">
      <div>Theme<div class="muted small">System follows the Windows light / dark setting.</div></div>
      <div class="seg" id="theme-seg">${[["system", "System"], ["dark", "Dark"], ["light", "Light"]]
        .map(([k, n]) => `<button type="button" data-theme="${k}" class="${theme === k ? "on" : ""}">${n}</button>`).join("")}</div>
    </div>
    <div class="card pad row between" style="margin-top:10px">
      <div>Font<div class="muted small">Any font installed on this PC.</div></div>
      <div class="row"><select id="font-sel" disabled style="min-width:220px"><option>Loading fonts…</option></select>
        <button type="button" class="btn sm" id="font-reset" disabled>Reset</button></div>
    </div>
    <div class="card pad row between" style="margin-top:10px">
      <div>Font size<div class="muted small">Scales text and spacing across the whole window.</div></div>
      <div class="seg" id="scale-seg">${SCALES
        .map(([k, n]) => `<button type="button" data-scale="${k}" class="${scale === k ? "on" : ""}">${n}</button>`).join("")}</div>
    </div>
    ${S.tray ? `<h2>Window</h2>
    <div class="card pad stack">
      <label class="check"><input type="checkbox" id="tray" ${S.close_to_tray ? "checked" : ""}> Closing the window keeps DevStack running in the system tray</label>
      <div class="muted small">Right-click the tray icon to start, stop or restart Apache and MySQL, open a site or quit DevStack.</div>
    </div>` : ""}
    <div class="row between" style="margin:28px 0 10px"><h2 style="margin:0" id="storage-h">Storage</h2>
      <button class="btn" id="recount">Recount</button></div>
    <div id="storage">${storageHtml()}</div>
    <div class="row between" style="margin:28px 0 10px"><h2 style="margin:0">Troubleshoot</h2>
      <button class="btn" id="run-doctor">Run checks</button></div>
    <div id="doctor-results" class="card empty">Checks ports, hosts, certificates, PHP, MySQL and more.</div>`;
  bindLinks();
  const tr = document.getElementById("tray");
  if (tr) tr.onchange = async () => {
    if (await act(null, "set_close_to_tray", [tr.checked], tr.checked ? "Closing now hides DevStack in the tray" : "Closing now quits DevStack")) refresh();
  };
  document.getElementById("run-doctor").onclick = runDoctor;
  document.getElementById("recount").onclick = (e) => { e.target.disabled = true; loadStats(true); };
  loadStats();
  main.querySelectorAll("#theme-seg button").forEach((b) => (b.onclick = () => {
    setTheme(b.dataset.theme);
    main.querySelectorAll("#theme-seg button").forEach((x) => x.classList.toggle("on", x === b));
  }));
  main.querySelectorAll("#scale-seg button").forEach((b) => (b.onclick = () => {
    setScale(b.dataset.scale);
    main.querySelectorAll("#scale-seg button").forEach((x) => x.classList.toggle("on", x === b));
  }));
  bindFontPicker();
}

// Settings -> Storage: space per item (each with its folder), the other folders, then every site's project folder.
function storageHtml() {
  const folders = `<div class="row" style="flex-wrap:wrap;margin-top:14px">
      ${[["DevStack", S.root], ["Config", S.root + "/config"], ["Certificates", S.root + "/ssl"]]
        .map(([n, p]) => `<button class="btn sm" data-path="${esc(p)}">${icon("folder")}${n}</button>`).join("")}</div>`;
  const sz = ST?.sizes;
  if (!sz || sz.projects == null) return `<div class="card pad"><div class="faint small">Counting folder sizes…</div>${folders}</div>`;
  const items = [["Sites", sz.projects, "var(--accent-text)", S.www, "project folders of all sites"],
    ["Databases", sz.mysql, "var(--s3)", S.root + "/data/mysql", "MySQL data folder"],
    ["Apps & programs", sz.bin, "var(--s2)", S.root + "/bin", `Apache, PHP, MySQL${sz.apps != null ? ` · phpMyAdmin ${fmtBytes(sz.apps)}` : ""}`],
    ["Logs", sz.logs, "var(--warn)", S.root + "/logs", `<a data-go="logs">clear logs</a>`],
    ["SQL backups", sz.backups, "var(--s1)", S.root + "/data/exports", "manual + scheduled backups"]].filter((x) => x[1] != null);
  const total = items.reduce((a, x) => a + x[1], 0) || 1;
  const sites = S.sites.map((s) => [s, sz.sites?.[s.name]]).sort((a, b) => (b[1] || 0) - (a[1] || 0));
  const top = Math.max(1, ...sites.map((x) => x[1] || 0));
  return `
    <div class="card pad">
      <div class="row between"><span class="muted small">Total</span><b>${fmtBytes(total)}${sz.counting ? ` <span class="faint small">counting…</span>` : ""}</b></div>
      <div class="ov-bar" style="margin-top:8px">${items.map(([, n, c]) => `<span style="width:${(n / total) * 100}%;background:${c}"></span>`).join("")}</div>
      <table class="compact storage-table" style="margin-top:12px"><tbody>${items.map(([l, n, c, p, sub]) => `
        <tr><td><i class="sw" style="background:${c}"></i>${l}<div class="faint small">${sub}</div></td>
          <td class="r nowrap num"><b>${fmtBytes(n)}</b></td>
          <td class="r" style="width:1%">${iconBtn("folder", "Open folder", `data-path="${esc(p)}"`)}</td></tr>`).join("")}</tbody></table>
      ${folders}
    </div>
    <h3 class="storage-sub">Space per site</h3>
    <div class="card"><table><tbody>${sites.map(([s, n]) => `
      <tr><td><a data-url="${esc(siteLink(s))}">${esc(siteHost(s))}</a>
          <a data-path="${esc(s.root)}" class="mono ellipsis site-path" title="Open ${esc(s.root)}">${esc(s.root)}</a></td>
        <td style="width:30%"><div class="bar"><span style="width:${((n || 0) / top) * 100}%"></span></div></td>
        <td class="r nowrap num" style="width:1%">${fmtBytes(n)}</td></tr>`).join("")}</tbody></table></div>`;
}

function bindStorage() {
  const b = document.getElementById("recount");
  if (b) b.disabled = !!ST?.sizes.counting;
}

function drawMailSettings(m) {
  const box = document.getElementById("mail-settings");
  if (!box) return;
  box.innerHTML = `
    <label class="check"><input type="checkbox" id="mc-enabled" ${m.enabled ? "checked" : ""}> Catch mail from PHP instead of sending it (every installed PHP version)</label>
    <div class="row"><label class="field" style="max-width:120px">Port<input type="number" id="mc-port" min="1" max="65535" value="${m.port}"></label>
      <span class="faint small" style="align-self:end;padding-bottom:9px">${m.enabled ? (m.running ? "Running" : "Not running") : ""}</span></div>
    <div class="faint small">For frameworks that want SMTP settings directly: host <span class="mono">127.0.0.1</span>, port <span class="mono">${esc(String(m.port))}</span>, no encryption, no auth needed.</div>
    <div><button class="btn sm primary" id="mc-save">Save</button></div>`;
  document.getElementById("mc-save").onclick = async (e) => {
    const enabled = document.getElementById("mc-enabled").checked, port = document.getElementById("mc-port").value;
    if (await act(e.target, "set_mail_settings", [enabled, port], "Saved")) { delete CACHE.mail_status; drawMailSettings(await call("mail_status")); }
  };
}

function drawBackupSettings(d) {
  const box = document.getElementById("backup-settings");
  if (!box) return;
  const b = d.backup_settings || { enabled: false, dbs: [], keep: 7 };
  const dbs = d.databases.filter((x) => !x.system);
  box.innerHTML = `
    <label class="check"><input type="checkbox" id="bk-enabled" ${b.enabled ? "checked" : ""}> Back up databases automatically, once every 24 hours</label>
    <div class="row"><label class="field" style="max-width:120px">Keep per database<input type="number" id="bk-keep" min="1" value="${b.keep}"></label></div>
    <div class="faint small">Which databases (none picked = all):</div>
    <div class="ext-grid">${dbs.map((x) => `<label class="check small"><input type="checkbox" data-bkdb="${esc(x.name)}" ${!b.dbs.length || b.dbs.includes(x.name) ? "checked" : ""}>${esc(x.name)}</label>`).join("") || `<span class="faint small">No databases yet</span>`}</div>
    <div><button class="btn sm primary" id="bk-save">Save</button></div>`;
  document.getElementById("bk-save").onclick = async (e) => {
    const all = [...box.querySelectorAll("[data-bkdb]")];
    const picked = all.filter((c) => c.checked).map((c) => c.dataset.bkdb);
    const dbsArg = picked.length === all.length ? [] : picked;   // everything checked = "all" (empty array)
    if (await act(e.target, "set_backup_settings", [document.getElementById("bk-enabled").checked, dbsArg, document.getElementById("bk-keep").value], "Saved"))
      delete CACHE.databases;
  };
}

const STATUS_LABEL = { pass: "OK", warn: "Warning", fail: "Problem" };

async function runDoctor() {
  const btn = document.getElementById("run-doctor");
  const box = document.getElementById("doctor-results");
  box.innerHTML = `<div class="loading">Running checks…</div>`;
  const checks = await act(btn, "doctor");
  if (!checks) return;
  const bad = checks.filter((c) => c.status !== "pass");
  box.outerHTML = `<div id="doctor-results" class="card"><table>
    <thead><tr><th></th><th>Check</th><th>Detail</th><th></th></tr></thead>
    <tbody>${checks.map((c) => `<tr>
      <td><span class="dot ${c.status === "pass" ? "running" : c.status === "warn" ? "starting" : "stopped"}" title="${esc(STATUS_LABEL[c.status])}"></span></td>
      <td>${esc(c.label)}</td>
      <td class="muted small">${esc(c.detail)}</td>
      <td class="r">${c.fix ? `<button class="btn sm" data-fix="${esc(c.fix)}" data-fix-args='${esc(JSON.stringify(c.fix_args))}'>Fix</button>` : ""}</td>
    </tr>`).join("")}</tbody></table></div>`;
  const fresh = document.getElementById("doctor-results");
  fresh.querySelectorAll("[data-fix]").forEach((b) => (b.onclick = async () => {
    const args = JSON.parse(b.dataset.fixArgs || "[]");
    if (await act(b, b.dataset.fix, args, "Done")) runDoctor();
  }));
}

function serverVersionsHtml() {
  const U = S.updates, A = U.apache, M = U.mysql, P = U.pma;
  const folders = (kind, list) => list.length > 1 ? `<div class="small muted" style="margin-top:8px">Installed: ${list.map((x) =>
    `<span class="tag ${x.active ? "accent" : ""}">${esc(x.name)}${x.active ? " · in use" : ""}</span>
     ${x.active ? "" : `${kind === "apache" ? `<a data-use="${esc(x.name)}">use</a> · ` : ""}<a class="bad-text" data-rmsrv="${kind}" data-name="${esc(x.name)}">remove</a>`}`).join(" ")}</div>` : "";
  return `
    <div class="row between" style="margin:28px 0 10px"><h2 style="margin:0">Server versions</h2>
      <div class="row"><span class="faint small">Last checked ${esc(fmtAgo(U.checked))}</span><button class="btn sm" id="check">Check for updates</button></div></div>
    ${Object.keys(U.errors).length ? `<div class="note small bad-text">${Object.entries(U.errors).map(([k, v]) => `${esc(k)}: ${esc(v)}`).join("<br>")}</div>` : ""}
    <div class="stack">
      <div class="card pad">
        <div class="row between">
          <div><b>Apache ${esc(A.version || "")}</b>
            <div class="muted small">${!U.checked ? "Press Check for updates." : A.update
              ? `Apache ${esc(A.latest.version)} is available (Apache Lounge build, with mod_fcgid). Your config is tested with it first; if it doesn't start, DevStack goes back to ${esc(A.version)}.`
              : "Up to date."}</div></div>
          ${A.update ? `<button class="btn hl" id="upd-apache">Update to ${esc(A.latest.version)}</button>` : ""}
        </div>
        ${folders("apache", A.installed)}
      </div>
      <div class="card pad">
        <div class="row between"><div><b>MySQL ${esc(M.version || "")}</b>
          <div class="muted small">${!U.checked ? "Press Check for updates." : M.available.length ? "Newer versions:" : "Up to date."}</div></div></div>
        ${M.available.map((r) => `
          <div class="row between upd-row">
            <div><span class="mono">${esc(r.version)}</span> ${r.lts ? `<span class="tag ok">LTS</span>` : `<span class="tag">Innovation</span>`}
              ${r.recommended ? `<span class="tag accent">recommended</span>` : ""}
              <div class="faint small">${r.lts ? "Long-term support: bug and security fixes only, no surprises." : "Newest features, replaced every few months."}</div></div>
            <button class="btn ${r.recommended ? "hl" : ""}" data-mysql="${esc(r.version)}">Update to ${esc(r.version)}</button>
          </div>`).join("")}
        ${M.available.length ? `<div class="faint small" style="margin-top:8px">About 340 MB download. The data folder is backed up first; MySQL can't be downgraded afterwards (the backup is the way back).</div>` : ""}
        ${folders("mysql", M.installed)}
      </div>
      <div class="card pad">
        <div class="row between">
          <div><b>phpMyAdmin ${esc(P.version || "(not installed)")}</b>
            <div class="muted small">${!U.checked ? "Press Check for updates." : P.update
              ? `phpMyAdmin ${esc(P.latest.version)} is available (released ${esc(P.latest.date || "")}, needs PHP ${esc(P.latest.php_versions || "?")}).
                 The folder is replaced; your login settings are kept.`
              : "Up to date."}
              ${P.update && !P.php_ok ? `<div class="bad-text">localhost.test runs PHP ${esc(P.php)}, outside that range. It may still work; if not, give localhost.test another PHP version on the Sites page.</div>` : ""}</div></div>
          ${P.update ? `<button class="btn hl" id="upd-pma">Update to ${esc(P.latest.version)}</button>` : ""}
        </div>
      </div>
    </div>`;
}

function bindServerVersions() {
  const chk = document.getElementById("check");
  chk.onclick = async () => { if (await act(chk, "check_updates", [], "Version list updated")) refresh(); };
  const ua = document.getElementById("upd-apache");
  if (ua) ua.onclick = async () => {
    const A = S.updates.apache;
    if (await confirmDialog(`Update Apache to ${A.latest.version}?`,
      `Downloads Apache ${esc(A.latest.version)} into its own folder, tests your config with it and switches. Apache restarts once.
       ${esc(A.version)} stays installed, so you can switch back from this page.`, "Update")) startJob(ua, "update_apache");
  };
  const up = document.getElementById("upd-pma");
  if (up) up.onclick = async () => {
    const P = S.updates.pma;
    if (await confirmDialog(`Update phpMyAdmin to ${P.latest.version}?`,
      `Downloads phpMyAdmin ${esc(P.latest.version)} (about 15 MB) and replaces <span class="mono">apps/phpmyadmin</span>.
       Your config is kept; you may need to log in again.`, "Update")) startJob(up, "update_pma");
  };
  main.querySelectorAll("[data-mysql]").forEach((b) => (b.onclick = async () => {
    const v = b.dataset.mysql;
    if (await confirmDialog(`Update MySQL to ${v}?`,
      `1. Downloads MySQL ${esc(v)} (about 340 MB).<br>2. Stops MySQL and copies <span class="mono">data/mysql</span> to a backup folder.<br>
       3. Starts ${esc(v)}, which upgrades your databases.<br><br>If it doesn't start, the backup is restored and ${esc(S.versions.mysql)} runs again.
       Sites can't reach the database for a minute or two.`, "Update")) startJob(b, "update_mysql", [v]);
  }));
  main.querySelectorAll("[data-use]").forEach((a) => (a.onclick = async () => {
    if (await confirmDialog(`Switch to ${a.dataset.use}?`, "Apache restarts with the other version.", "Switch")) startJob(null, "use_apache", [a.dataset.use]);
  }));
  main.querySelectorAll("[data-rmsrv]").forEach((a) => (a.onclick = async () => {
    if (!(await confirmDialog(`Remove ${a.dataset.name}?`, `Deletes the folder <span class="mono">bin/${esc(a.dataset.rmsrv)}/${esc(a.dataset.name)}</span>.`, "Remove"))) return;
    if (await act(null, "remove_server", [a.dataset.rmsrv, a.dataset.name], `${a.dataset.name} removed`)) refresh();
  }));
}

// ------------------------------------------------------------------ boot

// Start-up overlay: blocks the menu until the first state is in (reconcile() can take a while after an update).
const preloadMsg = setTimeout(() => {
  const m = document.getElementById("preload-msg");
  if (m) m.textContent = "Checking configuration and services…";
}, 4000);
function hidePreload() {
  clearTimeout(preloadMsg);
  const el = document.getElementById("preload");
  if (!el) return;
  el.classList.add("done");
  setTimeout(() => el.remove(), 300);
}

window.addEventListener("pywebviewready", () => {
  refresh().finally(hidePreload).then(() => S?.default_php && setTimeout(prefetch, 300));
  pollJobs(true);
  setInterval(async () => {   // keep service dots fresh without redrawing forms
    if (document.getElementById("dialog").open || !S?.services) return;
    try {
      const { services, synced, stamp, php_log_mtimes, mail_count } = await call("status");
      if (synced.length || stamp !== S.stamp) return refresh();   // settings changed outside this window
      const changed = JSON.stringify(services) !== JSON.stringify(S.services);
      S.services = services;
      const badgesChanged = JSON.stringify(php_log_mtimes) !== JSON.stringify(PHP_LOG_MTIMES);
      PHP_LOG_MTIMES = php_log_mtimes;
      const mailChanged = mail_count !== MAIL_COUNT_LAST;
      updateMailBadge(mail_count);
      renderFoot();
      if ((changed || badgesChanged) && ["dashboard", "servers", "database", "sites"].includes(view)) render();
      if (mailChanged && view === "mail") renderMail(true);
    } catch { /* ignore */ }
  }, 5000);
});
