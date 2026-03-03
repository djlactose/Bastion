#Docker Image to spin up a Bastion Server
FROM ubuntu:25.10

EXPOSE 22
EXPOSE 80
EXPOSE 443
EXPOSE 8000

VOLUME /home
VOLUME /root/bastion
VOLUME /etc/bastion
VOLUME /root/web/instance
VOLUME /var/log/bastion

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD nc -q 0 -w 3 localhost 22 | grep -q "SSH" && nc -z -w 3 localhost 8000

COPY config/sshd_config /etc/ssh/sshd_config
COPY config/sshd /etc/pam.d/sshd
COPY config/bastion-app-sudo /etc/sudoers.d/bastion-app-sudo
COPY config/nginx.conf /etc/nginx/sites-available/default
COPY utils/RestoreUsers.sh /root/bin/RestoreUsers.sh
COPY utils/BackupUsers.sh /root/bin/BackupUsers.sh
COPY utils/upgrade.sh /root/bin/upgrade.sh
COPY utils/adduser.sh /root/bin/adduser.sh
COPY utils/deluser.sh /root/bin/deluser.sh
COPY utils/resetpw.sh /root/bin/resetpw.sh
COPY servers.sh /root/bin/servers.sh
COPY config/servers.conf-sample /root/bin/servers.conf-sample
COPY config/servers.json-sample /root/bin/servers.json-sample
COPY run.sh /root/bin/run.sh
COPY web/templates/base.html /root/web/templates/base.html
COPY web/templates/index.html /root/web/templates/index.html
COPY web/templates/users.html /root/web/templates/users.html
COPY web/templates/add_user.html /root/web/templates/add_user.html
COPY web/templates/edit_user.html /root/web/templates/edit_user.html
COPY web/templates/login.html /root/web/templates/login.html
COPY web/templates/register.html /root/web/templates/register.html
COPY web/templates/setup.html /root/web/templates/setup.html
COPY web/templates/change_password.html /root/web/templates/change_password.html
COPY web/templates/system_users.html /root/web/templates/system_users.html
COPY web/templates/add_system_user.html /root/web/templates/add_system_user.html
COPY web/templates/system_user_qr.html /root/web/templates/system_user_qr.html
COPY web/templates/reset_system_password.html /root/web/templates/reset_system_password.html
COPY web/app.py /root/web/app.py
COPY web/wsgi.py /root/web/wsgi.py

RUN apt update && \
apt upgrade -y && \
apt install -y -o Dpkg::Options::="--force-confold" python3-venv gunicorn openssh-server openssh-client libpam-google-authenticator sudo qrencode netcat-openbsd nginx jq && \
python3 -m venv /opt/venv && \
export PATH="/opt/venv/bin:$PATH" && \
pip3 install -U pip && \
pip3 install jinja2 "cryptography>=46.0.5" flask-login flask-sqlalchemy "flask>=3.1.3" "werkzeug>=3.1.6" flask-wtf gunicorn flask-limiter && \
mkdir -p /root/bastion && \
chmod 700 /root/bastion/ && \
mkdir -p /var/log/bastion && \
chmod 755 /root/bin/adduser.sh && \
chmod 755 /root/bin/deluser.sh && \
chmod 755 /root/bin/resetpw.sh && \
chmod 755 /root/bin/run.sh && \
chmod 755 /root/bin/BackupUsers.sh && \
chmod 755 /root/bin/RestoreUsers.sh && \
chmod 644 /root/bin/servers.conf-sample && \
chmod 644 /root/bin/servers.json-sample && \
chmod 755 /root/bin/servers.sh && \
mkdir -p -m0755 /var/run/sshd && \
apt-get clean && \
rm -rf /var/lib/apt/lists/*

WORKDIR /root/bin

ENTRYPOINT ["/root/bin/run.sh"]
