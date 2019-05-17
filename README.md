# Bastion
This is a set of scripts to setup a linux machine to run as a bastion host.  It is designed to run using Linux on windows and will handle several protocols on it's own.

##Persistent Storage
To keep all generated accounts you need to create the two following volumes:
* /home
* /root/bastion
* /etc/bastion

##Environmental Vars
* hostname - this is the hostname you want the container to have.  It will default to "bastion".
* dns - this is the DNS server you want the host to user.  If left blank it will use "9.9.9.9".
