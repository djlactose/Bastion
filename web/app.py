from datetime import timedelta
from flask import Flask, request, render_template, redirect, url_for, flash, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.datastructures import MultiDict
import os
import time
import base64
import struct
import hashlib
import threading
import urllib.request
import re
import hmac
import json
import socket
import secrets
import subprocess
import logging
from logging.handlers import RotatingFileHandler

# SSH users have a shell in the same container as this app. Everything it
# creates (database, logs, session data) is private to the web user; the one
# file other users need, servers.conf, is explicitly made readable when written.
os.umask(0o077)

app = Flask(__name__)

# Fix #1: File-based persistent SECRET_KEY.
# web/migrate.py (invoked from run.sh before gunicorn starts) rotates an
# under-sized key in place and leaves the previous key at secret_key.old so
# Flask's SECRET_KEY_FALLBACKS can still unsign in-flight sessions and CSRF
# tokens during the grace window.
secret_key_path = '/var/lib/bastion/secret_key'
secret_key_fallback_path = '/var/lib/bastion/secret_key.old'
if os.path.exists(secret_key_path):
    with open(secret_key_path, 'r') as f:
        app.config['SECRET_KEY'] = f.read().strip()
    if os.path.exists(secret_key_fallback_path):
        with open(secret_key_fallback_path, 'r') as f:
            app.config['SECRET_KEY_FALLBACKS'] = [f.read().strip()]
else:
    # Normally web/migrate.py has already created the key before gunicorn
    # starts. This fallback creates it exclusively and with mode 0600 from the
    # start, so it is never world-readable and two workers racing here end up
    # sharing whichever key was written first.
    generated_key = os.urandom(32).hex()
    os.makedirs(os.path.dirname(secret_key_path), exist_ok=True)
    try:
        fd = os.open(secret_key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, generated_key.encode('ascii'))
        finally:
            os.close(fd)
    except FileExistsError:
        with open(secret_key_path, 'r') as f:
            generated_key = f.read().strip() or generated_key
    app.config['SECRET_KEY'] = generated_key

# Database: use persistent volume, auto-migrate from old location
new_db_path = '/var/lib/bastion/users.db'
old_db_path = os.path.join(app.instance_path, 'users.db')
if os.path.exists(old_db_path) and not os.path.exists(new_db_path):
    import shutil
    os.makedirs(os.path.dirname(new_db_path), exist_ok=True)
    shutil.copy2(old_db_path, new_db_path)

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////var/lib/bastion/users.db'
app.config['PERMANENT_SESSION_LIFETIME'] = 1800  # 30 minute session timeout
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Fix #3: CSRF protection
csrf = CSRFProtect(app)

# run.sh only starts nginx (and binds gunicorn to 127.0.0.1) when TLS certs are
# present; otherwise gunicorn is exposed directly on 0.0.0.0:8000.
behind_proxy = os.path.exists('/etc/bastion/certs/fullchain.pem')

class UnixSocketProxyFix:
    """Trust X-Forwarded-For/-Proto only on requests that came from nginx.

    In TLS mode nginx reaches gunicorn over a private Unix socket
    (/run/bastion/gunicorn.sock, see run.sh), while the loopback TCP listener
    stays open for the SSH-tunnelled "Bastion Web Admin" connection. Any SSH
    user can reach that TCP listener, so forwarded headers arriving there are
    client-controlled: honoring them would let a user dodge the login rate
    limit and forge audit-log IPs. Only requests whose transport is the Unix
    socket are passed through ProxyFix. Host/prefix are never trusted because
    nginx passes client-supplied X-Forwarded-Host/-Prefix through untouched.
    """

    def __init__(self, wsgi_app):
        self.direct = wsgi_app
        self.proxied = ProxyFix(wsgi_app, x_for=1, x_proto=1)

    def __call__(self, environ, start_response):
        sock = environ.get('gunicorn.socket')
        if sock is not None and getattr(sock, 'family', None) == socket.AF_UNIX:
            return self.proxied(environ, start_response)
        return self.direct(environ, start_response)


app.wsgi_app = UnixSocketProxyFix(app.wsgi_app)

# Secure cookie settings
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = behind_proxy

# Restricts where scripts, styles, fonts and form posts may go. The templates
# still use inline scripts/handlers and inline styles, so 'unsafe-inline' is
# allowed for now; everything else is limited to this origin and the jsDelivr
# CDN that serves Bootstrap (loaded with Subresource Integrity).
CONTENT_SECURITY_POLICY = '; '.join([
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net",
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net",
    "font-src 'self' https://cdn.jsdelivr.net",
    "img-src 'self' data:",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])

@app.after_request
def set_security_headers(response):
    # Set here (not in nginx) so they also apply in plain-HTTP mode on :8000.
    response.headers.setdefault('X-Frame-Options', 'DENY')
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('Referrer-Policy', 'same-origin')
    # Admin pages (and the one-time authenticator QR code) must not be kept in
    # browser or proxy caches.
    response.headers.setdefault('Cache-Control', 'no-store')
    response.headers.setdefault('Content-Security-Policy', CONTENT_SECURITY_POLICY)
    return response

# Rate limiting
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://",
)

# Audit logging
audit_log_dir = '/var/log/bastion'
os.makedirs(audit_log_dir, exist_ok=True)
audit_logger = logging.getLogger('bastion.audit')
audit_logger.setLevel(logging.INFO)
audit_handler = RotatingFileHandler(
    os.path.join(audit_log_dir, 'audit.log'),
    maxBytes=5 * 1024 * 1024,
    backupCount=5
)
audit_handler.setFormatter(logging.Formatter(
    '%(asctime)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
))
audit_logger.addHandler(audit_handler)

# Optional: also send audit events to a syslog collector (UDP), e.g.
# SYSLOG_ADDRESS=logs.example.com:514. Off unless configured.
_syslog_address = os.environ.get('SYSLOG_ADDRESS', '').strip()
if _syslog_address:
    try:
        from logging.handlers import SysLogHandler
        _syslog_host, _, _syslog_port = _syslog_address.rpartition(':')
        if not _syslog_host:
            _syslog_host, _syslog_port = _syslog_address, '514'
        _syslog_handler = SysLogHandler(address=(_syslog_host, int(_syslog_port)))
        _syslog_handler.setFormatter(logging.Formatter('bastion-audit: %(message)s'))
        audit_logger.addHandler(_syslog_handler)
    except (OSError, ValueError) as exc:
        logging.getLogger(__name__).warning('SYSLOG_ADDRESS ignored: %r', exc)

# Optional: POST selected audit events as JSON to a webhook (chat, pager, SIEM),
# e.g. ALERT_WEBHOOK_URL=https://hooks.example.com/abc. Off unless configured.
ALERT_WEBHOOK_URL = os.environ.get('ALERT_WEBHOOK_URL', '').strip()
if not ALERT_WEBHOOK_URL.startswith(('https://', 'http://')):
    ALERT_WEBHOOK_URL = ''
ALERT_ACTIONS = frozenset({
    'LOGIN_FAILED', 'LOGIN_DENIED_NOT_ADMIN', 'LOGIN_2FA_FAILED', 'SETUP_DENIED_BAD_TOKEN',
    'USER_CREATED', 'USER_DELETED', 'USER_EDITED',
    'SYSTEM_USER_CREATED', 'SYSTEM_USER_DELETED', 'SYSTEM_USER_DISABLED',
    'SYSTEM_USER_2FA_RESET', 'SYSTEM_USER_KEYS_UPDATED',
    'CONFIG_UPDATED', 'CONFIG_IMPORTED', 'TOTP_DISABLED',
})

def _send_alert(payload):
    try:
        req = urllib.request.Request(
            ALERT_WEBHOOK_URL,
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json', 'User-Agent': 'bastion-alert'},
        )
        urllib.request.urlopen(req, timeout=5).close()
    except Exception:  # noqa: BLE001 - an alert must never break the request
        pass

_AUDIT_UNSAFE = re.compile(r'[\x00-\x1f\x7f]')

def _audit_scrub(value):
    """Collapse control characters so an attacker-controlled field can't forge
    a new log line or smuggle tab/backspace/escape sequences into the log."""
    return _AUDIT_UNSAFE.sub('?', str(value))

def audit_log(action, details=''):
    """Log an admin action with the current user context."""
    user = _audit_scrub(current_user.username) if current_user.is_authenticated else 'anonymous'
    ip = request.remote_addr or 'unknown'
    ua = _audit_scrub((request.headers.get('User-Agent') or '-')[:200])
    details = _audit_scrub(details)
    audit_logger.info(
        f'user={user} ip={ip} ua="{ua}" action={action} {details}'.strip()
    )
    if ALERT_WEBHOOK_URL and action in ALERT_ACTIONS:
        payload = {
            'text': f'Bastion: {action} by {user} from {ip} {details}'.strip(),
            'action': action, 'user': user, 'ip': ip, 'details': details,
            'time': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        }
        threading.Thread(target=_send_alert, args=(payload,), daemon=True).start()

# User model
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    # Column added by web/migrate.py for existing DBs; created in-place by
    # db.create_all() for fresh DBs. Default False preserves prior behavior.
    force_password_change = db.Column(db.Boolean, default=False, nullable=False)
    # Server-side session revocation. Sessions are signed cookies, so without
    # this a stolen cookie stays valid after logout or a password change. Once
    # a token is set it is embedded in the session id; rotating it invalidates
    # every outstanding session for the user. Empty means "never rotated", so
    # sessions issued before this column existed keep working (the column is
    # added to existing DBs by web/migrate.py).
    session_token = db.Column(db.String(64), default='', server_default='', nullable=False)
    # Optional two-factor login for this admin (columns added by migrate.py).
    # totp_secret is the base32 secret ('' = not enrolled); totp_recovery is a
    # JSON list of hashed one-time recovery codes; totp_last_step is the last
    # accepted time step, so a code cannot be used twice.
    totp_secret = db.Column(db.String(64), default='', server_default='', nullable=False)
    totp_recovery = db.Column(db.Text, default='', server_default='', nullable=False)
    totp_last_step = db.Column(db.Integer, default=0, server_default='0', nullable=False)

    def get_id(self):
        if self.session_token:
            return f'{self.id}:{self.session_token}'
        return str(self.id)

    def rotate_session_token(self):
        self.session_token = secrets.token_hex(16)

@login_manager.user_loader
def load_user(user_id):
    uid, _, token = str(user_id).partition(':')
    try:
        user = db.session.get(User, int(uid))
    except (TypeError, ValueError):
        return None
    if user is None:
        return None
    # The token in the cookie must match the current one. A cookie without a
    # token is only valid while the user's token has never been rotated.
    if not hmac.compare_digest(user.session_token or '', token):
        return None
    return user

_FORCE_PW_ALLOWED_ENDPOINTS = frozenset({'change_password', 'logout', 'login', 'static'})

# Configuration file paths
config_file = '/etc/bastion/servers.conf'
config_file_json = '/etc/bastion/servers.json'

# Fix #4: Input sanitization for shell-safe values
def sanitize_shell_input(value):
    """Reject input containing shell metacharacters or control characters.

    Control characters are refused as well as newlines: these values are echoed
    to users' terminals by servers.sh, where an escape sequence could rewrite
    what the user sees."""
    dangerous_chars = re.compile(r'[;|&`$(){}\\<>\'"\x00-\x1f\x7f]')
    if dangerous_chars.search(value):
        return None
    return value

_HOST_CHARS = re.compile(r'^[a-zA-Z0-9._-]+$')

def validate_ip_or_hostname(value):
    """Validate that value looks like an IP address or hostname.
    Accepts everything the original character-class check accepted, but caps
    length at the RFC 1035 / 1123 limit and rejects pathological inputs that
    contain consecutive dots (which can't correspond to any real host)."""
    if not value or len(value) > 253:
        return False
    if '..' in value:
        return False
    # servers.sh passes hosts to ssh unquoted; a leading '-' would be parsed
    # as an option.
    if value.startswith('-'):
        return False
    return _HOST_CHARS.match(value) is not None

def validate_port(value):
    """Validate that value is a numeric port."""
    return value.isdigit() and 1 <= int(value) <= 65535

def validate_password(password):
    """Enforce password complexity requirements."""
    if len(password) < 12:
        return False, 'Password must be at least 12 characters long.'
    if not re.search(r'[A-Z]', password):
        return False, 'Password must contain at least one uppercase letter.'
    if not re.search(r'[a-z]', password):
        return False, 'Password must contain at least one lowercase letter.'
    if not re.search(r'[0-9]', password):
        return False, 'Password must contain at least one digit.'
    if not re.search(r'[!@#$%^&*()\-_=+\[\]{};:,.<>?/\\|`~]', password):
        return False, 'Password must contain at least one special character.'
    return True, ''

_WEB_USERNAME_RE = re.compile(r'^[^\s=\x00-\x1f\x7f]{1,150}$')

def validate_web_username(username):
    """Web admin usernames: 1-150 characters, no whitespace, '=' or control
    characters. They are written to the audit log as key=value fields, where
    those characters could forge an entry. Only enforced when a name is created
    or changed, so existing accounts are unaffected."""
    return bool(username) and _WEB_USERNAME_RE.match(username) is not None

WEB_USERNAME_ERROR = "Invalid username. Use 1-150 characters without spaces or '='."

_HOST_CA_RE = re.compile(r'^ssh-ed25519 [A-Za-z0-9+/=]+$')
host_ca_file = '/etc/bastion/ssh_ca.pub'

def read_host_ca():
    """Public key of this install's SSH host CA (published by
    sign-host-keys.sh), or '' when unavailable. Format-checked because it is
    written into the bash-sourced servers.conf."""
    try:
        with open(host_ca_file, 'r') as f:
            line = f.readline().strip()
    except OSError:
        return ''
    return line if _HOST_CA_RE.match(line) else ''

def validate_system_username(username):
    """Validate Linux username format."""
    return re.match(r'^[a-z_][a-z0-9_-]{0,31}$', username) is not None

# Connection types for the web UI dropdowns
CONNECTION_TYPES = [
    ("D", "Portainer Port - port 9000"),
    ("H", "Website Ports - ports 8080, 8443"),
    ("J", "Java Web Ports - ports 8443"),
    ("L", "Linux SSH - port 22"),
    ("M", "Bastion Host SSH - port from base_port"),
    ("N", "Nessus Port - ports 8834, 8000"),
    ("P", "Publish using MSDeploy - port 8172"),
    ("W", "Windows RDP - port 3389"),
    ("S", "SQL Server - port 1433"),
    ("T", "Sysadmin Toolbox"),
    ("X", "SOCKS Proxy - port 5222"),
    ("Y", "Shutdown WSL"),
    ("Z", "Wazuh Port - port 5601"),
    ("B", "Bastion Web Admin - port 8000"),
]
KNOWN_CODES = [ct[0] for ct in CONNECTION_TYPES]

# Menu color themes for servers.sh dialog screens. The value is written into
# the bash-sourced servers.conf, so only whitelisted names are ever accepted.
THEMES = ['default', 'dark', 'blue', 'green', 'red', 'purple', 'cyan', 'amber', 'custom']

# Color names allowed for the 'custom' theme roles. These are the eight ANSI
# colors that exist under the same name in both whiptail (NEWT_COLORS) and
# dialog, and they are written into the bash-sourced servers.conf, so only
# whitelisted names are ever accepted.
THEME_COLORS = ['black', 'red', 'green', 'yellow', 'blue', 'magenta', 'cyan', 'white']

# Custom-theme color roles and their defaults (a dark look).
CUSTOM_COLOR_DEFAULTS = {
    'custom_screen': 'black',
    'custom_bg': 'black',
    'custom_fg': 'white',
    'custom_title': 'yellow',
    'custom_sel_bg': 'yellow',
    'custom_sel_fg': 'black',
}

def parse_config(file_path):
    config = {
        'bastion': [],
        'base_port': 22,
        'name': '',
        'theme': 'default',
        # Off unless the config says otherwise, so installs that predate the
        # setting keep their existing client behavior.
        'verify_host': False,
        'windowsMachines': [],
        'linuxMachines': [],
        'otherMachines': []
    }
    config.update(CUSTOM_COLOR_DEFAULTS)

    # Try JSON first
    if os.path.exists(config_file_json):
        try:
            with open(config_file_json, 'r') as f:
                data = json.load(f)
            config['bastion'] = data.get('bastion', [])
            config['base_port'] = data.get('base_port', 22)
            config['name'] = data.get('name', '')
            theme = data.get('theme', 'default')
            config['theme'] = theme if theme in THEMES else 'default'
            config['verify_host'] = data.get('verify_host') is True
            for field, default in CUSTOM_COLOR_DEFAULTS.items():
                color = data.get(field, default)
                config[field] = color if color in THEME_COLORS else default
            for category in ('windowsMachines', 'linuxMachines', 'otherMachines'):
                machines = data.get(category, [])
                config[category] = [
                    (f"{m['ip']}_{m['connection']}", m['name'])
                    for m in machines
                ]
            return config
        except (json.JSONDecodeError, KeyError):
            pass

    # Fall back to legacy bash format
    if os.path.exists(file_path):
        with open(file_path, 'r') as file:
            lines = file.readlines()
            for line in lines:
                line = line.strip()
                if line.startswith('bastion='):
                    # Fix #11: limit split to first '='
                    bastion_hosts = line.split('=', 1)[1].strip('()').split('" "')
                    config['bastion'] = [host.strip('"') for host in bastion_hosts if host.strip('"')]
                elif line.startswith('base_port='):
                    config['base_port'] = line.split('=', 1)[1]
                elif line.startswith('name='):
                    config['name'] = line.split('=', 1)[1].strip('"')
                elif line.startswith('theme='):
                    theme = line.split('=', 1)[1].strip('"')
                    config['theme'] = theme if theme in THEMES else 'default'
                elif line.startswith('verify_host='):
                    config['verify_host'] = line.split('=', 1)[1].strip('"') == 'yes'
                elif any(line.startswith(field + '=') for field in CUSTOM_COLOR_DEFAULTS):
                    field, _, value = line.partition('=')
                    color = value.strip('"')
                    config[field] = color if color in THEME_COLORS else CUSTOM_COLOR_DEFAULTS[field]
                elif line.startswith('windowsMachines='):
                    content = line.split('=', 1)[1].strip('()')
                    items = content.split('" "')
                    config['windowsMachines'] = [(items[i].strip('" '), items[i+1].strip('" ')) for i in range(0, len(items), 2) if i+1 < len(items)]
                elif line.startswith('linuxMachines='):
                    content = line.split('=', 1)[1].strip('()')
                    items = content.split('" "')
                    config['linuxMachines'] = [(items[i].strip('" '), items[i+1].strip('" ')) for i in range(0, len(items), 2) if i+1 < len(items)]
                elif line.startswith('otherMachines='):
                    content = line.split('=', 1)[1].strip('()')
                    items = content.split('" "')
                    config['otherMachines'] = [(items[i].strip('" '), items[i+1].strip('" ')) for i in range(0, len(items), 2) if i+1 < len(items)]

    return config

# --- Per-user target restrictions ---
#
# An SSH user can be limited to a chosen set of the configured machines. The
# choice is stored in servers.json as {"restrictions": {user: ["ip_CODE", ...]}}
# (a user with no entry is unrestricted) and enforced by the root helper
# restrictions.sh, which is handed the resulting host:port list.

# Ports each connection code forwards to (see doConnection in servers.sh).
# M (a shell on the bastion), X (SOCKS proxy) and Y (WSL shutdown) have no
# fixed destination, so they are not things that can be granted.
RESTRICTION_PORTS = {
    'D': (9000,), 'H': (80, 443), 'J': (8443,), 'L': (22,), 'N': (8834, 8000),
    'P': (8172,), 'W': (3389,), 'S': (1433,), 'T': (5222,), 'Z': (5601,),
}

def machine_targets(ip_conn):
    """(host, port) destinations that the machine entry "ip_CODE" forwards to."""
    ip, _, conn = ip_conn.rpartition('_')
    if conn == 'B':
        # The web admin tunnel always goes to the bastion itself.
        return [('localhost', 8000), ('127.0.0.1', 8000)]
    if conn in RESTRICTION_PORTS:
        ports = RESTRICTION_PORTS[conn]
    elif validate_port(conn):
        ports = (int(conn),)
    else:
        return []
    if not validate_ip_or_hostname(ip):
        return []
    return [(ip, port) for port in ports]

def clean_restrictions(raw, valid_keys=None):
    """Keep only well-formed entries of a restrictions mapping; when valid_keys
    is given, also drop machines that are no longer configured."""
    result = {}
    if not isinstance(raw, dict):
        return result
    for user, entries in raw.items():
        if not isinstance(user, str) or not validate_system_username(user) or not isinstance(entries, list):
            continue
        kept = []
        for entry in entries:
            if isinstance(entry, str) and entry not in kept and (valid_keys is None or entry in valid_keys):
                kept.append(entry)
        result[user] = kept
    return result

def load_restrictions():
    try:
        with open(config_file_json, 'r') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return clean_restrictions(data.get('restrictions')) if isinstance(data, dict) else {}

def save_restrictions(restrictions):
    """Store the restrictions mapping in servers.json, leaving the rest of the
    file as it is. Returns False if the file could not be updated."""
    try:
        with open(config_file_json, 'r') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return False
        if restrictions:
            data['restrictions'] = restrictions
        else:
            data.pop('restrictions', None)
        with open(config_file_json, 'w') as f:
            json.dump(data, f, indent=4)
    except (OSError, ValueError):
        return False
    return True

def sync_restrictions():
    """Hand the current restrictions to the root helper, which rewrites the
    sshd rules and the firewall. Returns (ok, firewall_active)."""
    lines = []
    for user, entries in sorted(load_restrictions().items()):
        targets = sorted({t for entry in entries for t in machine_targets(entry)})
        if not targets:
            lines.append(f'{user} - -')
        for host, port in targets:
            lines.append(f'{user} {host} {port}')
    try:
        result = subprocess.run(['sudo', '/root/bin/restrictions.sh', 'set'],
                                input=''.join(line + '\n' for line in lines),
                                capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        audit_log('RESTRICTIONS_APPLY_FAILED', f'error={e!r}')
        return False, False
    if result.returncode != 0:
        audit_log('RESTRICTIONS_APPLY_FAILED', f'stderr={result.stderr!r}')
        return False, False
    return True, 'firewall=yes' in result.stdout

def restrictions_firewall_active():
    try:
        result = subprocess.run(['sudo', '/root/bin/restrictions.sh', 'status'],
                                capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and 'firewall=yes' in result.stdout

RESTRICTIONS_NO_FIREWALL = ('Port forwarding is restricted, but shell sessions on the bastion are not: the container '
                            'lacks the NET_ADMIN capability. Start it with --cap-add=NET_ADMIN to enforce the list for shell users too.')

def write_json_config(bastion, base_port, name, theme, custom_colors, windows_machines, linux_machines, other_machines, verify_host=False):
    """Write JSON config file alongside the legacy .conf."""
    # Read before the file is rewritten below.
    restrictions = load_restrictions()

    def parse_machine_entries(machine_strs):
        machines = []
        for entry in machine_strs:
            # entries are like '"192.168.1.10_W" "PC One"'
            parts = entry.strip('"').split('" "')
            if len(parts) == 2:
                ip_conn = parts[0]
                mname = parts[1]
                underscore_idx = ip_conn.rfind('_')
                if underscore_idx > 0:
                    machines.append({
                        'ip': ip_conn[:underscore_idx],
                        'connection': ip_conn[underscore_idx+1:],
                        'name': mname
                    })
        return machines

    config_data = {
        'bastion': bastion,
        'base_port': int(base_port),
        'name': name,
        'verify_host': bool(verify_host),
        'theme': theme,
        **custom_colors,
        'windowsMachines': parse_machine_entries(windows_machines),
        'linuxMachines': parse_machine_entries(linux_machines),
        'otherMachines': parse_machine_entries(other_machines)
    }
    # Carry the per-user restrictions over, dropping machines that no longer
    # exist. A restricted user stays restricted even if that leaves them with
    # nothing.
    if restrictions:
        valid_keys = {f"{m['ip']}_{m['connection']}"
                      for category in ('windowsMachines', 'linuxMachines', 'otherMachines')
                      for m in config_data[category]}
        config_data['restrictions'] = clean_restrictions(restrictions, valid_keys)

    with open(config_file_json, 'w') as f:
        json.dump(config_data, f, indent=4)

def migrate_conf_to_json():
    """One-time migration from legacy .conf to .json format."""
    if os.path.exists(config_file) and not os.path.exists(config_file_json):
        config = parse_config(config_file)
        config_data = {
            'bastion': config['bastion'],
            'base_port': int(config['base_port']) if isinstance(config['base_port'], str) else config['base_port'],
            'name': config['name'],
            'verify_host': bool(config.get('verify_host', False)),
            'theme': config.get('theme', 'default'),
        }
        for field, default in CUSTOM_COLOR_DEFAULTS.items():
            config_data[field] = config.get(field, default)
        for category in ('windowsMachines', 'linuxMachines', 'otherMachines'):
            config_data[category] = []
            for m in config[category]:
                underscore_idx = m[0].rfind('_')
                if underscore_idx > 0:
                    config_data[category].append({
                        'ip': m[0][:underscore_idx],
                        'connection': m[0][underscore_idx+1:],
                        'name': m[1]
                    })
        with open(config_file_json, 'w') as f:
            json.dump(config_data, f, indent=4)

# Initialize database (handle race condition with multiple gunicorn workers)
with app.app_context():
    try:
        db.create_all()
    except Exception:
        pass

# Auto-migrate legacy .conf to .json on startup
migrate_conf_to_json()

@app.route('/')
@login_required
def index():
    if not User.query.first():
        return redirect(url_for('setup'))

    config = parse_config(config_file)
    return render_template('index.html', connection_types=CONNECTION_TYPES, known_codes=KNOWN_CODES, themes=THEMES, theme_colors=THEME_COLORS, host_ca_available=bool(read_host_ca()), **config)

@app.route('/ssh-ca.pub')
@limiter.exempt
def ssh_host_ca():
    """Public key of this install's SSH host CA.

    Deliberately unauthenticated: it is a public key, and servers.sh fetches it
    over HTTPS so that a bastion with a publicly trusted TLS certificate can
    anchor its SSH identity in that certificate."""
    ca = read_host_ca()
    if not ca:
        return ('', 404)
    return (ca + '\n', 200, {'Content-Type': 'text/plain; charset=utf-8'})

@app.route('/update', methods=['POST'])
@login_required
def update():
    apply_config_form(request.form)
    return redirect(url_for('index'))

@app.route('/config/export')
@login_required
def export_config():
    """Download the current configuration as JSON (for backup or for copying
    a setup to another bastion)."""
    config = parse_config(config_file)
    data = {
        'bastion': config['bastion'],
        'base_port': int(config['base_port']),
        'name': config['name'],
        'verify_host': bool(config['verify_host']),
        'theme': config['theme'],
    }
    for field in CUSTOM_COLOR_DEFAULTS:
        data[field] = config[field]
    for category in ('windowsMachines', 'linuxMachines', 'otherMachines'):
        data[category] = []
        for ip_conn, mname in config[category]:
            ip, _, conn = ip_conn.rpartition('_')
            data[category].append({'ip': ip, 'connection': conn, 'name': mname})
    restrictions = load_restrictions()
    if restrictions:
        data['restrictions'] = restrictions
    audit_log('CONFIG_EXPORTED')
    return (json.dumps(data, indent=4) + '\n', 200, {
        'Content-Type': 'application/json',
        'Content-Disposition': 'attachment; filename="bastion-config.json"',
    })

MAX_IMPORT_BYTES = 256 * 1024

@app.route('/config/import', methods=['POST'])
@login_required
def import_config():
    """Replace the configuration with an uploaded JSON export.

    The upload is converted into the same fields the configuration form posts
    and goes through apply_config_form(), so an import is validated by exactly
    the same rules as a save from the page and cannot write anything the form
    could not."""
    upload = request.files.get('config_file')
    raw = upload.read(MAX_IMPORT_BYTES + 1) if upload else b''
    if not raw or len(raw) > MAX_IMPORT_BYTES:
        flash('Choose a configuration file to import (maximum 256 KB).', 'danger')
        return redirect(url_for('index'))
    try:
        data = json.loads(raw.decode('utf-8'))
        if not isinstance(data, dict):
            raise ValueError('not an object')
        fields = [
            ('base_port', str(data.get('base_port', 22))),
            ('name', str(data.get('name', ''))),
            ('theme', str(data.get('theme', 'default'))),
        ]
        for host in data.get('bastion', []):
            fields.append(('bastion', str(host)))
        if data.get('verify_host') is True:
            fields.append(('verify_host', 'on'))
        for field, default in CUSTOM_COLOR_DEFAULTS.items():
            fields.append((field, str(data.get(field, default))))
        for category, prefix in (('windowsMachines', 'windows'), ('linuxMachines', 'linux'), ('otherMachines', 'other')):
            for machine in data.get(category, []):
                conn = str(machine['connection'])
                known = conn in KNOWN_CODES
                fields.append((f'{prefix}_ip', str(machine['ip'])))
                fields.append((f'{prefix}_connection', conn if known else 'Other'))
                fields.append((f'{prefix}_other_connection', '' if known else conn))
                fields.append((f'{prefix}_name', str(machine['name'])))
    except (ValueError, KeyError, TypeError, AttributeError, UnicodeDecodeError):
        flash('That file is not a valid Bastion configuration export.', 'danger')
        return redirect(url_for('index'))
    if apply_config_form(MultiDict(fields)):
        audit_log('CONFIG_IMPORTED')
        if current_user.is_admin and isinstance(data.get('restrictions'), dict):
            # Per-user restrictions travel with the export. Only machines that
            # are in the imported configuration can be referenced.
            valid_keys = {key for category in ('windowsMachines', 'linuxMachines', 'otherMachines')
                          for key, _ in parse_config(config_file)[category]}
            existing_users = {u['username'] for u in get_system_users()}
            imported = {user: entries for user, entries in clean_restrictions(data['restrictions'], valid_keys).items()
                        if user in existing_users}
            if save_restrictions(imported):
                ok, firewall = sync_restrictions()
                if not ok:
                    flash('The imported per-user restrictions could not be applied. See audit log for details.', 'danger')
                elif load_restrictions() and not firewall:
                    flash(RESTRICTIONS_NO_FIREWALL, 'warning')
    return redirect(url_for('index'))

def apply_config_form(form):
    """Validate configuration fields and write servers.conf / servers.json.

    `form` is a MultiDict with the field names of the configuration page. Used
    by both the page's Save and by the JSON import. Flashes a message and
    returns False when anything is invalid; nothing is written in that case."""
    bastion = [host for host in form.getlist('bastion') if host.strip()]
    base_port = form['base_port']
    name = form['name']
    theme = form.get('theme', 'default')
    # Checkbox: only ever written to servers.conf as the literal yes/no.
    verify_host = 'verify_host' in form
    host_ca = read_host_ca()
    if verify_host and not host_ca:
        flash('Host verification cannot be enabled: this bastion has no SSH host CA yet. Restart the container and try again.', 'danger')
        return False

    # Fix #4: Validate base_port is numeric
    if not validate_port(base_port):
        flash('Invalid port number.', 'danger')
        return False

    # Whitelist-only: this value is written into the bash-sourced servers.conf.
    if theme not in THEMES:
        flash('Invalid theme selection.', 'danger')
        return False

    # Custom theme colors — whitelist-only for the same reason.
    custom_colors = {}
    for field, default in CUSTOM_COLOR_DEFAULTS.items():
        color = form.get(field, default)
        if color not in THEME_COLORS:
            flash('Invalid theme color selection.', 'danger')
            return False
        custom_colors[field] = color

    # Fix #4: Validate bastion hosts
    for host in bastion:
        if not validate_ip_or_hostname(host):
            flash(f'Invalid bastion host: {host}', 'danger')
            return False

    # Fix #4: Sanitize name
    if sanitize_shell_input(name) is None:
        flash('Name contains invalid characters.', 'danger')
        return False

    windows_ips = form.getlist('windows_ip')
    windows_connections = form.getlist('windows_connection')
    windows_other_connections = form.getlist('windows_other_connection')
    windows_names = form.getlist('windows_name')

    linux_ips = form.getlist('linux_ip')
    linux_connections = form.getlist('linux_connection')
    linux_other_connections = form.getlist('linux_other_connection')
    linux_names = form.getlist('linux_name')

    other_ips = form.getlist('other_ip')
    other_connections = form.getlist('other_connection')
    other_other_connections = form.getlist('other_other_connection')
    other_names = form.getlist('other_name')

    def process_entries(ips, connections, other_connections, names):
        machines = []
        for ip, conn, other_conn, entry_name in zip(ips, connections, other_connections, names):
            if conn == 'Other':
                connection_type = other_conn.strip()
            else:
                connection_type = conn
            if ip.strip() and connection_type and entry_name.strip():
                # Fix #4: Validate each field
                if not validate_ip_or_hostname(ip.strip()):
                    flash(f'Invalid IP/hostname: {ip}', 'danger')
                    return None
                # Either a known code or a bare port number. servers.sh word-splits
                # this value into ssh arguments, so free text could inject options
                # (e.g. "80 -oProxyCommand=...") that run on every client.
                if connection_type not in KNOWN_CODES and not validate_port(connection_type):
                    flash(f'Invalid connection type: {connection_type}', 'danger')
                    return None
                if sanitize_shell_input(entry_name.strip()) is None:
                    flash(f'Invalid machine name: {entry_name}', 'danger')
                    return None
                machines.append('"{}_{}" "{}"'.format(ip.strip(), connection_type, entry_name.strip()))
        return machines

    windows_machines = process_entries(windows_ips, windows_connections, windows_other_connections, windows_names)
    if windows_machines is None:
        return False
    linux_machines = process_entries(linux_ips, linux_connections, linux_other_connections, linux_names)
    if linux_machines is None:
        return False
    other_machines = process_entries(other_ips, other_connections, other_other_connections, other_names)
    if other_machines is None:
        return False

    bastion_str = 'bastion=(' + ' '.join(f'"{host}"' for host in bastion) + ')'
    windows_machines_str = 'windowsMachines=(' + ' '.join(windows_machines) + ')'
    linux_machines_str = 'linuxMachines=(' + ' '.join(linux_machines) + ')'
    other_machines_str = 'otherMachines=(' + ' '.join(other_machines) + ')'

    config_content = f"""#!/bin/bash
############################################
#Bastion Server Address
#NOTE: To load balance enter more than one host in quotes
{bastion_str}
############################################
############################################
#Port to use for Bastion
base_port={base_port}
############################################
############################################
#Name for bastion host to be displayed in menu
name="{name}"
############################################
############################################
#Verify the bastion's identity when connecting (yes/no). host_ca is this
#install's SSH CA public key.
verify_host="{'yes' if verify_host else 'no'}"
host_ca="{host_ca}"
############################################
############################################
#Menu color theme (default, dark, blue, green, red, purple, cyan, amber, custom)
theme="{theme}"
#Custom theme colors (used when theme="custom"; black, red, green, yellow, blue, magenta, cyan, white)
custom_screen="{custom_colors['custom_screen']}"
custom_bg="{custom_colors['custom_bg']}"
custom_fg="{custom_colors['custom_fg']}"
custom_title="{custom_colors['custom_title']}"
custom_sel_bg="{custom_colors['custom_sel_bg']}"
custom_sel_fg="{custom_colors['custom_sel_fg']}"
############################################
# Connection Table
# D = Portainer Port - port 9000
# H = Website Ports - ports 8080, 8443
# J - Java Web Ports - ports 8443
# L = Linux ssh - port 22
# M - Bastion Host ssh - port from base_port
# N = Nessus Port - ports 8834, 8000
# P = Publish using MSDeploy - port 8172
# W = Windows RDP - port 3389
# S = SQL Server - port 1433
# T = Sysadmin Toolbox
# X = SOCKS Proxy - port 5222
# Y = Shutdown WSL
# Z = Wazuh Port - port 5601
# B = Bastion Web Admin - port 8000
# # = Any number will forward that port
############################################
#Windows Machines List
{windows_machines_str}
#Linux Machines List
{linux_machines_str}
#Port Forward Machines List
{other_machines_str}
############################################
"""

    had_restrictions = bool(load_restrictions())

    with open(config_file, 'w') as file:
        file.write(config_content)
    # SSH users download this file through a symlink in their home directory,
    # so it must stay world-readable even though the app runs with umask 077.
    try:
        os.chmod(config_file, 0o644)
    except OSError:
        pass

    # Also write JSON config for structured access
    write_json_config(bastion, base_port, name, theme, custom_colors, windows_machines, linux_machines, other_machines, verify_host)

    audit_log('CONFIG_UPDATED', f'bastion_hosts={len(bastion)} windows={len(windows_machines)} linux={len(linux_machines)} other={len(other_machines)} theme={theme} verify_host={verify_host}')
    flash('Configuration updated successfully!', 'success')
    # Machines may have been removed or changed: bring the enforced per-user
    # restrictions in line. Skipped entirely on installs that have none.
    if had_restrictions:
        ok, _ = sync_restrictions()
        if not ok:
            flash('Per-user target restrictions could not be re-applied. See audit log for details.', 'danger')
    return True

_DUMMY_PASSWORD_HASH = generate_password_hash(os.urandom(16).hex(), method='pbkdf2:sha256')

@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute", methods=["POST"])
def login():
    if not User.query.first():
        return redirect(url_for('setup'))

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()

        # Always run a hash check so response timing doesn't reveal whether
        # the username exists.
        password_ok = check_password_hash(user.password if user else _DUMMY_PASSWORD_HASH, password)
        if user and password_ok:
            if user.is_admin:
                if user.totp_secret:
                    # Password accepted; the session is only signed in after
                    # the second step.
                    session['pending_2fa'] = {'uid': user.id, 'ts': int(time.time())}
                    return redirect(url_for('login_2fa'))
                login_user(user)
                audit_log('LOGIN_SUCCESS', f'username={username}')
                return redirect(url_for('index'))
            else:
                audit_log('LOGIN_DENIED_NOT_ADMIN', f'username={username}')
                flash('Access denied: Only administrators can sign in.', 'danger')
        else:
            audit_log('LOGIN_FAILED', f'username={username}')
            flash('Login Unsuccessful. Please check username and password', 'danger')
    return render_template('login.html')

# --- Two-factor login for web admins (TOTP, RFC 6238) ---

TOTP_PENDING_SECONDS = 300
TOTP_RECOVERY_CODES = 8

def _totp_code(secret_b32, step):
    key = base64.b32decode(secret_b32, casefold=True)
    digest = hmac.new(key, struct.pack('>Q', step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack('>I', digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return f'{number % 1000000:06d}'

def totp_matching_step(secret_b32, code, after_step=0):
    """Return the time step `code` is valid for (one step of clock drift
    either way), or None. Steps at or before `after_step` are refused so a
    code cannot be replayed."""
    code = re.sub(r'\s', '', code or '')
    if not re.fullmatch(r'\d{6}', code):
        return None
    now = int(time.time()) // 30
    for step in (now - 1, now, now + 1):
        if step > after_step and hmac.compare_digest(_totp_code(secret_b32, step), code):
            return step
    return None

def _hash_recovery_code(code):
    return hashlib.sha256(re.sub(r'[\s-]', '', code or '').lower().encode('utf-8')).hexdigest()

def consume_recovery_code(user, code):
    """Use up one of the user's recovery codes. Returns True if it matched."""
    try:
        stored = json.loads(user.totp_recovery) if user.totp_recovery else []
    except ValueError:
        stored = []
    candidate = _hash_recovery_code(code)
    for item in stored:
        if hmac.compare_digest(item, candidate):
            stored.remove(item)
            user.totp_recovery = json.dumps(stored)
            return True
    return False

def _totp_qr_data_uri(username, secret_b32):
    """QR code for an authenticator app, as an inline image. Rendered with the
    qrencode binary already in the image; '' if that fails (the secret is then
    still shown as text)."""
    from urllib.parse import quote
    uri = f'otpauth://totp/Bastion:{quote(username)}?secret={secret_b32}&issuer=Bastion'
    try:
        result = subprocess.run(['qrencode', '-t', 'SVG', '-m', '2', '-o', '-', uri],
                                capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ''
    if result.returncode != 0 or not result.stdout:
        return ''
    return 'data:image/svg+xml;base64,' + base64.b64encode(result.stdout).decode('ascii')

@app.route('/login/2fa', methods=['GET', 'POST'])
@limiter.limit("5 per minute", methods=["POST"])
def login_2fa():
    pending = session.get('pending_2fa')
    if not isinstance(pending, dict) or int(time.time()) - int(pending.get('ts', 0)) > TOTP_PENDING_SECONDS:
        session.pop('pending_2fa', None)
        return redirect(url_for('login'))
    user = db.session.get(User, int(pending.get('uid', 0)))
    if user is None or not user.is_admin or not user.totp_secret:
        session.pop('pending_2fa', None)
        return redirect(url_for('login'))

    if request.method == 'POST':
        code = request.form.get('code', '')
        method = None
        step = totp_matching_step(user.totp_secret, code, user.totp_last_step)
        if step is not None:
            user.totp_last_step = step
            method = 'totp'
        elif consume_recovery_code(user, code):
            method = 'recovery_code'
        if method:
            db.session.commit()
            session.pop('pending_2fa', None)
            login_user(user)
            audit_log('LOGIN_SUCCESS', f'username={user.username} second_factor={method}')
            if method == 'recovery_code':
                flash('You signed in with a recovery code. It cannot be used again.', 'warning')
            return redirect(url_for('index'))
        audit_logger.info(
            f'user=anonymous ip={request.remote_addr or "unknown"} action=LOGIN_2FA_FAILED '
            f'username={_audit_scrub(user.username)}'
        )
        flash('That code is not valid. Try again.', 'danger')
    return render_template('login_2fa.html')

@app.route('/account/2fa', methods=['GET', 'POST'])
@limiter.limit("10 per minute", methods=["POST"])
@login_required
def account_2fa():
    user = db.session.get(User, current_user.id)
    if request.method == 'POST':
        action = request.form.get('action', '')
        if action == 'enable' and not user.totp_secret:
            secret = session.get('totp_enroll', '')
            step = totp_matching_step(secret, request.form.get('code', '')) if secret else None
            if step is None:
                flash('That code is not valid. Scan the QR code and enter the current 6-digit code.', 'danger')
                return redirect(url_for('account_2fa'))
            codes = []
            for _ in range(TOTP_RECOVERY_CODES):
                raw = secrets.token_hex(6)
                codes.append(f'{raw[:6]}-{raw[6:]}')
            user.totp_secret = secret
            user.totp_last_step = step
            user.totp_recovery = json.dumps([_hash_recovery_code(c) for c in codes])
            db.session.commit()
            session.pop('totp_enroll', None)
            audit_log('TOTP_ENABLED')
            return render_template('account_2fa.html', enabled=True, recovery_codes=codes)
        if action == 'disable' and user.totp_secret:
            if not check_password_hash(user.password, request.form.get('current_password', '')):
                flash('Current password is incorrect.', 'danger')
                return redirect(url_for('account_2fa'))
            user.totp_secret = ''
            user.totp_recovery = ''
            user.totp_last_step = 0
            db.session.commit()
            audit_log('TOTP_DISABLED')
            flash('Two-factor login has been turned off for your account.', 'warning')
        return redirect(url_for('account_2fa'))

    if user.totp_secret:
        try:
            remaining = len(json.loads(user.totp_recovery)) if user.totp_recovery else 0
        except ValueError:
            remaining = 0
        return render_template('account_2fa.html', enabled=True, recovery_remaining=remaining)
    secret = session.get('totp_enroll')
    if not secret:
        secret = base64.b32encode(os.urandom(20)).decode('ascii')
        session['totp_enroll'] = secret
    return render_template('account_2fa.html', enabled=False, secret=secret,
                           qr=_totp_qr_data_uri(user.username, secret))

# --- Passkeys for web admins (WebAuthn) ---
#
# An admin can register passkeys and sign in with one instead of password (and
# authenticator code): a passkey that verifies the user (PIN / biometric) is
# two factors in itself. The password remains as a fallback.
#
# A passkey is bound to the address it was registered on (the WebAuthn "RP ID",
# i.e. the host name in the browser's address bar). One registered through the
# SSH tunnel on http://localhost:8000 does not work on https://bastion.example
# and vice versa, so each credential stores its RP ID and is only ever
# verified against that value. The request's own Host header is never trusted
# on its own: an assertion relayed from another site carries that site's RP ID
# hash and fails the check against the stored one.

class WebAuthnCredential(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    credential_id = db.Column(db.String(1024), unique=True, nullable=False)  # base64url
    public_key = db.Column(db.LargeBinary, nullable=False)
    sign_count = db.Column(db.Integer, default=0, nullable=False)
    rp_id = db.Column(db.String(255), nullable=False)
    label = db.Column(db.String(64), default='', nullable=False)
    created = db.Column(db.String(32), default='', nullable=False)

# Create the table on databases that predate it (create_all only adds missing
# tables; tolerate the race between gunicorn workers as above).
with app.app_context():
    try:
        db.create_all()
    except Exception:
        pass

PASSKEY_CHALLENGE_SECONDS = 300
MAX_PASSKEYS_PER_USER = 10

def _webauthn_rp():
    """(rp_id, origin) for the address this request was made to, or (None,
    None) when passkeys cannot work there. Browsers only allow WebAuthn on
    HTTPS or on localhost."""
    host = request.host or ''
    hostname = host.rsplit(':', 1)[0] if not host.startswith('[') else host
    if not hostname or not re.fullmatch(r'[A-Za-z0-9.-]{1,253}', hostname):
        return None, None
    hostname = hostname.lower()
    scheme = request.scheme
    if scheme != 'https' and hostname != 'localhost':
        return None, None
    return hostname, f'{scheme}://{host.lower()}'

def _passkey_challenge(kind):
    """Pop the stored challenge for `kind` if it is still fresh."""
    from webauthn.helpers import base64url_to_bytes
    stored = session.pop('passkey_' + kind, None)
    if not isinstance(stored, dict) or int(time.time()) - int(stored.get('ts', 0)) > PASSKEY_CHALLENGE_SECONDS:
        return None, None
    try:
        return base64url_to_bytes(stored['challenge']), stored.get('rp_id')
    except (KeyError, ValueError, TypeError):
        return None, None

@app.route('/account/passkeys')
@login_required
def account_passkeys():
    rp_id, _ = _webauthn_rp()
    creds = WebAuthnCredential.query.filter_by(user_id=current_user.id).order_by(WebAuthnCredential.id).all()
    return render_template('account_passkeys.html', passkeys=creds, rp_id=rp_id)

@app.route('/account/passkeys/register/options', methods=['POST'])
@limiter.limit("20 per minute")
@login_required
def passkey_register_options():
    from webauthn import generate_registration_options, options_to_json
    from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
    from webauthn.helpers.structs import (AuthenticatorSelectionCriteria, PublicKeyCredentialDescriptor,
                                          ResidentKeyRequirement, UserVerificationRequirement)
    rp_id, _ = _webauthn_rp()
    if rp_id is None:
        return jsonify(error='Passkeys need HTTPS, or the SSH tunnel on http://localhost:8000.'), 400
    existing = WebAuthnCredential.query.filter_by(user_id=current_user.id).all()
    if len(existing) >= MAX_PASSKEYS_PER_USER:
        return jsonify(error=f'You can register at most {MAX_PASSKEYS_PER_USER} passkeys.'), 400
    options = generate_registration_options(
        rp_id=rp_id,
        rp_name='Bastion',
        user_id=str(current_user.id).encode('ascii'),
        user_name=current_user.username,
        exclude_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(c.credential_id))
                             for c in existing if c.rp_id == rp_id],
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
    )
    session['passkey_register'] = {'challenge': bytes_to_base64url(options.challenge),
                                   'rp_id': rp_id, 'ts': int(time.time())}
    return app.response_class(options_to_json(options), mimetype='application/json')

@app.route('/account/passkeys/register/verify', methods=['POST'])
@limiter.limit("20 per minute")
@login_required
def passkey_register_verify():
    from webauthn import verify_registration_response
    from webauthn.helpers import bytes_to_base64url
    rp_id, origin = _webauthn_rp()
    challenge, challenge_rp = _passkey_challenge('register')
    payload = request.get_json(silent=True) or {}
    if rp_id is None or challenge is None or challenge_rp != rp_id or not isinstance(payload.get('credential'), dict):
        return jsonify(error='Registration expired. Try again.'), 400
    try:
        verified = verify_registration_response(
            credential=payload['credential'], expected_challenge=challenge,
            expected_rp_id=rp_id, expected_origin=origin, require_user_verification=True,
        )
    except Exception as exc:  # noqa: BLE001 - the library raises several types
        audit_log('PASSKEY_REGISTER_FAILED', f'reason={type(exc).__name__}')
        return jsonify(error='The passkey could not be verified.'), 400
    credential_id = bytes_to_base64url(verified.credential_id)
    if WebAuthnCredential.query.filter_by(credential_id=credential_id).first():
        return jsonify(error='That passkey is already registered.'), 400
    label = re.sub(r'[\x00-\x1f\x7f]', '', str(payload.get('label', '')))[:64].strip() or 'Passkey'
    db.session.add(WebAuthnCredential(
        user_id=current_user.id, credential_id=credential_id,
        public_key=verified.credential_public_key, sign_count=verified.sign_count,
        rp_id=rp_id, label=label, created=time.strftime('%Y-%m-%d'),
    ))
    db.session.commit()
    audit_log('PASSKEY_REGISTERED', f'rp_id={rp_id}')
    flash(f'Passkey "{label}" registered for {rp_id}.', 'success')
    return jsonify(ok=True)

@app.route('/account/passkeys/delete/<int:id>', methods=['POST'])
@login_required
def passkey_delete(id):
    cred = WebAuthnCredential.query.filter_by(id=id, user_id=current_user.id).first_or_404()
    db.session.delete(cred)
    db.session.commit()
    audit_log('PASSKEY_REMOVED', f'rp_id={cred.rp_id}')
    flash('Passkey removed.', 'success')
    return redirect(url_for('account_passkeys'))

@app.route('/login/passkey/options', methods=['POST'])
@limiter.limit("10 per minute")
def passkey_login_options():
    from webauthn import generate_authentication_options, options_to_json
    from webauthn.helpers import bytes_to_base64url
    from webauthn.helpers.structs import UserVerificationRequirement
    rp_id, _ = _webauthn_rp()
    if rp_id is None:
        return jsonify(error='Passkeys need HTTPS, or the SSH tunnel on http://localhost:8000.'), 400
    # No allow-list: the browser offers whichever of the user's passkeys were
    # registered for this address, and no account names are disclosed.
    options = generate_authentication_options(
        rp_id=rp_id, user_verification=UserVerificationRequirement.REQUIRED)
    session['passkey_login'] = {'challenge': bytes_to_base64url(options.challenge),
                                'rp_id': rp_id, 'ts': int(time.time())}
    return app.response_class(options_to_json(options), mimetype='application/json')

@app.route('/login/passkey/verify', methods=['POST'])
@limiter.limit("10 per minute")
def passkey_login_verify():
    from webauthn import verify_authentication_response
    rp_id, origin = _webauthn_rp()
    challenge, challenge_rp = _passkey_challenge('login')
    payload = request.get_json(silent=True) or {}
    credential = payload.get('credential')
    if rp_id is None or challenge is None or challenge_rp != rp_id or not isinstance(credential, dict):
        return jsonify(error='Sign-in expired. Try again.'), 400
    cred = WebAuthnCredential.query.filter_by(credential_id=str(credential.get('id', ''))).first()
    user = db.session.get(User, cred.user_id) if cred else None
    # The credential is only valid for the address it was registered on.
    if cred is None or user is None or cred.rp_id != rp_id:
        audit_log('LOGIN_FAILED', 'method=passkey reason=unknown_credential')
        return jsonify(error='That passkey is not registered here.'), 400
    try:
        verified = verify_authentication_response(
            credential=credential, expected_challenge=challenge,
            expected_rp_id=cred.rp_id, expected_origin=origin,
            credential_public_key=cred.public_key,
            credential_current_sign_count=cred.sign_count,
            require_user_verification=True,
        )
    except Exception as exc:  # noqa: BLE001 - the library raises several types
        audit_log('LOGIN_FAILED', f'method=passkey username={user.username} reason={type(exc).__name__}')
        return jsonify(error='The passkey could not be verified.'), 400
    if not user.is_admin:
        audit_log('LOGIN_DENIED_NOT_ADMIN', f'username={user.username}')
        return jsonify(error='Only administrators can sign in.'), 403
    cred.sign_count = verified.new_sign_count
    db.session.commit()
    session.pop('pending_2fa', None)
    login_user(user)
    audit_log('LOGIN_SUCCESS', f'username={user.username} method=passkey')
    return jsonify(ok=True, redirect=url_for('index'))

@app.errorhandler(404)
def not_found(e):
    return render_template('login.html'), 404

@app.errorhandler(429)
def ratelimit_handler(e):
    flash('Too many attempts. Please wait before trying again.', 'danger')
    return redirect(url_for('login'))

# Optional first-run protection. On a fresh install whoever reaches /setup
# first becomes the administrator; when the container is started with
# SETUP_TOKEN set, creating that first account also requires the token.
SETUP_TOKEN = os.environ.get('SETUP_TOKEN', '')

@app.route('/setup', methods=['GET', 'POST'])
@limiter.limit("5 per minute", methods=["POST"])
def setup():
    if User.query.first():
        return redirect(url_for('login'))

    token_required = bool(SETUP_TOKEN)
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        confirm_pw = request.form.get('confirm_password', '')
        if token_required and not hmac.compare_digest(
                request.form.get('setup_token', '').encode('utf-8'),
                SETUP_TOKEN.encode('utf-8')):
            audit_log('SETUP_DENIED_BAD_TOKEN')
            flash('Setup token is incorrect.', 'danger')
            return render_template('setup.html', token_required=token_required)
        if not validate_web_username(username):
            flash(WEB_USERNAME_ERROR, 'danger')
            return render_template('setup.html', token_required=token_required)
        if password != confirm_pw:
            flash('Passwords do not match.', 'danger')
            return render_template('setup.html', token_required=token_required)
        valid, msg = validate_password(password)
        if not valid:
            flash(msg, 'danger')
            return render_template('setup.html', token_required=token_required)
        # Fix #10: Check for duplicate username
        if User.query.filter_by(username=username).first():
            flash('Username already exists.', 'danger')
            return render_template('setup.html', token_required=token_required)
        is_admin = True
        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
        user = User(username=username, password=hashed_password, is_admin=is_admin)
        db.session.add(user)
        db.session.commit()
        audit_log('USER_CREATED', f'target_user={username} is_admin=True initial_setup=True')
        flash(f'Admin account created for {username}!', 'success')
        return redirect(url_for('login'))
    return render_template('setup.html', token_required=token_required)

@app.route('/register', methods=['GET', 'POST'])
@login_required
def register():
    if not current_user.is_admin:
        flash('Only administrators can register new users.', 'danger')
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        confirm_pw = request.form.get('confirm_password', '')
        if not validate_web_username(username):
            flash(WEB_USERNAME_ERROR, 'danger')
            return render_template('register.html')
        if password != confirm_pw:
            flash('Passwords do not match.', 'danger')
            return render_template('register.html')
        valid, msg = validate_password(password)
        if not valid:
            flash(msg, 'danger')
            return render_template('register.html')
        # Fix #10: Check for duplicate username
        if User.query.filter_by(username=username).first():
            flash('Username already exists.', 'danger')
            return render_template('register.html')
        is_admin = 'is_admin' in request.form
        force_pw_change = 'force_password_change' in request.form
        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
        user = User(
            username=username,
            password=hashed_password,
            is_admin=is_admin,
            force_password_change=force_pw_change,
        )
        db.session.add(user)
        db.session.commit()
        audit_log(
            'USER_CREATED',
            f'target_user={username} is_admin={is_admin} '
            f'force_password_change={force_pw_change}',
        )
        flash(f'Account created for {username}!', 'success')
        return redirect(url_for('index'))
    return render_template('register.html')

@app.route('/logout', methods=['GET', 'POST'])
def logout():
    # POST only (with the CSRF token), so another site cannot sign an admin
    # out by getting their browser to load a URL. A plain GET, e.g. from an old
    # bookmark, just returns to the app.
    if request.method != 'POST':
        return redirect(url_for('index'))
    if current_user.is_authenticated:
        audit_log('LOGOUT')
        # Invalidate the session server-side as well: the signed cookie would
        # otherwise remain usable until it expired.
        user = db.session.get(User, current_user.id)
        if user is not None:
            user.rotate_session_token()
            db.session.commit()
        logout_user()
    return redirect(url_for('login'))

@app.before_request
def refresh_session():
    session.permanent = True
    app.permanent_session_lifetime = timedelta(minutes=30)

@app.before_request
def enforce_admin_session():
    # Only admins may sign in, but a session outlives a later demotion. Without
    # this, a demoted user could keep using routes that only check
    # @login_required (e.g. /update, which writes the bash-sourced servers.conf).
    if current_user.is_authenticated and not current_user.is_admin:
        audit_log('SESSION_REVOKED_NOT_ADMIN')
        logout_user()
        flash('Access denied: Only administrators can sign in.', 'danger')
        return redirect(url_for('login'))

@app.before_request
def enforce_forced_password_change():
    if not current_user.is_authenticated:
        return
    if not getattr(current_user, 'force_password_change', False):
        return
    if request.endpoint is None or request.endpoint in _FORCE_PW_ALLOWED_ENDPOINTS:
        return
    return redirect(url_for('change_password'))

@app.route('/change-password', methods=['GET', 'POST'])
@limiter.limit("10 per minute", methods=["POST"])
@login_required
def change_password():
    forced = bool(current_user.force_password_change)
    if request.method == 'POST':
        current_pw = request.form['current_password']
        new_pw = request.form['password']
        confirm_pw = request.form.get('confirm_password', '')
        if not check_password_hash(current_user.password, current_pw):
            flash('Current password is incorrect.', 'danger')
            return render_template('change_password.html', forced=forced)
        if new_pw != confirm_pw:
            flash('New passwords do not match.', 'danger')
            return render_template('change_password.html', forced=forced)
        if not new_pw:
            flash('New password cannot be empty.', 'danger')
            return render_template('change_password.html', forced=forced)
        valid, msg = validate_password(new_pw)
        if not valid:
            flash(msg, 'danger')
            return render_template('change_password.html', forced=forced)
        user = db.session.get(User, current_user.id)
        user.password = generate_password_hash(new_pw, method='pbkdf2:sha256')
        was_forced = forced
        user.force_password_change = False
        # End every other session for this account, then re-issue this one
        # under the new token.
        user.rotate_session_token()
        db.session.commit()
        login_user(user)
        audit_log('PASSWORD_CHANGED', f'forced={was_forced}')
        flash('Password changed successfully!', 'success')
        return redirect(url_for('index'))
    return render_template('change_password.html', forced=forced)

@app.route('/users')
@login_required
def list_users():
    if not current_user.is_admin:
        flash('Only administrators can manage users.', 'danger')
        return redirect(url_for('index'))
    users = User.query.all()
    return render_template('users.html', users=users)

@app.route('/users/add', methods=['GET', 'POST'])
@login_required
def add_user():
    if not current_user.is_admin:
        flash('Only administrators can add users.', 'danger')
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        confirm_pw = request.form.get('confirm_password', '')
        if not validate_web_username(username):
            flash(WEB_USERNAME_ERROR, 'danger')
            return render_template('add_user.html')
        if password != confirm_pw:
            flash('Passwords do not match.', 'danger')
            return render_template('add_user.html')
        valid, msg = validate_password(password)
        if not valid:
            flash(msg, 'danger')
            return render_template('add_user.html')
        # Fix #10: Check for duplicate username
        if User.query.filter_by(username=username).first():
            flash('Username already exists.', 'danger')
            return render_template('add_user.html')
        is_admin = 'is_admin' in request.form
        force_pw_change = 'force_password_change' in request.form
        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
        user = User(
            username=username,
            password=hashed_password,
            is_admin=is_admin,
            force_password_change=force_pw_change,
        )
        db.session.add(user)
        db.session.commit()
        audit_log(
            'USER_CREATED',
            f'target_user={username} is_admin={is_admin} '
            f'force_password_change={force_pw_change}',
        )
        flash(f'Account created for {username}!', 'success')
        return redirect(url_for('list_users'))
    return render_template('add_user.html')

@app.route('/users/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_user(id):
    if not current_user.is_admin:
        flash('Only administrators can edit users.', 'danger')
        return redirect(url_for('index'))

    user = User.query.get_or_404(id)
    if request.method == 'POST':
        new_username = request.form['username']
        # Only checked when the name actually changes, so an account created
        # before this rule existed can still be edited.
        if new_username != user.username and not validate_web_username(new_username):
            flash(WEB_USERNAME_ERROR, 'danger')
            return render_template('edit_user.html', user=user)
        # Fix #10: Check for duplicate username (only if changed)
        if new_username != user.username and User.query.filter_by(username=new_username).first():
            flash('Username already exists.', 'danger')
            return render_template('edit_user.html', user=user)
        user.username = new_username
        password_changed = False
        if request.form['password']:
            confirm_pw = request.form.get('confirm_password', '')
            if request.form['password'] != confirm_pw:
                flash('Passwords do not match.', 'danger')
                return render_template('edit_user.html', user=user)
            valid, msg = validate_password(request.form['password'])
            if not valid:
                flash(msg, 'danger')
                return render_template('edit_user.html', user=user)
            user.password = generate_password_hash(request.form['password'], method='pbkdf2:sha256')
            password_changed = True
            # A new password ends every session opened with the old one.
            user.rotate_session_token()
        new_is_admin = 'is_admin' in request.form
        if user.is_admin and not new_is_admin and User.query.filter_by(is_admin=True).count() <= 1:
            flash('Cannot remove admin from the last admin account.', 'danger')
            return render_template('edit_user.html', user=user)
        user.is_admin = new_is_admin
        new_force_pw = 'force_password_change' in request.form
        if new_force_pw and user.id == current_user.id and not user.force_password_change:
            flash('You will be required to change your password on your next request.', 'warning')
        user.force_password_change = new_force_pw
        db.session.commit()
        if password_changed and user.id == current_user.id:
            # Keep the admin who just changed their own password signed in,
            # under the new session token.
            login_user(user)
        audit_log(
            'USER_EDITED',
            f'target_user={user.username} is_admin={user.is_admin} '
            f'password_changed={password_changed} '
            f'force_password_change={user.force_password_change}',
        )
        flash(f'Account updated for {user.username}!', 'success')
        return redirect(url_for('list_users'))
    return render_template('edit_user.html', user=user)

@app.route('/users/delete/<int:id>', methods=['POST'])
@login_required
def delete_user(id):
    if not current_user.is_admin:
        flash('Only administrators can delete users.', 'danger')
        return redirect(url_for('index'))

    user = User.query.get_or_404(id)
    if user.id == current_user.id:
        flash('You cannot delete your own account.', 'danger')
        return redirect(url_for('list_users'))
    if user.is_admin and User.query.filter_by(is_admin=True).count() <= 1:
        flash('Cannot delete the last admin account.', 'danger')
        return redirect(url_for('list_users'))
    audit_log('USER_DELETED', f'target_user={user.username}')
    WebAuthnCredential.query.filter_by(user_id=user.id).delete()
    db.session.delete(user)
    db.session.commit()
    flash(f'Account deleted for {user.username}!', 'success')
    return redirect(url_for('list_users'))

# --- System User Management (SSH Users) ---

# One-time Google Authenticator enrollment QR codes are handed over by
# adduser.sh in this directory (mode 700, owned by www-data; created by run.sh).
QR_DIR = '/var/lib/bastion/qr'

def get_system_users():
    """Read /etc/passwd and return non-system users (UID >= 1000, exclude nobody)."""
    users = []
    try:
        with open('/etc/passwd', 'r') as f:
            for line in f:
                parts = line.strip().split(':')
                if len(parts) >= 6:
                    uid = int(parts[2])
                    if uid >= 1000 and parts[0] != 'nobody':
                        users.append({'username': parts[0], 'uid': uid, 'home': parts[5]})
    except FileNotFoundError:
        pass
    return users

@app.route('/system-users')
@login_required
def list_system_users():
    if not current_user.is_admin:
        flash('Only administrators can manage system users.', 'danger')
        return redirect(url_for('index'))
    users = get_system_users()
    states = get_system_user_states()
    restrictions = load_restrictions()
    for u in users:
        u['state'], u['state_detail'] = states.get(u['username'], ('active', ''))
        u['restricted'] = u['username'] in restrictions
        u['allowed_count'] = len(restrictions.get(u['username'], []))
    return render_template('system_users.html', users=users)

@app.route('/system-users/access/<username>', methods=['GET', 'POST'])
@login_required
def system_user_access(username):
    """Choose which configured machines an SSH user may reach."""
    denied = _require_existing_system_user(username)
    if denied:
        return denied
    config = parse_config(config_file)
    groups = []
    for title, category in (('Windows machines', 'windowsMachines'), ('Linux machines', 'linuxMachines'),
                            ('Port forwards', 'otherMachines')):
        machines = []
        for key, mname in config[category]:
            targets = machine_targets(key)
            if targets and not any(m['key'] == key for g in groups for m in g['machines']) \
                    and not any(m['key'] == key for m in machines):
                machines.append({'key': key, 'name': mname,
                                 'targets': ', '.join(f'{host}:{port}' for host, port in targets)})
        if machines:
            groups.append({'title': title, 'machines': machines})
    restrictions = load_restrictions()

    if request.method == 'POST':
        mode = request.form.get('mode', '')
        if mode == 'restricted':
            valid_keys = {m['key'] for g in groups for m in g['machines']}
            restrictions[username] = [k for k in dict.fromkeys(request.form.getlist('machine')) if k in valid_keys]
        elif mode == 'unrestricted':
            restrictions.pop(username, None)
        else:
            flash('Unknown action.', 'danger')
            return redirect(url_for('system_user_access', username=username))
        if not save_restrictions(restrictions):
            flash('Could not save the restrictions.', 'danger')
            return redirect(url_for('system_user_access', username=username))
        ok, firewall = sync_restrictions()
        if not ok:
            audit_log('SYSTEM_USER_ACCESS_FAILED', f'target_user={username}')
            flash('The restrictions were saved but could not be applied. See audit log for details.', 'danger')
        elif mode == 'restricted':
            audit_log('SYSTEM_USER_ACCESS_RESTRICTED', f'target_user={username} machines={len(restrictions[username])} firewall={firewall}')
            flash(f'"{username}" is limited to {len(restrictions[username])} machine(s). Any open sessions were ended.', 'success')
            if not firewall:
                flash(RESTRICTIONS_NO_FIREWALL, 'warning')
        else:
            audit_log('SYSTEM_USER_ACCESS_UNRESTRICTED', f'target_user={username}')
            flash(f'"{username}" is no longer restricted.', 'success')
        return redirect(url_for('system_user_access', username=username))

    return render_template('system_user_access.html', username=username, groups=groups,
                           restricted=username in restrictions, allowed=restrictions.get(username, []),
                           firewall_active=restrictions_firewall_active())

def get_system_user_states():
    """Map username -> (state, detail) from the account expiry dates, where
    state is 'active', 'disabled', 'expired' or 'expires'. Read through the
    root helper because /etc/shadow is not readable by the web user."""
    states = {}
    try:
        result = subprocess.run(['sudo', '/root/bin/userstate.sh', 'status'],
                                capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return states
    if result.returncode != 0:
        return states
    today = int(time.time()) // 86400
    for line in result.stdout.splitlines():
        name, _, exp = line.partition(' ')
        if not exp.isdigit():
            states[name] = ('active', '')
            continue
        day = int(exp)
        date = time.strftime('%Y-%m-%d', time.gmtime(day * 86400))
        if day <= 1:
            states[name] = ('disabled', '')
        elif day <= today:
            states[name] = ('expired', date)
        else:
            states[name] = ('expires', date)
    return states

def _require_existing_system_user(username):
    """Shared checks for the per-user actions below. Returns an error redirect,
    or None when the caller may proceed."""
    if not current_user.is_admin:
        flash('Only administrators can manage system users.', 'danger')
        return redirect(url_for('index'))
    if not validate_system_username(username):
        flash('Invalid username.', 'danger')
        return redirect(url_for('list_system_users'))
    if not any(u['username'] == username for u in get_system_users()):
        flash(f'System user "{username}" not found.', 'danger')
        return redirect(url_for('list_system_users'))
    return None

@app.route('/system-users/reset-2fa/<username>', methods=['POST'])
@login_required
def reset_system_2fa(username):
    """Issue a new authenticator secret for an SSH user (e.g. lost phone). The
    account, password and home directory are untouched."""
    denied = _require_existing_system_user(username)
    if denied:
        return denied
    result = subprocess.run(['sudo', '/root/bin/reset2fa.sh', username],
                            capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        audit_log('SYSTEM_USER_2FA_RESET_FAILED', f'target_user={username} stderr={result.stderr!r}')
        flash('Failed to reset the authenticator. See audit log for details.', 'danger')
        return redirect(url_for('list_system_users'))
    audit_log('SYSTEM_USER_2FA_RESET', f'target_user={username}')
    flash(f'New authenticator secret issued for "{username}". The old one no longer works.', 'success')
    return redirect(url_for('system_user_qr', username=username))

@app.route('/system-users/state/<username>', methods=['POST'])
@login_required
def set_system_user_state(username):
    """Disable, re-enable or set an expiry date on an SSH user."""
    denied = _require_existing_system_user(username)
    if denied:
        return denied
    action = request.form.get('action', '')
    command = ['sudo', '/root/bin/userstate.sh']
    if action in ('disable', 'enable'):
        command += [action, username]
    elif action == 'expire':
        date = request.form.get('date', '')
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', date):
            flash('Choose an expiry date.', 'danger')
            return redirect(url_for('list_system_users'))
        command += ['expire', username, date]
    else:
        flash('Unknown action.', 'danger')
        return redirect(url_for('list_system_users'))
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        audit_log('SYSTEM_USER_STATE_FAILED', f'target_user={username} action={action} stderr={result.stderr!r}')
        flash('Failed to update the account. See audit log for details.', 'danger')
    elif action == 'disable':
        audit_log('SYSTEM_USER_DISABLED', f'target_user={username}')
        flash(f'"{username}" is disabled and any open sessions were ended.', 'success')
    elif action == 'enable':
        audit_log('SYSTEM_USER_ENABLED', f'target_user={username}')
        flash(f'"{username}" is enabled.', 'success')
    else:
        audit_log('SYSTEM_USER_EXPIRY_SET', f'target_user={username} date={date}')
        flash(f'"{username}" will stop working on {date}.', 'success')
    return redirect(url_for('list_system_users'))

_SSH_KEY_RE = re.compile(
    r'^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp256|ecdsa-sha2-nistp384|ecdsa-sha2-nistp521|'
    r'sk-ssh-ed25519@openssh\.com|sk-ecdsa-sha2-nistp256@openssh\.com) ([A-Za-z0-9+/=]+)(?: ([ -~]*))?$'
)
MAX_SSH_KEYS = 50

def parse_ssh_keys(text):
    """Parse authorized_keys text into a list of key dicts. Lines that are not
    plain "type base64 [comment]" keys (for example ones carrying options) are
    returned with valid=False so the page can show them without touching them."""
    keys = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        m = _SSH_KEY_RE.match(line)
        entry = {'line': line, 'valid': False, 'type': '', 'comment': '', 'fingerprint': '', 'security_key': False}
        if m:
            try:
                blob = base64.b64decode(m.group(2), validate=True)
            except ValueError:
                blob = None
            if blob:
                digest = base64.b64encode(hashlib.sha256(blob).digest()).decode('ascii').rstrip('=')
                entry.update(valid=True, type=m.group(1), comment=m.group(3) or '',
                             fingerprint='SHA256:' + digest,
                             security_key=m.group(1).startswith('sk-'))
        keys.append(entry)
    return keys

@app.route('/system-users/keys/<username>', methods=['GET', 'POST'])
@login_required
def system_user_keys(username):
    """View, add and remove an SSH user's public keys."""
    denied = _require_existing_system_user(username)
    if denied:
        return denied
    result = subprocess.run(['sudo', '/root/bin/userkeys.sh', 'get', username],
                            capture_output=True, text=True, timeout=30)
    keys = parse_ssh_keys(result.stdout if result.returncode == 0 else '')

    if request.method == 'POST':
        action = request.form.get('action', '')
        if any(not k['valid'] for k in keys):
            flash('This user has key lines with options or an unknown format. Edit their authorized_keys file by hand; it was not changed.', 'danger')
            return redirect(url_for('system_user_keys', username=username))
        if action == 'add':
            new_keys = parse_ssh_keys(request.form.get('key', ''))
            if len(new_keys) != 1 or not new_keys[0]['valid']:
                flash('Paste one public key, for example "ssh-ed25519 AAAA... comment". Private keys and key options are not accepted.', 'danger')
                return redirect(url_for('system_user_keys', username=username))
            if any(k['fingerprint'] == new_keys[0]['fingerprint'] for k in keys):
                flash('That key is already authorized for this user.', 'warning')
                return redirect(url_for('system_user_keys', username=username))
            if len(keys) >= MAX_SSH_KEYS:
                flash(f'A user can have at most {MAX_SSH_KEYS} keys.', 'danger')
                return redirect(url_for('system_user_keys', username=username))
            keys.append(new_keys[0])
            detail = f'added={new_keys[0]["fingerprint"]}'
        elif action == 'remove':
            fingerprint = request.form.get('fingerprint', '')
            remaining = [k for k in keys if k['fingerprint'] != fingerprint]
            if len(remaining) == len(keys):
                flash('That key was not found.', 'warning')
                return redirect(url_for('system_user_keys', username=username))
            keys = remaining
            detail = f'removed={fingerprint}'
        else:
            flash('Unknown action.', 'danger')
            return redirect(url_for('system_user_keys', username=username))
        payload = ''.join(k['line'] + '\n' for k in keys)
        write = subprocess.run(['sudo', '/root/bin/userkeys.sh', 'set', username],
                               input=payload, capture_output=True, text=True, timeout=30)
        if write.returncode != 0:
            audit_log('SYSTEM_USER_KEYS_FAILED', f'target_user={username} stderr={write.stderr!r}')
            flash('Failed to update the keys. See audit log for details.', 'danger')
        else:
            audit_log('SYSTEM_USER_KEYS_UPDATED', f'target_user={username} {detail}')
            flash('Keys updated.', 'success')
        return redirect(url_for('system_user_keys', username=username))

    return render_template('system_user_keys.html', username=username, keys=keys)

# --- Activity page ---

SSHD_LOG_FILE = '/var/log/bastion-sshd/sshd.log'

def _tail_lines(path, limit):
    """Last `limit` lines of a text file, newest first. Reads at most the final
    256 KB so a large log cannot tie up a worker."""
    try:
        with open(path, 'rb') as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 262144))
            data = f.read().decode('utf-8', errors='replace')
    except OSError:
        return []
    lines = data.splitlines()
    if size > 262144 and lines:
        lines = lines[1:]  # first line is probably cut in half
    return list(reversed(lines[-limit:]))

def get_ssh_sessions():
    """Currently connected SSH users, from sshd's per-session processes
    ("sshd: alice@pts/0" for a shell, "sshd: alice@notty" for a tunnel)."""
    sessions = []
    try:
        result = subprocess.run(['ps', '-eo', 'etimes=,args='], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return sessions
    for line in result.stdout.splitlines():
        m = re.match(r'\s*(\d+)\s+sshd: ([a-z_][a-z0-9_-]*)@(\S+)', line)
        if m:
            seconds = int(m.group(1))
            sessions.append({
                'username': m.group(2),
                'kind': 'tunnel / command' if m.group(3) == 'notty' else f'shell ({m.group(3)})',
                'duration': f'{seconds // 3600}h {seconds % 3600 // 60:02d}m',
            })
    return sessions

@app.route('/activity')
@login_required
def activity():
    if not current_user.is_admin:
        flash('Only administrators can view activity.', 'danger')
        return redirect(url_for('index'))
    ssh_events = [l for l in _tail_lines(SSHD_LOG_FILE, 2000)
                  if re.search(r'Accepted |Failed |Invalid user|Disconnected from user|authenticating user|'
                               r'authentication failures|expired', l)][:200]
    return render_template('activity.html',
                           sessions=get_ssh_sessions(),
                           audit_lines=_tail_lines(os.path.join(audit_log_dir, 'audit.log'), 200),
                           ssh_events=ssh_events)

@app.route('/system-users/add', methods=['GET', 'POST'])
@login_required
def add_system_user():
    if not current_user.is_admin:
        flash('Only administrators can add system users.', 'danger')
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        confirm_pw = request.form.get('confirm_password', '')

        if not validate_system_username(username):
            flash('Invalid username. Use lowercase letters, digits, hyphens, and underscores only.', 'danger')
            return render_template('add_system_user.html')
        if password != confirm_pw:
            flash('Passwords do not match.', 'danger')
            return render_template('add_system_user.html')
        valid, msg = validate_password(password)
        if not valid:
            flash(msg, 'danger')
            return render_template('add_system_user.html')

        # Check if user already exists
        existing = get_system_users()
        if any(u['username'] == username for u in existing):
            flash(f'System user "{username}" already exists.', 'danger')
            return render_template('add_system_user.html')

        result = subprocess.run(
            ['sudo', '/root/bin/adduser.sh', username],
            input=password, capture_output=True, text=True, timeout=30
        )

        if result.returncode != 0:
            audit_log('SYSTEM_USER_CREATE_FAILED', f'target_user={username} stderr={result.stderr!r}')
            flash('Failed to create system user. See audit log for details.', 'danger')
            return render_template('add_system_user.html')

        audit_log('SYSTEM_USER_CREATED', f'target_user={username}')
        flash(f'System user "{username}" created successfully!', 'success')

        # Check for QR code file
        qr_file = os.path.join(QR_DIR, f'ga_qr_{username}.txt')
        if os.path.exists(qr_file):
            return redirect(url_for('system_user_qr', username=username))
        return redirect(url_for('list_system_users'))

    return render_template('add_system_user.html')

@app.route('/system-users/qr/<username>')
@login_required
def system_user_qr(username):
    if not current_user.is_admin:
        flash('Only administrators can view this page.', 'danger')
        return redirect(url_for('index'))

    if not validate_system_username(username):
        flash('Invalid username.', 'danger')
        return redirect(url_for('list_system_users'))

    qr_file = os.path.join(QR_DIR, f'ga_qr_{username}.txt')
    qr_content = ''
    if os.path.exists(qr_file):
        with open(qr_file, 'r') as f:
            qr_content = f.read()
        os.remove(qr_file)

    return render_template('system_user_qr.html', username=username, qr_content=qr_content)

@app.route('/system-users/delete/<username>', methods=['POST'])
@login_required
def delete_system_user(username):
    if not current_user.is_admin:
        flash('Only administrators can delete system users.', 'danger')
        return redirect(url_for('index'))

    if not validate_system_username(username):
        flash('Invalid username.', 'danger')
        return redirect(url_for('list_system_users'))

    result = subprocess.run(
        ['sudo', '/root/bin/deluser.sh', username],
        capture_output=True, text=True, timeout=30
    )

    if result.returncode != 0:
        audit_log('SYSTEM_USER_DELETE_FAILED', f'target_user={username} stderr={result.stderr!r}')
        flash('Failed to delete system user. See audit log for details.', 'danger')
    else:
        audit_log('SYSTEM_USER_DELETED', f'target_user={username}')
        flash(f'System user "{username}" deleted successfully!', 'success')
        # So a later account with the same name does not inherit the list.
        restrictions = load_restrictions()
        if username in restrictions:
            del restrictions[username]
            if save_restrictions(restrictions):
                sync_restrictions()

    return redirect(url_for('list_system_users'))

@app.route('/system-users/reset-password/<username>', methods=['GET', 'POST'])
@login_required
def reset_system_password(username):
    if not current_user.is_admin:
        flash('Only administrators can reset passwords.', 'danger')
        return redirect(url_for('index'))

    if not validate_system_username(username):
        flash('Invalid username.', 'danger')
        return redirect(url_for('list_system_users'))

    # Verify user exists
    existing = get_system_users()
    if not any(u['username'] == username for u in existing):
        flash(f'System user "{username}" not found.', 'danger')
        return redirect(url_for('list_system_users'))

    if request.method == 'POST':
        password = request.form['password']
        confirm_pw = request.form.get('confirm_password', '')

        if password != confirm_pw:
            flash('Passwords do not match.', 'danger')
            return render_template('reset_system_password.html', username=username)
        valid, msg = validate_password(password)
        if not valid:
            flash(msg, 'danger')
            return render_template('reset_system_password.html', username=username)

        result = subprocess.run(
            ['sudo', '/root/bin/resetpw.sh', username],
            input=password, capture_output=True, text=True, timeout=30
        )

        if result.returncode != 0:
            audit_log('SYSTEM_USER_PASSWORD_RESET_FAILED', f'target_user={username} stderr={result.stderr!r}')
            flash('Failed to reset password. See audit log for details.', 'danger')
            return render_template('reset_system_password.html', username=username)

        audit_log('SYSTEM_USER_PASSWORD_RESET', f'target_user={username}')
        flash(f'Password reset for "{username}" successfully!', 'success')
        return redirect(url_for('list_system_users'))

    return render_template('reset_system_password.html', username=username)

if __name__ == '__main__':
    app.run()
