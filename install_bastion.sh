#!/bin/bash
echo "Enter in the server address of the bastion host:"
read bastion
echo "Enter bastion username:"
read user
read -p "Generate SSH Key? " -n 1 -r
if [[ $REPLY =~ ^[Yy]$ ]]
then
  ssh-keygen -f ~/.ssh/id_rsa -t rsa -N ''
fi
ssh-copy-id $bastion
scp $user@$bastion:~/servers.sh ./
