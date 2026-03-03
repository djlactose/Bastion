#!/bin/bash
for src in /etc/passwd /etc/shadow /etc/gshadow /etc/group; do
    if [ -f "$src" ]; then
        \cp -P "$src" /root/bastion/ || echo "WARNING: Failed to backup $src"
    else
        echo "WARNING: $src not found, skipping"
    fi
done
if [ -d /var/spool/mail ]; then
    \cp -Pr /var/spool/mail /root/bastion/ || echo "WARNING: Failed to backup /var/spool/mail"
else
    echo "WARNING: /var/spool/mail not found, skipping"
fi
# Backup SSH host public keys
for pubkey in /etc/ssh/ssh_host_*_key.pub; do
    [ -f "$pubkey" ] && \cp -P "$pubkey" /root/bastion/ || true
done
# Backup web UI database
if [ -f /var/lib/bastion/users.db ]; then
    \cp -P /var/lib/bastion/users.db /var/lib/bastion/users.db.bak || echo "WARNING: Failed to backup users.db"
fi
