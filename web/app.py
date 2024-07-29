from flask import Flask, request, render_template, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

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
                    bastion_hosts = line.split('=')[1].strip('()').split('" "')
                    config['bastion'] = [host.strip('"') for host in bastion_hosts if host.strip('"')]
                elif line.startswith('base_port='):
                    config['base_port'] = line.split('=')[1]
                elif line.startswith('name='):
                    config['name'] = line.split('=')[1].strip('"')
                elif line.startswith('windowsMachines='):
                    content = line.split('=')[1].strip('()')
                    items = content.split('" "')
                    config['windowsMachines'] = [(items[i].strip('" '), items[i+1].strip('" ')) for i in range(0, len(items), 2) if i+1 < len(items)]
                elif line.startswith('linuxMachines='):
                    content = line.split('=')[1].strip('()')
                    items = content.split('" "')
                    config['linuxMachines'] = [(items[i].strip('" '), items[i+1].strip('" ')) for i in range(0, len(items), 2) if i+1 < len(items)]
                elif line.startswith('otherMachines='):
                    content = line.split('=')[1].strip('()')
                    items = content.split('" "')
                    config['otherMachines'] = [(items[i].strip('" '), items[i+1].strip('" ')) for i in range(0, len(items), 2) if i+1 < len(items)]
    
    return config

def initialize_database():
    db.create_all()

@app.before_request
def before_request():
    initialize_database()

@app.route('/')
@login_required
def index():
    if not User.query.first():
        return redirect(url_for('setup'))
    
    config = parse_config(config_file)
    return render_template('index.html', **config)

@app.route('/update', methods=['POST'])
@login_required
def update():
    bastion = [host for host in request.form.getlist('bastion') if host.strip()]
    base_port = request.form['base_port']
    name = request.form['name']
    
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
        for ip, conn, other_conn, name in zip(ips, connections, other_connections, names):
            if conn == 'Other':
                connection_type = other_conn.strip()
            else:
                connection_type = conn
            if ip.strip() and connection_type and name.strip():
                machines.append('"{}_{}" "{}"'.format(ip.strip(), connection_type, name.strip()))
        return machines

    windows_machines = process_entries(windows_ips, windows_connections, windows_other_connections, windows_names)
    linux_machines = process_entries(linux_ips, linux_connections, linux_other_connections, linux_names)
    other_machines = process_entries(other_ips, other_connections, other_other_connections, other_names)

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
            login_user(user)
            return redirect(url_for('index'))
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
        user.username = request.form['username']
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
