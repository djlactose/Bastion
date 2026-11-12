#!/bin/bash
# Read or replace an SSH user's authorized public keys.
#
#   userkeys.sh get <username>     print ~/.ssh/authorized_keys
#   userkeys.sh set <username>     replace it with the keys read from stdin
#
# Runs as root via sudo from the web app (www-data), so it only ever touches
# regular login users (UID >= 1000). The file itself is always read and written
# *as that user*: the home directory belongs to the user, and root following a
# symlink planted there could read or overwrite any file on the system.
action="$1"
user="$2"
case "$action" in
    get|set) ;;
    *) echo "Usage: userkeys.sh get|set <username>" >&2; exit 2 ;;
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
    echo "Refusing to touch system account '$user'." >&2
    exit 1
fi

if [ "$action" = "get" ]; then
    su -s /bin/sh "$user" -c 'cat "$HOME/.ssh/authorized_keys" 2>/dev/null' | head -c 65536
    exit 0
fi

# set: accept only plain "type base64 [comment]" lines of known key types. Key
# options (command=, from=, ...) are refused: they are a way to run commands.
key_re='^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp256|ecdsa-sha2-nistp384|ecdsa-sha2-nistp521|sk-ssh-ed25519@openssh\.com|sk-ecdsa-sha2-nistp256@openssh\.com) [A-Za-z0-9+/=]+( [[:print:]]*)?$'
tmp=$(mktemp) || exit 1
trap 'rm -f "$tmp" "$tmp.one"' EXIT
count=0
while IFS= read -r line || [ -n "$line" ]; do
    line="${line%$'\r'}"
    [ -z "$line" ] && continue
    count=$((count + 1))
    if [ "$count" -gt 50 ]; then
        echo "Too many keys (maximum 50)." >&2
        exit 2
    fi
    if ! [[ "$line" =~ $key_re ]]; then
        echo "Key $count is not a valid public key line." >&2
        exit 2
    fi
    printf '%s\n' "$line" > "$tmp.one"
    if ! ssh-keygen -l -f "$tmp.one" >/dev/null 2>&1; then
        echo "Key $count could not be parsed." >&2
        exit 2
    fi
    printf '%s\n' "$line" >> "$tmp"
done < <(head -c 65536)

# Write as the user. The old file is removed first so a symlink left in its
# place is replaced rather than followed.
su -s /bin/sh "$user" -c 'umask 077; mkdir -p "$HOME/.ssh" && rm -f "$HOME/.ssh/authorized_keys" && cat > "$HOME/.ssh/authorized_keys"' < "$tmp" || {
    echo "Could not write authorized_keys for '$user'." >&2
    exit 1
}
echo "Wrote $count key(s) for $user."
