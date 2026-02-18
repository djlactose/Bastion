from flask import Flask, request, render_template, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import generate_password_hash, check_password_hash
import os
import re

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

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Fix #3: CSRF protection
csrf = CSRFProtect(app)

# User model
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Configuration file path
config_file = '/etc/bastion/servers.conf'

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

# Fix #2: Initialize database once at startup instead of every request
with app.app_context():
    db.create_all()

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

    flash('Configuration updated successfully!', 'success')
    return redirect(url_for('index'))

@app.route('/login', methods=['GET', 'POST'])
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
                return redirect(url_for('index'))
            else:
                flash('Access denied: Only administrators can sign in.', 'danger')
        else:
            flash('Login Unsuccessful. Please check username and password', 'danger')
    return render_template('login.html')

@app.route('/setup', methods=['GET', 'POST'])
def setup():
    if User.query.first():
        return redirect(url_for('login'))

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        # Fix #10: Check for duplicate username
        if User.query.filter_by(username=username).first():
            flash('Username already exists.', 'danger')
            return render_template('setup.html')
        is_admin = True
        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
        user = User(username=username, password=hashed_password, is_admin=is_admin)
        db.session.add(user)
        db.session.commit()
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
        # Fix #10: Check for duplicate username
        if User.query.filter_by(username=username).first():
            flash('Username already exists.', 'danger')
            return render_template('register.html')
        is_admin = 'is_admin' in request.form
        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
        user = User(username=username, password=hashed_password, is_admin=is_admin)
        db.session.add(user)
        db.session.commit()
        flash(f'Account created for {username}!', 'success')
        return redirect(url_for('index'))
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

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
        # Fix #10: Check for duplicate username
        if User.query.filter_by(username=username).first():
            flash('Username already exists.', 'danger')
            return render_template('add_user.html')
        is_admin = 'is_admin' in request.form
        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
        user = User(username=username, password=hashed_password, is_admin=is_admin)
        db.session.add(user)
        db.session.commit()
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
        if request.form['password']:
            user.password = generate_password_hash(request.form['password'], method='pbkdf2:sha256')
        user.is_admin = 'is_admin' in request.form
        db.session.commit()
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
    db.session.delete(user)
    db.session.commit()
    flash(f'Account deleted for {user.username}!', 'success')
    return redirect(url_for('list_users'))

if __name__ == '__main__':
    app.run(debug=True)
