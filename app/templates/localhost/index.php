<?php
$cfgFile = __DIR__ . '/../../config/devstack.json';
$cfg = is_file($cfgFile) ? json_decode(file_get_contents($cfgFile), true) : ['sites' => [], 'ports' => []];
$https = !empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off';
$ports = $cfg['ports'] + ['http' => 80, 'https' => 443, 'mysql' => 3306];

function site_url(array $site, array $ports, bool $https): string {
    $useHttps = $https && !empty($site['ssl']);
    $port = $useHttps ? $ports['https'] : $ports['http'];
    $default = $useHttps ? 443 : 80;
    return ($useHttps ? 'https' : 'http') . '://' . $site['domain'] . ($port == $default ? '' : ":$port") . '/';
}

$mysqlVersion = null;
try {
    $db = @new mysqli('127.0.0.1', 'root', (string) ($cfg['mysql_root_password'] ?? ''), '', (int) $ports['mysql']);
    $mysqlVersion = $db->connect_errno ? null : $db->server_info;
} catch (Throwable $e) {
    $mysqlVersion = null;
}

if (isset($_GET['phpinfo'])) {
    phpinfo();
    exit;
}
$e = fn($s) => htmlspecialchars((string) $s, ENT_QUOTES);
?><!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DevStack</title>
<style>
  :root { --bg:#f6f7f9; --card:#fff; --text:#1d2330; --muted:#6b7280; --line:#e5e7eb; --accent:#4f46e5; }
  @media (prefers-color-scheme: dark) { :root { --bg:#0f1115; --card:#171a21; --text:#e6e8ee; --muted:#9aa1ad; --line:#262a33; --accent:#8b8cf6; } }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--text); font:15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
  main { max-width: 900px; margin: 0 auto; padding: 40px 16px; }
  h1 { font-size: 26px; margin: 0 0 4px; }
  .muted { color: var(--muted); }
  .grid { display:grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap:12px; margin:24px 0; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:14px 16px; }
  .card b { display:block; font-size:18px; }
  a { color: var(--accent); text-decoration: none; }
  a:hover { text-decoration: underline; }
  table { width:100%; border-collapse: collapse; background:var(--card); border:1px solid var(--line); border-radius:10px; overflow:hidden; }
  th, td { text-align:left; padding:10px 14px; border-bottom:1px solid var(--line); }
  th { font-size:12px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted); }
  tr:last-child td { border-bottom: 0; }
  code { font-size: 13px; color: var(--muted); }
  @media (max-width: 600px) { .hide-sm { display:none; } }
</style>
</head>
<body>
<main>
  <h1>DevStack</h1>
  <div class="muted">Local Apache + PHP + MySQL</div>

  <div class="grid">
    <div class="card"><span class="muted">This page runs</span><b>PHP <?= PHP_VERSION ?></b><a href="?phpinfo">phpinfo()</a></div>
    <div class="card"><span class="muted">MySQL</span><b><?= $mysqlVersion ? $e($mysqlVersion) : 'not running' ?></b><span class="muted">127.0.0.1:<?= (int) $ports['mysql'] ?> · root</span></div>
    <div class="card"><span class="muted">Database admin</span><b>phpMyAdmin</b><a href="/phpmyadmin/">Open</a></div>
  </div>

  <table>
    <thead><tr><th>Site</th><th>PHP</th><th class="hide-sm">Folder</th></tr></thead>
    <tbody>
    <?php foreach ($cfg['sites'] as $site): ?>
      <tr>
        <td><a href="<?= $e(site_url($site, $ports, $https)) ?>"><?= $e($site['domain']) ?></a><?= empty($site['ssl']) ? '' : ' 🔒' ?></td>
        <td><?= $e($site['php']) ?></td>
        <td class="hide-sm"><code><?= $e($site['root']) ?></code></td>
      </tr>
    <?php endforeach; ?>
    </tbody>
  </table>
</main>
</body>
</html>
