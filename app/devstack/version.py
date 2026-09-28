"""App version and release notes, both read from CHANGELOG.md (the newest "## x.y.z" heading is the version)."""
import re

from . import paths

_HEAD = re.compile(r"^##\s+(\d+\.\d+\.\d+)\s*(?:[-–—]\s*(\S+))?\s*$")

AUTHOR = "Prajuab Tunyu"
GITHUB = "https://github.com/sillverpro"
COPYRIGHT = AUTHOR   # shown in the About popup; keep in step with LICENSE

# Bundled components shown in the About popup: name, license, link. Installed version(s) are detected at runtime.
COMPONENTS = [
    {"name": "Apache", "license": "Apache-2.0", "url": "https://www.apache.org/licenses/LICENSE-2.0"},
    {"name": "PHP", "license": "PHP License v3.01", "url": "https://www.php.net/license/3_01.txt"},
    {"name": "MySQL", "license": "GPL-2.0", "url": "https://www.gnu.org/licenses/old-licenses/gpl-2.0.html"},
    {"name": "phpMyAdmin", "license": "GPL-2.0", "url": "https://www.gnu.org/licenses/old-licenses/gpl-2.0.html"},
    {"name": "OpenSSL", "license": "Apache-2.0", "url": "https://www.apache.org/licenses/LICENSE-2.0"},
    {"name": "Xdebug", "license": "Xdebug License", "url": "https://xdebug.org/license"},
    {"name": "Composer", "license": "MIT", "url": "https://github.com/composer/composer/blob/main/LICENSE"},
    {"name": "qrcode-generator (Kazuhiko Arase)", "license": "MIT",
     "url": "https://github.com/kazuhikoarase/qrcode-generator/blob/master/LICENSE"},
]


def changelog() -> list[dict]:
    """[{version, date, sections: [{title, items: [str]}]}], newest first."""
    try:
        lines = paths.CHANGELOG.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        m = _HEAD.match(line)
        if m:
            out.append({"version": m[1], "date": m[2] or "", "sections": []})
        elif not out:
            continue
        elif line.startswith("### "):
            out[-1]["sections"].append({"title": line[4:].strip(), "items": []})
        elif line.lstrip().startswith("- "):
            if not out[-1]["sections"]:
                out[-1]["sections"].append({"title": "", "items": []})
            out[-1]["sections"][-1]["items"].append(line.lstrip()[2:].strip())
        elif line.startswith("  ") and line.strip() and out[-1]["sections"] and out[-1]["sections"][-1]["items"]:
            out[-1]["sections"][-1]["items"][-1] += " " + line.strip()   # wrapped bullet
    return out


def current() -> str:
    log = changelog()
    return log[0]["version"] if log else "0.0.0"
