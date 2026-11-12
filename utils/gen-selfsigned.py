"""Generate a self-signed TLS certificate for the web interface.

Run by run.sh when TLS_SELF_SIGNED=true and no certificate has been supplied in
/etc/bastion/certs/. Browsers will warn about the certificate (it is not
issued by a public authority), but traffic to the web interface is encrypted.
Replace the two files with a real certificate at any time.
"""
import datetime
import ipaddress
import os
import socket
import sys

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

CERT_DIR = '/etc/bastion/certs'
CERT = os.path.join(CERT_DIR, 'fullchain.pem')
KEY = os.path.join(CERT_DIR, 'privkey.pem')


def main() -> int:
    if os.path.exists(CERT) or os.path.exists(KEY):
        return 0
    names = {'localhost', socket.gethostname()}
    for extra in os.environ.get('TLS_SELF_SIGNED_NAMES', '').split(','):
        if extra.strip():
            names.add(extra.strip())
    sans = []
    for name in sorted(names):
        try:
            sans.append(x509.IPAddress(ipaddress.ip_address(name)))
        except ValueError:
            sans.append(x509.DNSName(name))
    sans.append(x509.IPAddress(ipaddress.ip_address('127.0.0.1')))

    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Bastion (self-signed)')])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=825))
        .add_extension(x509.SubjectAlternativeName(sans), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    os.makedirs(CERT_DIR, mode=0o755, exist_ok=True)
    fd = os.open(KEY, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as f:
        f.write(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ))
    fd = os.open(CERT, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(fd, 'wb') as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    print(f'Generated a self-signed TLS certificate in {CERT_DIR}')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 - never block container start
        print(f'WARNING: could not generate a self-signed certificate: {exc!r}', file=sys.stderr)
        sys.exit(0)
