#Docker Image to spin up a Bastion Server
FROM centos
EXPOSE 22

RUN mkdir /home/bastion && \
yum install openssh-server git -y && \
cd /home/bastion && \
git clone https://github.com/djlactose/Bastion.git && \
mv /home/bastion/Bastion/servers.conf /home/bastion/ && \
mv /home/bastion/Bastion/servers.sh /home/bastion/ && \
mv /home/bastion/Bastion/install_bastion.sh /home/bastion/ && \
rm -rf /home/bastion/Bastion && \
ssh-keygen -f /etc/ssh/ssh_host_rsa_key -N '' -t rsa && \
ssh-keygen -f /etc/ssh/ssh_host_dsa_key -N '' -t dsa && \
ssh-keygen -f /etc/ssh/ssh_host_ecdsa_key -N '' -t ecdsa && \
ssh-keygen -f /etc/ssh/ssh_host_ed25519_key -N '' -t ed25519 && \
useradd -d /home/bastion admin && \
echo $(head /dev/urandom | tr -dc A-Za-z0-9|head -c 13;echo '') > /root/admin_pass.txt && \
cat /root/admin_pass.txt | passwd admin --stdin && \
chage -d 0 admin

COPY ./sshd_config /etc/ssh/sshd_config

VOLUME /home

ENTRYPOINT ["/usr/sbin/sshd","-D"]
