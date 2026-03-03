#!/bin/bash
# Restore SSH host keys from backup
for keytype in rsa ecdsa ed25519; do
    keyfile="/root/bastion/ssh_host_${keytype}_key"
    if [ -f "$keyfile" ]; then
        cp "$keyfile" "/etc/ssh/ssh_host_${keytype}_key"
        # Regenerate public key from private key (old backups may lack .pub files)
        ssh-keygen -y -f "/etc/ssh/ssh_host_${keytype}_key" > "/etc/ssh/ssh_host_${keytype}_key.pub" 2>/dev/null
    fi
done
\cp /root/bin/servers.sh /etc/bastion/
/root/bin/RestoreUsers.sh
