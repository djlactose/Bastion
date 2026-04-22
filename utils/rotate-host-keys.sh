#!/bin/bash
# Rotate the bastion's SSH host keys.
#
# This is a privileged, deliberately-manual operation. Run it via:
#   docker exec -it <container> /root/bin/rotate-host-keys.sh
# Pass --yes to skip the interactive confirmation (for scripted rotations).
#
# Behavior:
#   1. Snapshots current /etc/ssh/ssh_host_* key pairs to
#      /root/bastion/keys-rotated-<timestamp>/ (persistent volume).
#   2. Generates new RSA-4096, ECDSA-P521, and Ed25519 keys.
#   3. Copies the new keys back to /root/bastion/ for upgrade persistence.
#   4. Sends SIGHUP to the main sshd so new connections see the new keys.
#      Existing SSH sessions are unaffected.
#
# Client impact: anyone whose known_hosts pins the current fingerprint will
# see a mismatch warning and must re-accept. Clients launched via the bundled
# servers.sh (which uses StrictHostKeyChecking=no) are unaffected.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "rotate-host-keys.sh must be run as root (inside the container)." >&2
    exit 1
fi

if [ "${1:-}" != "--yes" ]; then
    cat <<'EOM'
This will rotate the bastion's SSH host keys.

After rotation, SSH clients that have the current host fingerprint in
~/.ssh/known_hosts will refuse to connect until the new fingerprint is
accepted. Clients connecting through the bundled servers.sh (which disables
strict host-key checking) are unaffected.

EOM
    read -rp "Continue with rotation? [y/N] " reply
    case "$reply" in
        [yY]|[yY][eE][sS]) ;;
        *) echo "Aborted."; exit 1 ;;
    esac
fi

BACKUP_DIR="/root/bastion/keys-rotated-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

KEYS=(
    /etc/ssh/ssh_host_rsa_key
    /etc/ssh/ssh_host_ecdsa_key
    /etc/ssh/ssh_host_ed25519_key
)

echo "Backing up current host keys to $BACKUP_DIR"
for k in "${KEYS[@]}"; do
    [ -f "$k" ]      && cp -p "$k"     "$BACKUP_DIR/"
    [ -f "$k.pub" ]  && cp -p "$k.pub" "$BACKUP_DIR/"
done

# Generate into temp paths first so a mid-flight failure doesn't leave the
# container without usable host keys.
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

echo "Generating new RSA-4096 key"
ssh-keygen -q -f "$TMP_DIR/ssh_host_rsa_key" -N '' -t rsa -b 4096

echo "Generating new ECDSA-P521 key"
ssh-keygen -q -f "$TMP_DIR/ssh_host_ecdsa_key" -N '' -t ecdsa -b 521

echo "Generating new Ed25519 key"
ssh-keygen -q -f "$TMP_DIR/ssh_host_ed25519_key" -N '' -t ed25519

echo "Installing new keys"
for k in "${KEYS[@]}"; do
    base="$(basename "$k")"
    install -o root -g root -m 600 "$TMP_DIR/$base"     "$k"
    install -o root -g root -m 644 "$TMP_DIR/$base.pub" "$k.pub"
    # Mirror to /root/bastion so upgrades persist them
    cp -p "$k"     /root/bastion/
    cp -p "$k.pub" /root/bastion/
done

echo "Reloading sshd (SIGHUP, existing sessions preserved)"
if pgrep -f 'sshd.*-D' >/dev/null; then
    pkill -HUP -f 'sshd.*-D' || true
else
    echo "  sshd not running in foreground mode; restart the container to pick up keys."
fi

echo
echo "Rotation complete. New fingerprints:"
for k in "${KEYS[@]}"; do
    [ -f "$k.pub" ] && ssh-keygen -l -f "$k.pub"
done
echo
echo "Old keys backed up at: $BACKUP_DIR"
echo "Rollback command:"
echo "  cp -p $BACKUP_DIR/ssh_host_* /etc/ssh/ && pkill -HUP -f 'sshd.*-D'"
