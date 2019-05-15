#!/bin/bash
ls /home | xargs -I xxx useradd -d /home/xxx xxx
copy /root/bastion/ssh_host_rsa_key /etc/ssh/
copy /root/bastion/ssh_host_dsa_key /etc/ssh/
copy /root/bastion/ssh_host_ecdsa_key /etc/ssh/ssh_host_ecdsa_key
copy /root/bastion/ssh_host_ed25519_key /etc/ssh/ssh_host_ed25519_key
/root/bin/RestoreUsers.sh
