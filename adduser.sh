#!/usr/bin/bash
read -p "Please enter the username: " user
useradd -m $user
ls /root/bastion/ |xargs -I xxx ln -s /root/bastion/xxx /home/$user/xxx
/root/bin/BackupUsers.sh
sudo -u $user google-authenticator
