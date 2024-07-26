#Docker Image to spin up a Bastion Server
FROM ubuntu:24.10

EXPOSE 22
EXPOSE 8000

ENV dns 9.9.9.9

VOLUME /home
VOLUME /root/bastion
VOLUME /etc/bastion

HEALTHCHECK CMD exit $(nc -q 0 -w 1 localhost 22|grep -c "SSH")

COPY config/sshd_config /etc/ssh/sshd_config
COPY config/sshd /etc/pam.d/sshd
COPY utils/RestoreUsers.sh /root/bin/RestoreUsers.sh
COPY utils/BackupUsers.sh /root/bin/BackupUsers.sh
COPY utils/upgrade.sh /root/bin/upgrade.sh
COPY utils/adduser.sh /root/bin/adduser.sh
COPY servers.sh /root/bin/servers.sh
COPY config/servers.conf-sample /root/bin/servers.conf-sample
COPY run.sh /root/bin/run.sh
COPY web/templates/base.html /root/web/templates/base.html
COPY web/templates/index.html /root/web/templates/index.html
COPY web/templates/users.html /root/web/templates/users.html
COPY web/templates/add_user.html /root/web/templates/add_user.html
COPY web/templates/edit_user.html /root/web/templates/edit_user.html
COPY web/templates/login.html /root/web/templates/login.html
COPY web/templates/register.html /root/web/templates/register.html
COPY web/templates/setup.html /root/web/templates/setup.html
COPY web/app.py /root/web/app.py
COPY web/wsgi.py /root/web/wsgi.py

RUN apt update && \
apt install -y -o Dpkg::Options::="--force-confold" python3-flask-login python3-flask-sqlalchemy  python3-flask python3-gunicorn gunicorn openssh-server openssh-client libpam-google-authenticator sudo qrencode && \
mkdir /root/bastion && \
chmod 700 /root/bastion/ && \
chmod 755 /root/bin/adduser.sh && \
chmod 755 /root/bin/run.sh && \
chmod 755 /root/bin/BackupUsers.sh && \
chmod 755 /root/bin/RestoreUsers.sh && \
chmod 644 /root/bin/servers.conf-sample && \
chmod 755 /root/bin/servers.sh && \
mkdir -p -m0755 /var/run/sshd && \
apt-get clean && \
rm -rf /var/lib/apt/lists/*

WORKDIR /root/bin

ENTRYPOINT /root/bin/run.sh