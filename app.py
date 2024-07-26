from flask import Flask, request, render_template_string
import os

app = Flask(__name__)

# Configuration file path
config_file = 'servers.conf'

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
                    bastion_hosts = line.split('=')[1].strip('()"').split('" "')
                    config['bastion'] = [host.strip('"') for host in bastion_hosts]
                elif line.startswith('base_port='):
                    config['base_port'] = line.split('=')[1]
                elif line.startswith('name='):
                    config['name'] = line.split('=')[1].strip('"')
                elif line.startswith('windowsMachines='):
                    content = line.split('=')[1].strip('()')
                    items = content.split('" "')
                    config['windowsMachines'] = [(items[i].strip('" '), items[i+1].strip('" ')) for i in range(0, len(items), 2)]
                elif line.startswith('linuxMachines='):
                    content = line.split('=')[1].strip('()')
                    items = content.split('" "')
                    config['linuxMachines'] = [(items[i].strip('" '), items[i+1].strip('" ')) for i in range(0, len(items), 2)]
                elif line.startswith('otherMachines='):
                    content = line.split('=')[1].strip('()')
                    items = content.split('" "')
                    config['otherMachines'] = [(items[i].strip('" '), items[i+1].strip('" ')) for i in range(0, len(items), 2)]
    
    return config

@app.route('/')
def index():
    config = parse_config(config_file)
    return render_template_string(open('index.html').read(), **config)

@app.route('/update', methods=['POST'])
def update():
    bastion = request.form.getlist('bastion')
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
# L = Linux
# M - Bastion Host
# N = Nesus Port - ports 8834, 8000
# P = Publish using MSDeploy - port 8172
# W = Windows
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

    return 'Configuration updated successfully!'

if __name__ == '__main__':
    app.run(debug=True)
