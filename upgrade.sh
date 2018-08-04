#!/usr/bin/bash
ls /home | grep -v bastion | xargs -I xxx useradd -d /home/xxx xxx
