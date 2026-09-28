"""Minimal local SMTP server that saves every message to data/mail/<ts>-<id>.eml instead of sending it.

Stdlib only (the `smtpd` module is gone in 3.13): a small socketserver-based SMTP that understands
EHLO/HELO, MAIL, RCPT, DATA, RSET, NOOP, QUIT, and accepts AUTH PLAIN/LOGIN with any credentials
(so frameworks configured with an SMTP user still connect - nothing here checks them).
"""
import base64
import email
import email.policy
import re
import socketserver
import threading
import time
import uuid

from . import paths

_server = None
_thread = None
_lock = threading.Lock()


class _SMTPHandler(socketserver.StreamRequestHandler):
    timeout = 60

    def _send(self, line):
        self.wfile.write((line + "\r\n").encode("utf-8", "replace"))

    def _line(self) -> str | None:
        raw = self.rfile.readline()
        if not raw:
            return None
        return raw.decode("utf-8", "replace").rstrip("\r\n")

    def handle(self):
        self._send("220 devstack.test ESMTP DevStack mail catcher")
        mail_from, rcpt_to = None, []
        while True:
            text = self._line()
            if text is None:
                return
            cmd = text.split(" ", 1)[0].upper() if text else ""
            if cmd in ("EHLO", "HELO"):
                self._send("250-devstack.test")
                self._send("250-AUTH PLAIN LOGIN")
                self._send("250 8BITMIME")
            elif cmd == "AUTH":
                mech = text.split(" ")[1].upper() if len(text.split(" ")) > 1 else ""
                if mech == "PLAIN" and len(text.split(" ")) < 3:   # PHPMailer sends the credentials on the next line
                    self._send("334 ")
                    if self._line() is None:
                        return
                elif mech == "LOGIN":
                    self._send("334 " + base64.b64encode(b"Username:").decode())
                    if self._line() is None:
                        return
                    self._send("334 " + base64.b64encode(b"Password:").decode())
                    if self._line() is None:
                        return
                self._send("235 2.7.0 Authentication successful")   # accepted, whatever the creds were
            elif cmd == "MAIL":
                m = re.search(r"FROM:\s*<([^>]*)>", text, re.I)
                mail_from = m.group(1) if m else ""
                self._send("250 OK")
            elif cmd == "RCPT":
                m = re.search(r"TO:\s*<([^>]*)>", text, re.I)
                if m:
                    rcpt_to.append(m.group(1))
                self._send("250 OK")
            elif cmd == "DATA":
                self._send("354 End data with <CR><LF>.<CR><LF>")
                lines = []
                while True:
                    raw = self.rfile.readline()
                    if not raw:
                        return
                    if raw in (b".\r\n", b".\n"):
                        break
                    if raw.startswith(b".."):
                        raw = raw[1:]
                    lines.append(raw)
                save_message(b"".join(lines))
                self._send("250 OK: queued")
                mail_from, rcpt_to = None, []
            elif cmd == "RSET":
                mail_from, rcpt_to = None, []
                self._send("250 OK")
            elif cmd == "NOOP":
                self._send("250 OK")
            elif cmd == "QUIT":
                self._send("221 Bye")
                return
            else:
                self._send("500 unrecognized command")


class _Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = False   # on Windows SO_REUSEADDR would let two servers share the port silently
    daemon_threads = True


def save_message(raw: bytes) -> str:
    paths.MAIL_DIR.mkdir(parents=True, exist_ok=True)
    mid = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    (paths.MAIL_DIR / f"{mid}.eml").write_bytes(raw)
    return mid


def start(host="127.0.0.1", port=1025):
    """(Re)start the server on a host/port. Safe to call again with a different port."""
    global _server, _thread
    with _lock:
        _stop_locked()
        _server = _Server((host, port), _SMTPHandler)
        _thread = threading.Thread(target=_server.serve_forever, daemon=True, name="mailcatch")
        _thread.start()


def _stop_locked():
    global _server, _thread
    if _server:
        _server.shutdown()
        _server.server_close()
        _server = None
        _thread = None


def stop():
    with _lock:
        _stop_locked()


def running() -> bool:
    return _server is not None


# ---------------------------------------------------------------- reading saved mail (Mail page)

def _file(mid: str):
    f = paths.MAIL_DIR / f"{mid}.eml"
    if f.parent != paths.MAIL_DIR or not f.is_file():
        raise ValueError("Message not found")
    return f


def _parse(f):
    with open(f, "rb") as fh:
        return email.message_from_binary_file(fh, policy=email.policy.default)


def list_messages() -> list[dict]:
    if not paths.MAIL_DIR.is_dir():
        return []
    out = []
    for f in sorted(paths.MAIL_DIR.glob("*.eml"), key=lambda f: f.stat().st_mtime, reverse=True):
        try:
            msg = _parse(f)
        except Exception:
            continue
        out.append({"id": f.stem, "date": f.stat().st_mtime, "from": str(msg.get("From", "")),
                    "to": str(msg.get("To", "")), "subject": str(msg.get("Subject", "(no subject)")),
                    "size": f.stat().st_size})
    return out


def read_message(mid: str) -> dict:
    f = _file(mid)
    msg = _parse(f)
    text = html = None
    attachments = []
    for i, part in enumerate(msg.walk()):
        if part.is_multipart():
            continue
        ctype = part.get_content_type()
        disp = part.get_content_disposition()
        if disp == "attachment" or (part.get_filename() and ctype not in ("text/plain", "text/html")):
            payload = part.get_payload(decode=True) or b""
            attachments.append({"index": i, "filename": part.get_filename() or f"attachment-{i}",
                                "type": ctype, "size": len(payload)})
        elif ctype == "text/plain" and text is None:
            text = part.get_content()
        elif ctype == "text/html" and html is None:
            html = part.get_content()
    return {"id": mid, "date": f.stat().st_mtime, "from": str(msg.get("From", "")), "to": str(msg.get("To", "")),
            "cc": str(msg.get("Cc", "")), "subject": str(msg.get("Subject", "(no subject)")), "size": f.stat().st_size,
            "text": text, "html": html, "attachments": attachments,
            "headers": [[k, str(v)] for k, v in msg.items()]}


def read_attachment(mid: str, index: int) -> tuple[str, bytes]:
    msg = _parse(_file(mid))
    parts = list(msg.walk())
    if index < 0 or index >= len(parts):
        raise ValueError("Attachment not found")
    part = parts[index]
    return part.get_filename() or f"attachment-{index}", part.get_payload(decode=True) or b""


def delete_message(mid: str):
    _file(mid).unlink()


def clear_all() -> int:
    if not paths.MAIL_DIR.is_dir():
        return 0
    files = list(paths.MAIL_DIR.glob("*.eml"))
    for f in files:
        f.unlink()
    return len(files)
