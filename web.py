from flask import Flask, render_template, request
import os

app = Flask(__name__)

# Function to read configuration file and extract machine lists
def read_config():
    config_file = '/etc/bastion/servers.conf'
    if os.path.exists(config_file):
        with open(config_file, 'r') as f:
            config_data = f.read()
        lines = config_data.split('\n')
        windows_machines = [line.strip() for line in lines if line.startswith('windowsMachines=')]
        linux_machines = [line.strip() for line in lines if line.startswith('linuxMachines=')]
        other_machines = [line.strip() for line in lines if line.startswith('otherMachines=')]
        
        windows_machines = windows_machines[0][16:-2].split('" "') if windows_machines else []
        linux_machines = linux_machines[0][16:-2].split('" "') if linux_machines else []
        other_machines = other_machines[0][16:-2].split('" "') if other_machines else []

        return windows_machines, linux_machines, other_machines
    else:
        # Return empty lists if the config file doesn't exist
        return [], [], []

# Function to format list as Bash array without newlines and ^M characters
def format_as_bash_array(lst):
    return '("' + '" "'.join([entry.replace('\r', '') for entry in lst]) + '")'

# Route to display the form
@app.route('/')
def index():
    windows_machines, linux_machines, other_machines = read_config()

    # Read current values from the configuration file
    config_values = {
        'bastion': '',
        'base_port': '',
        'name': '',
        'windows_machines': '',
        'linux_machines': '',
        'other_machines': ''
    }
    
    config_file = '/etc/bastion/servers.conf'
    if os.path.exists(config_file):
        with open(config_file, 'r') as f:
            config_data = f.read()
        for line in config_data.split('\n'):
            if line.startswith('bastion='):
                config_values['bastion'] = line.split('=')[1].strip('()\"')
            elif line.startswith('base_port='):
                config_values['base_port'] = line.split('=')[1].strip()
            elif line.startswith('name='):
                config_values['name'] = line.split('=')[1].strip('\"')
            elif line.startswith('windowsMachines='):
                config_values['windows_machines'] = line.split('=')[1].strip('()\"').replace('" "', '\n')
            elif line.startswith('linuxMachines='):
                config_values['linux_machines'] = line.split('=')[1].strip('()\"').replace('" "', '\n')
            elif line.startswith('otherMachines='):
                config_values['other_machines'] = line.split('=')[1].strip('()\"').replace('" "', '\n')

    return render_template('index.html', config_values=config_values)

# Route to handle form submission
@app.route('/submit', methods=['POST'])
def submit():
    bastion = request.form['bastion']
    base_port = request.form['base_port']
    name = request.form['name']
    windows_machines = request.form['windows_machines'].strip().split('\n')
    linux_machines = request.form['linux_machines'].strip().split('\n')
    other_machines = request.form['other_machines'].strip().split('\n')

    # Format lists as Bash arrays without newlines and ^M characters
    windows_machines_str = format_as_bash_array(windows_machines)
    linux_machines_str = format_as_bash_array(linux_machines)
    other_machines_str = format_as_bash_array(other_machines)

    # Update configuration file
    with open('/etc/bastion/servers.conf', 'w') as f:
        f.write(f'bastion=("{bastion}")\n')
        f.write(f'base_port={base_port}\n')
        f.write(f'name="{name}"\n')
        f.write(f'windowsMachines={windows_machines_str}\n')
        f.write(f'linuxMachines={linux_machines_str}\n')
        f.write(f'otherMachines={other_machines_str}\n')

    return 'Configuration updated successfully! <a href="/">Go back to main page</a>'

if __name__ == '__main__':
    app.run(debug=True)
