#!/bin/bash
if [ -f "/root/bastion/passwd" ] 
then
  /root/bin/upgrade.sh
else
  ssh-keygen -f /etc/ssh/ssh_host_rsa_key -N '' -t rsa && \
  ssh-keygen -f /etc/ssh/ssh_host_dsa_key -N '' -t dsa && \
  ssh-keygen -f /etc/ssh/ssh_host_ecdsa_key -N '' -t ecdsa && \
  ssh-keygen -f /etc/ssh/ssh_host_ed25519_key -N '' -t ed25519
  cp /etc/ssh/ssh_host_rsa_key /root/bastion
  cp /etc/ssh/ssh_host_dsa_key /root/bastion
  cp /etc/ssh/ssh_host_ecdsa_key /root/bastion
  cp /etc/ssh/ssh_host_ed25519_key /root/bastion
  cp /root/bin/servers.sh /etc/bastion/
fi
echo "nameserver	$dns" >> /etc/resolv.conf
/usr/sbin/sshd -f /etc/ssh/sshd_config -D
