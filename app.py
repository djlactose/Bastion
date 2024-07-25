from flask import Flask, request, render_template_string
import os

app = Flask(__name__)

# Configuration file path
config_file = 'servers.conf'

def parse_config(file_path):
    config = {
        'bastion': '',
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
                    config['bastion'] = line.split('=')[1].strip('()"')
                elif line.startswith('base_port='):
                    config['base_port'] = line.split('=')[1]
                elif line.startswith('name='):
                    config['name'] = line.split('=')[1].strip('"')
                elif line.startswith('windowsMachines='):
                    content = line.split('=("')[1].strip('")')
                    items = content.split('" "')
                    if len(items) % 2 == 0:  # Ensure pairs
                        config['windowsMachines'] = [
                            (items[i].strip('" '), items[i+1].strip('" '))
                            for i in range(0, len(items), 2)
                        ]
                elif line.startswith('linuxMachines='):
                    content = line.split('=("')[1].strip('")')
                    items = content.split('" "')
                    if len(items) % 2 == 0:  # Ensure pairs
                        config['linuxMachines'] = [
                            (items[i].strip('" '), items[i+1].strip('" '))
                            for i in range(0, len(items), 2)
                        ]
                elif line.startswith('otherMachines='):
                    content = line.split('=("')[1].strip('")')
                    items = content.split('" "')
                    if len(items) % 2 == 0:  # Ensure pairs
                        config['otherMachines'] = [
                            (items[i].strip('" '), items[i+1].strip('" '))
                            for i in range(0, len(items), 2)
                        ]
    
    return config

@app.route('/')
def index():
    config = parse_config(config_file)
    return render_template_string(open('index.html').read(), **config)

@app.route('/update', methods=['POST'])
def update():
    bastion = request.form['bastion']
    base_port = request.form['base_port']
    name = request.form['name']
    
    windows_ips = request.form.getlist('windows_ip')
    windows_names = request.form.getlist('windows_name')
    linux_ips = request.form.getlist('linux_ip')
    linux_names = request.form.getlist('linux_name')
    other_ips = request.form.getlist('other_ip')
    other_names = request.form.getlist('other_name')

    # Filter out blank entries
    windows_machines = [
        '"{}" "{}"'.format(ip.strip(), name.strip())
        for ip, name in zip(windows_ips, windows_names)
        if ip.strip() and name.strip()
    ]
    linux_machines = [
        '"{}" "{}"'.format(ip.strip(), name.strip())
        for ip, name in zip(linux_ips, linux_names)
        if ip.strip() and name.strip()
    ]
    other_machines = [
        '"{}" "{}"'.format(ip.strip(), name.strip())
        for ip, name in zip(other_ips, other_names)
        if ip.strip() and name.strip()
    ]

    # Join entries with space and wrap with parentheses
    windows_machines_str = 'windowsMachines=(' + ' '.join(windows_machines) + ')'
    linux_machines_str = 'linuxMachines=(' + ' '.join(linux_machines) + ')'
    other_machines_str = 'otherMachines=(' + ' '.join(other_machines) + ')'

    # Create the new config content
    config_content = f"""#!/bin/bash
############################################
#Bastion Server Address 
#NOTE: To load balance enter more than one host in quotes
bastion=("{bastion}")
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
# D = Portainer Port - port 8172
# H = Website Ports - ports 8080, 8443
# J - Java Web Ports - ports 8443
# L = Linux ssh - port 22
# M - Bastion Host ssh - port from base_port
# N = Nesus Port - ports 8834, 8000
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

    return 'Configuration updated successfully!'

if __name__ == '__main__':
    app.run(debug=True)
