from datetime import timedelta
from flask import Flask, request, render_template, redirect, url_for, flash, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix
import os
import re
import json
import subprocess
import logging
from logging.handlers import RotatingFileHandler

app = Flask(__name__)

# Fix #1: File-based persistent SECRET_KEY
secret_key_path = '/root/bastion/secret_key'
if os.path.exists(secret_key_path):
    with open(secret_key_path, 'r') as f:
        app.config['SECRET_KEY'] = f.read().strip()
else:
    generated_key = os.urandom(24).hex()
    os.makedirs(os.path.dirname(secret_key_path), exist_ok=True)
    with open(secret_key_path, 'w') as f:
        f.write(generated_key)
    app.config['SECRET_KEY'] = generated_key

# Database: use persistent volume, auto-migrate from old location
new_db_path = '/root/bastion/users.db'
old_db_path = os.path.join(app.instance_path, 'users.db')
if os.path.exists(old_db_path) and not os.path.exists(new_db_path):
    import shutil
    os.makedirs(os.path.dirname(new_db_path), exist_ok=True)
    shutil.copy2(old_db_path, new_db_path)

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////root/bastion/users.db'
app.config['PERMANENT_SESSION_LIFETIME'] = 1800  # 30 minute session timeout
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Fix #3: CSRF protection
csrf = CSRFProtect(app)

# ProxyFix for nginx reverse proxy (safe no-op without nginx)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# Secure cookie settings
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

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

def audit_log(action, details=''):
    """Log an admin action with the current user context."""
    user = current_user.username if current_user.is_authenticated else 'anonymous'
    ip = request.remote_addr or 'unknown'
    audit_logger.info(f'user={user} ip={ip} action={action} {details}'.strip())

# User model
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Configuration file paths
config_file = '/etc/bastion/servers.conf'
config_file_json = '/etc/bastion/servers.json'

# Fix #4: Input sanitization for shell-safe values
def sanitize_shell_input(value):
    """Reject input containing shell metacharacters."""
    dangerous_chars = re.compile(r'[;|&`$(){}\\<>\n\r\'"]')
    if dangerous_chars.search(value):
        return None
    return value

def validate_ip_or_hostname(value):
    """Validate that value looks like an IP address or hostname."""
    pattern = re.compile(r'^[a-zA-Z0-9._-]+$')
    return pattern.match(value) is not None

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

def parse_config(file_path):
    config = {
        'bastion': [],
        'base_port': 22,
        'name': '',
        'windowsMachines': [],
        'linuxMachines': [],
        'otherMachines': []
    }

    # Try JSON first
    if os.path.exists(config_file_json):
        try:
            with open(config_file_json, 'r') as f:
                data = json.load(f)
            config['bastion'] = data.get('bastion', [])
            config['base_port'] = data.get('base_port', 22)
            config['name'] = data.get('name', '')
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

def write_json_config(bastion, base_port, name, windows_machines, linux_machines, other_machines):
    """Write JSON config file alongside the legacy .conf."""
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
        'windowsMachines': parse_machine_entries(windows_machines),
        'linuxMachines': parse_machine_entries(linux_machines),
        'otherMachines': parse_machine_entries(other_machines)
    }

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
        }
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

# Fix #2: Initialize database once at startup instead of every request
with app.app_context():
    db.create_all()

# Auto-migrate legacy .conf to .json on startup
migrate_conf_to_json()

@app.route('/')
@login_required
def index():
    if not User.query.first():
        return redirect(url_for('setup'))

    config = parse_config(config_file)
    return render_template('index.html', connection_types=CONNECTION_TYPES, known_codes=KNOWN_CODES, **config)

@app.route('/update', methods=['POST'])
@login_required
def update():
    bastion = [host for host in request.form.getlist('bastion') if host.strip()]
    base_port = request.form['base_port']
    name = request.form['name']

    # Fix #4: Validate base_port is numeric
    if not validate_port(base_port):
        flash('Invalid port number.', 'danger')
        return redirect(url_for('index'))

    # Fix #4: Validate bastion hosts
    for host in bastion:
        if not validate_ip_or_hostname(host):
            flash(f'Invalid bastion host: {host}', 'danger')
            return redirect(url_for('index'))

    # Fix #4: Sanitize name
    if sanitize_shell_input(name) is None:
        flash('Name contains invalid characters.', 'danger')
        return redirect(url_for('index'))

    windows_ips = request.form.getlist('windows_ip')
    windows_connections = request.form.getlist('windows_connection')
    windows_other_connections = request.form.getlist('windows_other_connection')
    windows_names = request.form.getlist('windows_name')

    linux_ips = request.form.getlist('linux_ip')
    linux_connections = request.form.getlist('linux_connection')
    linux_other_connections = request.form.getlist('linux_other_connection')
    linux_names = request.form.getlist('linux_name')

    other_ips = request.form.getlist('other_ip')
    other_connections = request.form.getlist('other_connection')
    other_other_connections = request.form.getlist('other_other_connection')
    other_names = request.form.getlist('other_name')

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
                if sanitize_shell_input(connection_type) is None:
                    flash(f'Invalid connection type: {connection_type}', 'danger')
                    return None
                if sanitize_shell_input(entry_name.strip()) is None:
                    flash(f'Invalid machine name: {entry_name}', 'danger')
                    return None
                machines.append('"{}_{}" "{}"'.format(ip.strip(), connection_type, entry_name.strip()))
        return machines

    windows_machines = process_entries(windows_ips, windows_connections, windows_other_connections, windows_names)
    if windows_machines is None:
        return redirect(url_for('index'))
    linux_machines = process_entries(linux_ips, linux_connections, linux_other_connections, linux_names)
    if linux_machines is None:
        return redirect(url_for('index'))
    other_machines = process_entries(other_ips, other_connections, other_other_connections, other_names)
    if other_machines is None:
        return redirect(url_for('index'))

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

    with open(config_file, 'w') as file:
        file.write(config_content)

    # Also write JSON config for structured access
    write_json_config(bastion, base_port, name, windows_machines, linux_machines, other_machines)

    audit_log('CONFIG_UPDATED', f'bastion_hosts={len(bastion)} windows={len(windows_machines)} linux={len(linux_machines)} other={len(other_machines)}')
    flash('Configuration updated successfully!', 'success')
    return redirect(url_for('index'))

@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute", methods=["POST"])
def login():
    if not User.query.first():
        return redirect(url_for('setup'))

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()

        if user and check_password_hash(user.password, password):
            if user.is_admin:
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

@app.errorhandler(429)
def ratelimit_handler(e):
    flash('Too many attempts. Please wait before trying again.', 'danger')
    return redirect(url_for('login'))

@app.route('/setup', methods=['GET', 'POST'])
@limiter.limit("5 per minute", methods=["POST"])
def setup():
    if User.query.first():
        return redirect(url_for('login'))

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        confirm_pw = request.form.get('confirm_password', '')
        if password != confirm_pw:
            flash('Passwords do not match.', 'danger')
            return render_template('setup.html')
        valid, msg = validate_password(password)
        if not valid:
            flash(msg, 'danger')
            return render_template('setup.html')
        # Fix #10: Check for duplicate username
        if User.query.filter_by(username=username).first():
            flash('Username already exists.', 'danger')
            return render_template('setup.html')
        is_admin = True
        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
        user = User(username=username, password=hashed_password, is_admin=is_admin)
        db.session.add(user)
        db.session.commit()
        audit_log('USER_CREATED', f'target_user={username} is_admin=True initial_setup=True')
        flash(f'Admin account created for {username}!', 'success')
        return redirect(url_for('login'))
    return render_template('setup.html')

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
        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
        user = User(username=username, password=hashed_password, is_admin=is_admin)
        db.session.add(user)
        db.session.commit()
        audit_log('USER_CREATED', f'target_user={username} is_admin={is_admin}')
        flash(f'Account created for {username}!', 'success')
        return redirect(url_for('index'))
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    audit_log('LOGOUT')
    logout_user()
    return redirect(url_for('login'))

@app.before_request
def refresh_session():
    session.permanent = True
    app.permanent_session_lifetime = timedelta(minutes=30)

@app.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        current_pw = request.form['current_password']
        new_pw = request.form['password']
        confirm_pw = request.form.get('confirm_password', '')
        if not check_password_hash(current_user.password, current_pw):
            flash('Current password is incorrect.', 'danger')
            return render_template('change_password.html')
        if new_pw != confirm_pw:
            flash('New passwords do not match.', 'danger')
            return render_template('change_password.html')
        if not new_pw:
            flash('New password cannot be empty.', 'danger')
            return render_template('change_password.html')
        valid, msg = validate_password(new_pw)
        if not valid:
            flash(msg, 'danger')
            return render_template('change_password.html')
        current_user.password = generate_password_hash(new_pw, method='pbkdf2:sha256')
        db.session.commit()
        audit_log('PASSWORD_CHANGED')
        flash('Password changed successfully!', 'success')
        return redirect(url_for('index'))
    return render_template('change_password.html')

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
        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
        user = User(username=username, password=hashed_password, is_admin=is_admin)
        db.session.add(user)
        db.session.commit()
        audit_log('USER_CREATED', f'target_user={username} is_admin={is_admin}')
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
        new_is_admin = 'is_admin' in request.form
        if user.is_admin and not new_is_admin and User.query.filter_by(is_admin=True).count() <= 1:
            flash('Cannot remove admin from the last admin account.', 'danger')
            return render_template('edit_user.html', user=user)
        user.is_admin = new_is_admin
        db.session.commit()
        audit_log('USER_EDITED', f'target_user={user.username} is_admin={user.is_admin} password_changed={password_changed}')
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
    db.session.delete(user)
    db.session.commit()
    flash(f'Account deleted for {user.username}!', 'success')
    return redirect(url_for('list_users'))

# --- System User Management (SSH Users) ---

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
    return render_template('system_users.html', users=users)

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
            ['sudo', '/root/bin/adduser.sh', username, password],
            capture_output=True, text=True, timeout=30
        )

        if result.returncode != 0:
            flash(f'Failed to create system user: {result.stderr}', 'danger')
            return render_template('add_system_user.html')

        audit_log('SYSTEM_USER_CREATED', f'target_user={username}')
        flash(f'System user "{username}" created successfully!', 'success')

        # Check for QR code file
        qr_file = f'/tmp/ga_qr_{username}.txt'
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

    qr_file = f'/tmp/ga_qr_{username}.txt'
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
        flash(f'Failed to delete system user: {result.stderr}', 'danger')
    else:
        audit_log('SYSTEM_USER_DELETED', f'target_user={username}')
        flash(f'System user "{username}" deleted successfully!', 'success')

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
            flash(f'Failed to reset password: {result.stderr}', 'danger')
            return render_template('reset_system_password.html', username=username)

        audit_log('SYSTEM_USER_PASSWORD_RESET', f'target_user={username}')
        flash(f'Password reset for "{username}" successfully!', 'success')
        return redirect(url_for('list_system_users'))

    return render_template('reset_system_password.html', username=username)

if __name__ == '__main__':
    app.run(debug=True)
