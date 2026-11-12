#!/bin/bash
# Re-enroll an SSH user in Google Authenticator (e.g. after a lost phone).
# Replaces the user's authenticator secret and scratch codes; the account,
# password and home directory are left alone.
#
#   reset2fa.sh <username>
#
# Runs as root via sudo from the web app (www-data), so it only ever touches
# regular login users (UID >= 1000).
if [ -z "$1" ]; then
    echo "Usage: reset2fa.sh <username>" >&2
    exit 2
fi
user="$1"
if ! [[ "$user" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]]; then
    echo "Invalid username '$user'." >&2
    exit 2
fi
if ! id "$user" >/dev/null 2>&1; then
    echo "User '$user' does not exist." >&2
    exit 1
fi
if [ "$(id -u "$user")" -lt 1000 ] || [ "$user" = "nobody" ]; then
    echo "Refusing to modify system account '$user'." >&2
    exit 1
fi

if ! ga_output=$(sudo -u "$user" google-authenticator -C -t -d -f -r 4 -R 30 -w 4 -Q UTF8); then
    echo "google-authenticator failed for '$user'." >&2
    exit 1
fi
# Same hand-over as adduser.sh: written as www-data into its private one-time
# directory, read once by the web app and deleted.
qr_dir=/var/lib/bastion/qr
if id www-data >/dev/null 2>&1 && [ -d "$qr_dir" ]; then
    printf '%s\n' "$ga_output" | \
        su -s /bin/sh www-data -c 'umask 077; rm -f -- "$0"; cat > "$0"' "$qr_dir/ga_qr_${user}.txt"
fi
printf '%s\n' "$ga_output"
