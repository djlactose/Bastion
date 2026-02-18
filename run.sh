#!/bin/bash
if [ -f "/root/bastion/passwd" ]
then
  /root/bin/upgrade.sh
else
  rm -f /etc/ssh/ssh_host_rsa_key
  rm -f /etc/ssh/ssh_host_ecdsa_key
  rm -f /etc/ssh/ssh_host_ed25519_key
  ssh-keygen -f /etc/ssh/ssh_host_rsa_key -N '' -t rsa
  ssh-keygen -f /etc/ssh/ssh_host_ecdsa_key -N '' -t ecdsa
  ssh-keygen -f /etc/ssh/ssh_host_ed25519_key -N '' -t ed25519
  cp /etc/ssh/ssh_host_rsa_key /root/bastion
  cp /etc/ssh/ssh_host_rsa_key.pub /root/bastion
  cp /etc/ssh/ssh_host_ecdsa_key /root/bastion
  cp /etc/ssh/ssh_host_ecdsa_key.pub /root/bastion
  cp /etc/ssh/ssh_host_ed25519_key /root/bastion
  cp /etc/ssh/ssh_host_ed25519_key.pub /root/bastion
  cp /root/bin/servers.sh /etc/bastion/
  cp /root/bin/servers.conf-sample /etc/bastion/
  cp /root/bin/servers.conf-sample /etc/bastion/servers.conf
  cp /root/bin/servers.json-sample /etc/bastion/
  cp /root/bin/servers.json-sample /etc/bastion/servers.json
fi
cp /root/bin/servers.sh /etc/bastion/
cp /root/bin/servers.conf-sample /etc/bastion/
cp /root/bin/servers.json-sample /etc/bastion/
export PATH="/opt/venv/bin:$PATH"

# Configurable Gunicorn workers (default: 2)
GUNICORN_WORKERS=${GUNICORN_WORKERS:-2}
if ! [[ "$GUNICORN_WORKERS" =~ ^[0-9]+$ ]] || [ "$GUNICORN_WORKERS" -lt 1 ]; then
    echo "WARNING: Invalid GUNICORN_WORKERS value '$GUNICORN_WORKERS', defaulting to 2"
    GUNICORN_WORKERS=2
fi

# Start Gunicorn and optionally Nginx for HTTPS
if [ -f "/etc/bastion/certs/fullchain.pem" ] && [ -f "/etc/bastion/certs/privkey.pem" ]; then
    echo "TLS certificates found. Starting Nginx with HTTPS on port 443."
    gunicorn -w "$GUNICORN_WORKERS" -b 127.0.0.1:8000 --daemon --chdir /root/web/ wsgi:app
    nginx
else
    echo "No TLS certificates found at /etc/bastion/certs/. Running without HTTPS on port 8000."
    gunicorn -w "$GUNICORN_WORKERS" -b 0.0.0.0:8000 --daemon --chdir /root/web/ wsgi:app
fi

/usr/sbin/sshd -f /etc/ssh/sshd_config -D -e
