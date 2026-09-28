"""Local certificate authority and per-site certificates (mkcert-style)."""
import datetime as dt
import ipaddress
import time

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from . import paths
from .winutil import run

CA_NAME = "DevStack Local CA"


def _now():
    return dt.datetime.now(dt.timezone.utc)


def _write_key(key, path):
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                       serialization.NoEncryption()))


def _load_ca():
    key = serialization.load_pem_private_key(paths.CA_KEY.read_bytes(), None)   # ~90 ms: only when signing
    return _ca_cert(), key


_cert_cache = {"stamp": None, "cert": None}
_trust_cache = {"tp": None, "at": 0.0, "trusted": False}
TRUST_TTL = 60   # certutil takes ~50 ms per store; the UI asks on every state call


def _ca_cert():
    """The CA certificate (no private key), parsed again only when the file changes."""
    stamp = paths.CA_CRT.stat().st_mtime_ns
    if _cert_cache["stamp"] != stamp:
        _cert_cache.update(stamp=stamp, cert=x509.load_pem_x509_certificate(paths.CA_CRT.read_bytes()))
    return _cert_cache["cert"]


def ensure_ca() -> bool:
    """Create the CA if missing. Returns True when a new CA was created."""
    if paths.CA_CRT.exists() and paths.CA_KEY.exists():
        return False
    paths.CA_CRT.parent.mkdir(parents=True, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, CA_NAME),
                      x509.NameAttribute(NameOID.ORGANIZATION_NAME, "DevStack")])
    ski = x509.SubjectKeyIdentifier.from_public_key(key.public_key())
    cert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(_now() - dt.timedelta(days=1))
            .not_valid_after(_now() + dt.timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True,
                                         content_commitment=False, key_encipherment=False, data_encipherment=False,
                                         key_agreement=False, encipher_only=False, decipher_only=False), critical=True)
            .add_extension(ski, critical=False)
            .sign(key, hashes.SHA256()))
    _write_key(key, paths.CA_KEY)
    paths.CA_CRT.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return True


def ca_thumbprint() -> str:
    return _ca_cert().fingerprint(hashes.SHA1()).hex()


def is_ca_trusted() -> bool:
    if not paths.CA_CRT.exists():
        return False
    tp = ca_thumbprint()
    c = _trust_cache
    if c["tp"] == tp and time.time() - c["at"] < TRUST_TTL:
        return c["trusted"]
    trusted = any(run(["certutil", *scope, "-store", "Root", tp]).returncode == 0 for scope in ([], ["-user"]))
    c.update(tp=tp, at=time.time(), trusted=trusted)
    return trusted


def trust_ca(machine: bool):
    """Add the CA to Windows' trusted roots. Machine store needs admin; user store shows a Windows prompt."""
    scope = [] if machine else ["-user"]
    r = run(["certutil", *scope, "-addstore", "Root", str(paths.CA_CRT)])
    if r.returncode != 0:
        raise RuntimeError("certutil failed: " + (r.stdout + r.stderr).strip())
    _trust_cache["tp"] = None


def untrust_ca():
    tp = ca_thumbprint()
    for scope in ([], ["-user"]):
        run(["certutil", *scope, "-delstore", "Root", tp])
    _trust_cache["tp"] = None


def cert_paths(domain: str):
    return paths.SITE_CERTS / f"{domain}.crt", paths.SITE_CERTS / f"{domain}.key"


def issue(domain: str, extra_names: list[str] = ()):
    """(Re)issue a certificate for domain and *.domain signed by the local CA."""
    ensure_ca()
    ca_cert, ca_key = _load_ca()
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    names = [domain, f"*.{domain}", *extra_names]
    san = []
    for n in dict.fromkeys(names):
        try:
            san.append(x509.IPAddress(ipaddress.ip_address(n)))
        except ValueError:
            san.append(x509.DNSName(n))
    cert = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, domain)]))
            .issuer_name(ca_cert.subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(_now() - dt.timedelta(days=1))
            .not_valid_after(_now() + dt.timedelta(days=825))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, key_encipherment=True, content_commitment=False,
                                         data_encipherment=False, key_agreement=False, key_cert_sign=False,
                                         crl_sign=False, encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.SubjectAlternativeName(san), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256()))
    crt, keyfile = cert_paths(domain)
    crt.parent.mkdir(parents=True, exist_ok=True)
    _write_key(key, keyfile)
    crt.write_bytes(cert.public_bytes(serialization.Encoding.PEM) + ca_cert.public_bytes(serialization.Encoding.PEM))


def ensure_site_cert(domain: str, extra_names: list[str] = ()):
    crt, key = cert_paths(domain)
    wanted = {domain, f"*.{domain}", *extra_names}   # same names issue() puts in the cert
    if crt.exists() and key.exists():
        cert = x509.load_pem_x509_certificate(crt.read_bytes())
        current = set(_names(cert))
        if cert.not_valid_after_utc - _now() > dt.timedelta(days=30) and current == wanted:
            return
    issue(domain, extra_names)


def remove_site_cert(domain: str):
    for p in cert_paths(domain):
        p.unlink(missing_ok=True)


# ---------------------------------------------------------------- info for the Certificates page

def _names(cert) -> list[str]:
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except x509.ExtensionNotFound:
        return []
    return [str(n.value) for n in san]


def ca_info() -> dict | None:
    if not paths.CA_CRT.exists():
        return None
    cert = _ca_cert()
    return {
        "name": cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value,
        "fingerprint": cert.fingerprint(hashes.SHA1()).hex(":").upper(),
        "expires": cert.not_valid_after_utc.timestamp(),
        "days_left": (cert.not_valid_after_utc - _now()).days,
        "trusted": is_ca_trusted(),
        "path": paths.fwd(paths.CA_CRT),
    }


def cert_info(domain: str, ca_cert=None) -> dict:
    crt, key = cert_paths(domain)
    if not (crt.exists() and key.exists()):
        return {"domain": domain, "state": "missing"}
    cert = x509.load_pem_x509_certificate(crt.read_bytes())
    days = (cert.not_valid_after_utc - _now()).days
    try:
        cert.verify_directly_issued_by(ca_cert)
        ours = True
    except Exception:
        ours = False
    state = ("expired" if days < 0 else "foreign" if not ours else "expiring" if days < 30 else "ok")
    return {"domain": domain, "state": state, "names": _names(cert), "days_left": days,
            "issued": cert.not_valid_before_utc.timestamp(), "expires": cert.not_valid_after_utc.timestamp(),
            "path": paths.fwd(crt)}


def list_certs(domains: list[str]) -> dict:
    """Certificates for the given site domains, plus leftover files of sites that no longer exist."""
    ca_cert = _ca_cert() if paths.CA_CRT.exists() else None
    sites = [cert_info(d, ca_cert) for d in domains]
    orphans = sorted({f.stem for f in paths.SITE_CERTS.glob("*.crt")} - set(domains))
    return {"sites": sites, "orphans": orphans}
