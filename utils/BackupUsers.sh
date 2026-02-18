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
