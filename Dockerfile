#Docker Image to spin up a Bastion Server
FROM centos
EXPOSE 22

COPY ./sshd_config /etc/ssh/sshd_config
COPY ./upgrade.sh /root
COPY ./adduser.sh /root
COPY servers.sh /root
COPY servers.conf /root
COPY install_bastion.sh /root
COPY run.sh /root

RUN mkdir /home/bastion && \
yum install openssh-server -y && \
chmod 755 /root/servers.conf && \
chmod 755 /root/servers.sh && \
chmod 755 /root/install_bastion.sh && \
ln -P /root/servers.conf /home/bastion/servers.conf && \
ln -P /root/servers.sh /home/bastion/servers.sh && \
ln -P /root/install_bastion.sh /home/bastion/install_bastion.sh && \
chmod 755 /home/bastion/servers.conf && \
chmod 755 /home/bastion/servers.sh && \
chmod 755 /home/bastion/install_bastion.sh && \
chmod 755 /root/run.sh && \
ssh-keygen -f /etc/ssh/ssh_host_rsa_key -N '' -t rsa && \
ssh-keygen -f /etc/ssh/ssh_host_dsa_key -N '' -t dsa && \
ssh-keygen -f /etc/ssh/ssh_host_ecdsa_key -N '' -t ecdsa && \
ssh-keygen -f /etc/ssh/ssh_host_ed25519_key -N '' -t ed25519 

VOLUME /home

WORKDIR /root

ENTRYPOINT /root/run.sh
