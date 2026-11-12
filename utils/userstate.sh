#!/bin/bash
# Disable, re-enable or set an expiry date on an SSH user without deleting it.
#
#   userstate.sh status                      list "<user> <expiry-day|->" for login users
#   userstate.sh disable <username>          block all logins now and end open sessions
#   userstate.sh enable  <username>          clear the block / expiry date
#   userstate.sh expire  <username> <YYYY-MM-DD>   logins stop working on that date
#
# Uses the account expiry date (usermod -e). Unlike locking the password, an
# expired account is refused for public-key logins as well.
#
# Runs as root via sudo from the web app (www-data), so it only ever touches
# regular login users (UID >= 1000).
action="$1"
user="$2"

if [ "$action" = "status" ]; then
    # Field 8 of /etc/shadow is the expiry date in days since 1970-01-01.
    while IFS=: read -r name _ uid _; do
        if [ "$uid" -ge 1000 ] 2>/dev/null && [ "$name" != "nobody" ]; then
            exp=$(awk -F: -v u="$name" '$1 == u {print $8}' /etc/shadow)
            echo "$name ${exp:--}"
        fi
    done < /etc/passwd
    exit 0
fi

case "$action" in
    disable|enable|expire) ;;
    *) echo "Usage: userstate.sh status | disable <user> | enable <user> | expire <user> <YYYY-MM-DD>" >&2; exit 2 ;;
esac
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

case "$action" in
    disable)
        # Day 1 (1970-01-02) is always in the past: the account is expired.
        usermod -e 1 "$user" || exit 1
        # End sessions that are already open.
        pkill -KILL -u "$user" 2>/dev/null
        ;;
    enable)
        usermod -e '' "$user" || exit 1
        ;;
    expire)
        date="$3"
        if ! [[ "$date" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || ! date -d "$date" >/dev/null 2>&1; then
            echo "Invalid date '$date' (use YYYY-MM-DD)." >&2
            exit 2
        fi
        usermod -e "$date" "$user" || exit 1
        ;;
esac
/root/bin/BackupUsers.sh
