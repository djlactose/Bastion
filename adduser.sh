#!/bin/bash
read -p "Please enter the username: " user
addgroup $user
adduser -G $user $user
ln -s /etc/bastion/servers.conf /home/$user/servers.conf
ln -s /etc/bastion/servers.sh /home/$user/servers.sh
sudo -u $user google-authenticator
passwd $user
/root/bin/BackupUsers.sh
