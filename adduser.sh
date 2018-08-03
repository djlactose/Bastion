#!/usr/bash
read -P "Please enter the username: " user
useradd -m $user
ls /home/bastion/ |xargs -I xxx ln -P /home/bastion/xxx /home/$user/xxx
