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

RUN apt update && \
apt install -y -o Dpkg::Options::="--force-confold" openssh-server openssh-client libpam-google-authenticator sudo qrencode && \
mkdir /root/bastion && \
chmod 700 /root/bastion/ && \
chmod 755 /root/bin/install_bastion.sh && \
chmod 755 /root/bin/adduser.sh && \
chmod 755 /root/bin/run.sh && \
chmod 755 /root/bin/BackupUsers.sh && \
chmod 755 /root/bin/RestoreUsers.sh && \
chmod 644 /root/bin/servers.conf-sample && \
chmod 755 /root/bin/servers.sh && \
mkdir -p -m0755 /var/run/sshd

WORKDIR /root/bin

ENTRYPOINT /root/bin/run.sh