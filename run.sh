#!/bin/bash
if [ -f "/root/bastion/passwd" ] 
then
  /root/bin/upgrade.sh
fi
/usr/sbin/sshd -f /etc/ssh/sshd_config -D
