#Docker Image to spin up a Bastion Server
FROM centos

EXPOSE 22

COPY sshd_config /etc/ssh/sshd_config
COPY sshd /etc/pam.d/sshd
COPY upgrade.sh /root/bin
COPY adduser.sh /root/bin
COPY servers.sh /root/bastion
COPY servers.conf /root/bastion
COPY install_bastion.sh /root/bin
COPY run.sh /root/bin

RUN yum install sudo epel-release openssh-server -y && \
yum install google-authenticator -y && \
chmod 755 /root/bastion/ -R && \
chmod 755 /root/bin/install_bastion.sh && \
chmod 755 /root/bin/adduser.sh && \
chmod 755 /root/run.sh && \
ssh-keygen -f /etc/ssh/ssh_host_rsa_key -N '' -t rsa && \
ssh-keygen -f /etc/ssh/ssh_host_dsa_key -N '' -t dsa && \
ssh-keygen -f /etc/ssh/ssh_host_ecdsa_key -N '' -t ecdsa && \
ssh-keygen -f /etc/ssh/ssh_host_ed25519_key -N '' -t ed25519 

VOLUME /home
VOLUME /root/bastion

WORKDIR /root

ENTRYPOINT /root/run.sh
