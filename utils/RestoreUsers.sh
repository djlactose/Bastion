#!/bin/bash
for src in passwd shadow gshadow group; do
    if [ -f "/root/bastion/$src" ]; then
        \cp -P "/root/bastion/$src" "/etc/$src" || echo "WARNING: Failed to restore $src"
    else
        echo "WARNING: /root/bastion/$src not found, skipping"
    fi
done
if [ -d /root/bastion/mail ]; then
    \cp -rP /root/bastion/mail /var/spool/mail || echo "WARNING: Failed to restore /var/spool/mail"
else
    echo "WARNING: /root/bastion/mail not found, skipping"
fi
# Restore web UI database backup if primary is missing
if [ -f /root/bastion/users.db.bak ] && [ ! -f /var/lib/bastion/users.db ]; then
    \cp -P /root/bastion/users.db.bak /var/lib/bastion/users.db || echo "WARNING: Failed to restore users.db"
fi
if [ -f /var/lib/bastion/users.db.bak ] && [ ! -f /var/lib/bastion/users.db ]; then
    \cp -P /var/lib/bastion/users.db.bak /var/lib/bastion/users.db || echo "WARNING: Failed to restore users.db"
fi
