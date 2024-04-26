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
  cp /root/bin/servers.conf-sample /etc/bastion/
  cp /root/bin/servers.conf-sample /etc/bastion/servers.conf
fi
echo "nameserver	$dns" >> /etc/resolv.conf
python3 /root/web/web.py &
/usr/sbin/sshd -f /etc/ssh/sshd_config -D -e
