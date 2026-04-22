#!/bin/bash
if [ -f "/root/bastion/passwd" ]
then
  /root/bin/upgrade.sh
  # Ensure www-data exists after user restore (required for gunicorn/nginx)
  if ! id www-data >/dev/null 2>&1; then
      groupadd -r www-data 2>/dev/null || true
      useradd -r -g www-data -s /usr/sbin/nologin -d /var/www www-data 2>/dev/null || true
      echo "Re-created www-data user after upgrade restore."
  fi
else
  rm -f /etc/ssh/ssh_host_rsa_key
  rm -f /etc/ssh/ssh_host_ecdsa_key
  rm -f /etc/ssh/ssh_host_ed25519_key
  # Explicit sizes so fresh containers always get strong keys regardless of
  # the underlying ssh-keygen version's defaults.
  ssh-keygen -q -f /etc/ssh/ssh_host_rsa_key -N '' -t rsa -b 4096
  ssh-keygen -q -f /etc/ssh/ssh_host_ecdsa_key -N '' -t ecdsa -b 521
  ssh-keygen -q -f /etc/ssh/ssh_host_ed25519_key -N '' -t ed25519
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

# Migrate web app data from old volume to new volume (one-time)
if [ -f /root/bastion/users.db ] && [ ! -f /var/lib/bastion/users.db ]; then
    cp /root/bastion/users.db /var/lib/bastion/users.db
    echo "Migrated users.db to /var/lib/bastion/"
fi
if [ -f /root/bastion/secret_key ] && [ ! -f /var/lib/bastion/secret_key ]; then
    cp /root/bastion/secret_key /var/lib/bastion/secret_key
    echo "Migrated secret_key to /var/lib/bastion/"
fi
chown -R www-data:www-data /var/lib/bastion /var/log/bastion

# Warn if any persisted SSH host key is below current best-practice strength.
# Does NOT auto-rotate — fingerprint changes are a deliberate operator action
# (see /root/bin/rotate-host-keys.sh).
check_host_key_strength() {
    local key="$1"
    [ -f "$key" ] || return 0
    local info bits type
    info=$(ssh-keygen -l -f "$key" 2>/dev/null) || return 0
    bits=$(echo "$info" | awk '{print $1}')
    type=$(echo "$info" | sed -n 's/.*(\(.*\))$/\1/p')
    case "$type" in
        RSA)
            if [ "${bits:-0}" -lt 3072 ]; then
                echo "WARNING: $key is ${bits}-bit RSA (recommend >=3072). Rotate via: docker exec -it <container> /root/bin/rotate-host-keys.sh" >&2
            fi
            ;;
        ECDSA)
            if [ "${bits:-0}" -lt 384 ]; then
                echo "NOTICE: $key is ${bits}-bit ECDSA. A 521-bit curve is available via /root/bin/rotate-host-keys.sh." >&2
            fi
            ;;
    esac
}
for k in /etc/ssh/ssh_host_rsa_key /etc/ssh/ssh_host_ecdsa_key /etc/ssh/ssh_host_ed25519_key; do
    check_host_key_strength "$k"
done

# Configurable Gunicorn workers (default: 2)
GUNICORN_WORKERS=${GUNICORN_WORKERS:-2}
if ! [[ "$GUNICORN_WORKERS" =~ ^[0-9]+$ ]] || [ "$GUNICORN_WORKERS" -lt 1 ]; then
    echo "WARNING: Invalid GUNICORN_WORKERS value '$GUNICORN_WORKERS', defaulting to 2"
    GUNICORN_WORKERS=2
fi

# Run one-shot Python migrations (e.g. SECRET_KEY rotation) as the web user
# before starting gunicorn. Kept single-threaded so multi-worker races can't
# corrupt on-disk state.
su -s /bin/bash www-data -c "/opt/venv/bin/python /opt/bastion/web/migrate.py" || \
    echo "WARNING: web migrate.py exited non-zero; continuing to start gunicorn"

# Switch to accessible directory before running gunicorn as www-data
cd /

# Remove stale gunicorn control socket if present
rm -f /tmp/gunicorn.ctl

# Common Gunicorn options
GUNICORN_OPTS="--error-logfile /var/log/bastion/gunicorn-error.log --access-logfile /var/log/bastion/gunicorn-access.log --control-socket /tmp/gunicorn.ctl"

# Start Gunicorn as www-data and optionally Nginx for HTTPS
if [ -f "/etc/bastion/certs/fullchain.pem" ] && [ -f "/etc/bastion/certs/privkey.pem" ]; then
    echo "TLS certificates found. Starting Nginx with HTTPS on port 443."
    su -s /bin/bash www-data -c "/opt/venv/bin/gunicorn -w $GUNICORN_WORKERS -b 127.0.0.1:8000 --daemon --chdir /opt/bastion/web/ $GUNICORN_OPTS wsgi:app"
    nginx
else
    echo "No TLS certificates found at /etc/bastion/certs/. Running without HTTPS on port 8000."
    su -s /bin/bash www-data -c "/opt/venv/bin/gunicorn -w $GUNICORN_WORKERS -b 0.0.0.0:8000 --daemon --chdir /opt/bastion/web/ $GUNICORN_OPTS wsgi:app"
fi

# Verify Gunicorn started successfully
sleep 2
if ! pgrep -f "gunicorn.*wsgi:app" > /dev/null; then
    echo "ERROR: Gunicorn failed to start. Check /var/log/bastion/gunicorn-error.log"
    cat /var/log/bastion/gunicorn-error.log 2>/dev/null
    echo "Retrying Gunicorn startup..."
    if [ -f "/etc/bastion/certs/fullchain.pem" ] && [ -f "/etc/bastion/certs/privkey.pem" ]; then
        su -s /bin/bash www-data -c "/opt/venv/bin/gunicorn -w $GUNICORN_WORKERS -b 127.0.0.1:8000 --daemon --chdir /opt/bastion/web/ $GUNICORN_OPTS wsgi:app"
    else
        su -s /bin/bash www-data -c "/opt/venv/bin/gunicorn -w $GUNICORN_WORKERS -b 0.0.0.0:8000 --daemon --chdir /opt/bastion/web/ $GUNICORN_OPTS wsgi:app"
    fi
    sleep 2
    if pgrep -f "gunicorn.*wsgi:app" > /dev/null; then
        echo "Gunicorn started successfully on retry."
    else
        echo "ERROR: Gunicorn failed to start after retry."
        cat /var/log/bastion/gunicorn-error.log 2>/dev/null
    fi
else
    echo "Gunicorn started successfully."
fi

/usr/sbin/sshd -f /etc/ssh/sshd_config -D -e
