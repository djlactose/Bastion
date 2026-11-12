#!/bin/bash
if [ -z "$1" ]; then
    read -p "Please enter the username: " user
else
    user="$1"
fi

# This runs as root via sudo from www-data; reject anything that isn't a plain
# Linux username (it is also interpolated into /home and /tmp paths below).
if ! [[ "$user" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]]; then
    echo "Invalid username '$user'." >&2
    exit 2
fi

# Check if user already exists
if id "$user" >/dev/null 2>&1; then
    echo "User '$user' already exists." >&2
    exit 1
fi

useradd -m "$user"
if [ -t 0 ]; then
    # Interactive: prompt for password
    while true
    do
        read -s -p "Please enter the password: " pass
        echo .
        read -s -p "Please re-enter the password: " pass2
        if [[ "$pass" == "$pass2" ]]; then
            break
        fi
    done
else
    # Non-interactive: read password from stdin (e.g. web UI)
    read -r pass
fi
ln -s /etc/bastion/servers.conf "/home/$user/servers.conf"
ln -s /etc/bastion/servers.sh "/home/$user/servers.sh"
# Enroll the user in Google Authenticator.
ga_output=$(sudo -u "$user" google-authenticator -C -t -d -f -r 4 -R 30 -w 4 -Q UTF8)
# Hand the QR code to the web UI through its private one-time directory
# (mode 700, owned by www-data; the app reads the file once and deletes it).
# The file is created and written as www-data, so root never writes into a
# directory the web user controls and no SSH user can read the secret.
qr_dir=/var/lib/bastion/qr
if id www-data >/dev/null 2>&1 && [ -d "$qr_dir" ]; then
    printf '%s\n' "$ga_output" | \
        su -s /bin/sh www-data -c 'umask 077; rm -f -- "$0"; cat > "$0"' "$qr_dir/ga_qr_${user}.txt"
fi
printf '%s\n' "$ga_output"
echo "$user:$pass" | chpasswd
/root/bin/BackupUsers.sh
