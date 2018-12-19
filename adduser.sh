#!/usr/bin/bash
read -p "Please enter the username: " user
useradd -m $user
ls /root/bastion/ |xargs -I xxx ln -P /root/bastion/xxx /home/$user/xxx
sudo -u $user google-authenticator
