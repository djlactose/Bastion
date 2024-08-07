# Bastion

This is a set of scripts to setup a linux machine to run as a bastion host.  It is designed to run using Linux on windows and will handle several protocols on it's own.  The only two scripts you need if you just want to run the bastion is the servers.sh and the servers.conf.  All of the other items pertain to running it is a docker containter or are there to try and make it easier to setup.

## Persistent Storage

To keep all generated accounts you need to create the two following volumes:

* /home
* /root/bastion
* /etc/bastion
* /root/web/instance - Only needed if you are using the Web Interface

## Ports

* 22 - This is the port people will connect through
* 8000 - **BETA* If you want to make the web interface publically accessible you should open this port.  You can still access the bastion host without making this accessible.
