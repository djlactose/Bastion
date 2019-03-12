#!/usr/bin/bash
ls /home | xargs -I xxx useradd -d /home/xxx xxx
/root/bin/RestoreUsers.sh
