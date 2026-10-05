#!/bin/bash
if [ -z "$1" ]; then
    echo "Usage: resetpw.sh <username>" >&2
    exit 2
fi
user="$1"
# This runs as root via sudo from www-data, so it must never touch root or a
# system/service account: only regular login users (UID >= 1000).
if ! [[ "$user" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]]; then
    echo "Invalid username '$user'." >&2
    exit 2
fi
# Verify user exists
if ! id "$user" >/dev/null 2>&1; then
    echo "User '$user' does not exist." >&2
    exit 1
fi
if [ "$(id -u "$user")" -lt 1000 ] || [ "$user" = "nobody" ]; then
    echo "Refusing to modify system account '$user'." >&2
    exit 1
fi
# Read password from stdin
read -r pass
echo "$user:$pass" | chpasswd
