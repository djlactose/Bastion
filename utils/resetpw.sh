#!/bin/bash
if [ -z "$1" ]; then
    echo "Usage: resetpw.sh <username>" >&2
    exit 2
fi
user="$1"
# Verify user exists
if ! id "$user" >/dev/null 2>&1; then
    echo "User '$user' does not exist." >&2
    exit 1
fi
# Read password from stdin
read -r pass
echo "$user:$pass" | chpasswd
