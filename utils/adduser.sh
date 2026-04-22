#!/bin/bash
if [ -z "$1" ]; then
    read -p "Please enter the username: " user
else
    user="$1"
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
# Capture Google Authenticator QR code output for web UI display.
# Create the file O_EXCL-style to defeat a pre-existing symlink: rm any prior
# entry, then noclobber-create with a restrictive umask so chmod races can't
# redirect root writes to an arbitrary file.
qr="/tmp/ga_qr_${user}.txt"
rm -f -- "$qr"
( umask 177 && set -C && : > "$qr" ) || { echo "Failed to create $qr safely" >&2; exit 1; }
ga_output=$(sudo -u "$user" google-authenticator -C -t -d -f -r 4 -R 30 -w 4 -Q UTF8)
printf '%s\n' "$ga_output" > "$qr"
printf '%s\n' "$ga_output"
echo "$user:$pass" | chpasswd
/root/bin/BackupUsers.sh
