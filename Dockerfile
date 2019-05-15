#Docker Image to spin up a Bastion Server
FROM centos

EXPOSE 22

COPY sshd_config /etc/ssh/sshd_config
COPY sshd /etc/pam.d/sshd
COPY RestoreUsers.sh /root/bin/RestoreUsers.sh
COPY BackupUsers.sh /root/bin/BackupUsers.sh
COPY upgrade.sh /root/bin/upgrade.sh
COPY adduser.sh /root/bin/adduser.sh
COPY servers.sh /root/bin/servers.sh
COPY servers.conf /root/bastion/servers.conf
COPY install_bastion.sh /root/bin/install_bastion.sh
COPY run.sh /root/bin/run.sh

RUN yum install sudo epel-release openssh-server -y && \
yum install google-authenticator -y && \
yum clean all && \
ln -s /root/bin/servers.sh /root/bastion/servers.sh && \
chmod 777 /root/bastion/* -R && \
chmod 755 /root/bin/install_bastion.sh && \
chmod 755 /root/bin/adduser.sh && \
chmod 755 /root/bin/run.sh && \
chmod 755 /root/bin/BackupUsers.sh && \
chmod 755 /root/bin/RestoreUsers.sh

VOLUME /home
VOLUME /root/bastion

WORKDIR /root/bin

ENTRYPOINT /root/bin/run.sh
