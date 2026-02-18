#!/bin/bash
if [ -z "$1" ]; then
    read -p "Please enter the username: " user
else
    user="$1"
fi
useradd -m "$user"
if [ -z "$2" ]; then
    while true
    do
        read -s -p "Please enter the password: " pass
        echo .
        read -s -p "Please re-enter the password: " pass2
        if [[ "$pass" == "$pass2" ]]; then
            break
        fi
    done
else
    pass="$2"
fi
ln -s /etc/bastion/servers.conf "/home/$user/servers.conf"
ln -s /etc/bastion/servers.sh "/home/$user/servers.sh"
sudo -u "$user" google-authenticator -C -t -d -f -r 4 -R 30 -w 4 -Q UTF8
echo "$user:$pass" | chpasswd
/root/bin/BackupUsers.sh
