#!/usr/bin/bash
read -p "Please enter the username: " user
useradd -m $user
ls /home/bastion/ |grep -v upgrade.sh | grep -v adduser.sh |xargs -I xxx ln -P /home/bastion/xxx /home/$user/xxx
