"""Keeps a managed block of *.test entries in the Windows hosts file."""
import re

from . import paths
from .winutil import run

BEGIN = "# >>> DevStack (managed - do not edit inside this block)"
END = "# <<< DevStack"
_BLOCK = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END) + r"\r?\n?", re.S)


def current_domains() -> list[str]:
    try:
        text = paths.HOSTS_FILE.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    m = _BLOCK.search(text)
    if not m:
        return []
    return sorted({ln.split()[1] for ln in m.group(0).splitlines()
                   if ln.strip() and not ln.startswith("#") and len(ln.split()) > 1})


def sync(domains: list[str], aliases: list[str] = ()):
    """Rewrite the managed block. Needs admin rights. `aliases` are added as-is (no automatic www.)."""
    names = []
    for d in domains:
        names += [d, f"www.{d}"]
    names += list(aliases)
    lines = [BEGIN]
    for n in dict.fromkeys(names):
        lines += [f"127.0.0.1  {n}", f"::1        {n}"]
    lines.append(END)
    block = "\r\n".join(lines) + "\r\n"

    raw = paths.HOSTS_FILE.read_bytes()
    text = raw.decode("utf-8", errors="replace")
    if _BLOCK.search(text):
        new = _BLOCK.sub(lambda _: block, text)
    else:
        new = text.rstrip("\r\n") + "\r\n\r\n" + block
    if new == text:
        return
    try:
        paths.HOSTS_FILE.write_bytes(new.encode("utf-8"))
    except PermissionError:
        raise PermissionError("Updating the hosts file needs administrator rights. Run DevStack as administrator.")
    run(["ipconfig", "/flushdns"])
