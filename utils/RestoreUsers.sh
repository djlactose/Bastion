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
