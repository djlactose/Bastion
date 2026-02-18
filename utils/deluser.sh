#!/bin/bash
if [ -z "$1" ]; then
    echo "Usage: deluser.sh <username>" >&2
    exit 2
fi
user="$1"
# Verify user exists
if ! id "$user" >/dev/null 2>&1; then
    echo "User '$user' does not exist." >&2
    exit 1
fi
userdel -r "$user" 2>/dev/null
/root/bin/BackupUsers.sh
