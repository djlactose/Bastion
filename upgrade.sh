#!/bin/bash
cp /root/bastion/ssh_host_rsa_key /etc/ssh/
cp /root/bastion/ssh_host_dsa_key /etc/ssh/
cp /root/bastion/ssh_host_ecdsa_key /etc/ssh/ssh_host_ecdsa_key
cp /root/bastion/ssh_host_ed25519_key /etc/ssh/ssh_host_ed25519_key
\cp /root/bin/servers.sh /etc/bastion/
/root/bin/RestoreUsers.sh
