#Docker Image to spin up a Bastion Server
FROM ubuntu

EXPOSE 22
EXPOSE 5000

ENV dns 9.9.9.9

VOLUME /home
VOLUME /root/bastion
VOLUME /etc/bastion

HEALTHCHECK CMD exit $(nc -q 0 -w 1 localhost 22|grep -c "SSH")

COPY sshd_config /etc/ssh/sshd_config
COPY sshd /etc/pam.d/sshd
COPY RestoreUsers.sh /root/bin/RestoreUsers.sh
COPY BackupUsers.sh /root/bin/BackupUsers.sh
COPY upgrade.sh /root/bin/upgrade.sh
COPY adduser.sh /root/bin/adduser.sh
COPY servers.sh /root/bin/servers.sh
COPY servers.conf-sample /root/bin/servers.conf-sample
COPY install_bastion.sh /root/bin/install_bastion.sh
COPY run.sh /root/bin/run.sh
COPY templates/index.html /root/web/templates/index.html
COPY web.py /root/web/web.py

<<<<<<< HEAD
RUN apt update && \
apt install -y -o Dpkg::Options::="--force-confold" openssh-server libpam-google-authenticator sudo qrencode && \
=======
RUN yum install sudo epel-release openssh-clients openssh-server python3 python3-pip -y && \
yum install google-authenticator -y && \
yum clean all && \
>>>>>>> 5e5f1bbe92ae073628cb4c727f0e8260de017489
mkdir /root/bastion && \
chmod 700 /root/bastion/ && \
chmod 755 /root/bin/install_bastion.sh && \
chmod 755 /root/bin/adduser.sh && \
chmod 755 /root/bin/run.sh && \
chmod 755 /root/bin/BackupUsers.sh && \
chmod 755 /root/bin/RestoreUsers.sh && \
<<<<<<< HEAD
chmod 644 /root/bin/servers.conf-sample && \
chmod 755 /root/bin/servers.sh
=======
chmod 744 /root/bin/servers.conf-sample && \
chmod 755 /root/bin/servers.sh && \
pip3 install flask
>>>>>>> 5e5f1bbe92ae073628cb4c727f0e8260de017489

WORKDIR /root/bin

ENTRYPOINT /root/bin/run.sh