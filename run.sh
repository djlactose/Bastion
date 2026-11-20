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
# --remove-destination: replace the entry itself rather than writing through
# whatever is at that path.
cp --remove-destination /root/bin/servers.sh /etc/bastion/
cp --remove-destination /root/bin/servers.conf-sample /etc/bastion/
cp --remove-destination /root/bin/servers.json-sample /etc/bastion/

# Sign the SSH host keys with this install's SSH CA and publish the CA public
# key (see sign-host-keys.sh). Never fatal: without certificates sshd serves
# its plain host keys exactly as before.
/root/bin/sign-host-keys.sh || echo "WARNING: sign-host-keys.sh failed; continuing without host certificates"

# Optional sshd hardening, off unless requested through the environment so
# existing deployments behave exactly as before.
SSHD_OPTIONS_DROPIN=/etc/ssh/sshd_config.d/20-bastion-options.conf
mkdir -p /etc/ssh/sshd_config.d
: > "$SSHD_OPTIONS_DROPIN"
is_true() {
    case "${1,,}" in
        1|true|yes|on) return 0 ;;
        *) return 1 ;;
    esac
}
if is_true "${SSH_REQUIRE_KEY_AND_2FA:-}"; then
    # A public key alone is no longer enough: the PAM prompts (password and
    # authenticator code) must also be passed. Password + code logins still work.
    echo "AuthenticationMethods publickey,keyboard-interactive keyboard-interactive" >> "$SSHD_OPTIONS_DROPIN"
    echo "SSH_REQUIRE_KEY_AND_2FA is set: public-key logins also require password and authenticator code."
fi
if is_true "${SSH_PUBKEY_SECURITY_KEYS_ONLY:-}"; then
    # Public-key logins are limited to FIDO2 security keys ("passkeys" for
    # SSH: sk-ssh-ed25519 / sk-ecdsa), and each login must be confirmed with
    # the key's PIN or biometric as well as a touch. A key login is then two
    # factors on its own. Password + authenticator-code logins are unaffected.
    echo "PubkeyAcceptedAlgorithms sk-ssh-ed25519@openssh.com,sk-ecdsa-sha2-nistp256@openssh.com,sk-ssh-ed25519-cert-v01@openssh.com,sk-ecdsa-sha2-nistp256-cert-v01@openssh.com" >> "$SSHD_OPTIONS_DROPIN"
    echo "PubkeyAuthOptions verify-required" >> "$SSHD_OPTIONS_DROPIN"
    echo "SSH_PUBKEY_SECURITY_KEYS_ONLY is set: only FIDO2 security keys are accepted for public-key logins."
fi
if is_true "${SSH_DISABLE_X11_AGENT_FORWARDING:-}"; then
    echo "X11Forwarding no" >> "$SSHD_OPTIONS_DROPIN"
    echo "AllowAgentForwarding no" >> "$SSHD_OPTIONS_DROPIN"
    echo "SSH_DISABLE_X11_AGENT_FORWARDING is set: X11 and agent forwarding are disabled."
fi

# Per-user target restrictions (set from the web interface). Does nothing
# unless an administrator has restricted at least one user. Never fatal.
/root/bin/restrictions.sh apply > /dev/null || echo "WARNING: restrictions.sh failed; target restrictions are not in force"

# Allow the web app (www-data) to update the live config files.
# /etc/bastion is a volume. The directory is root-owned, group-writable by
# www-data and sticky (like /tmp): the web app can create and rewrite its own
# two config files, but cannot delete or replace root-owned entries such as
# servers.sh (which every client downloads and runs) or an operator-mounted
# certs/ directory.
chown root:www-data /etc/bastion
chmod 1775 /etc/bastion
# -h: never follow a symlink the web user may have left in its place.
[ -f /etc/bastion/servers.conf ] && chown -h www-data:www-data /etc/bastion/servers.conf
[ -f /etc/bastion/servers.json ] && chown -h www-data:www-data /etc/bastion/servers.json

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
# Private one-time directory for Google Authenticator enrollment QR codes
# (written by adduser.sh, read once by the web app).
mkdir -p /var/lib/bastion/qr
chown -R www-data:www-data /var/lib/bastion /var/log/bastion
# SSH users have a shell in this container. Keep the web admin database,
# secret key and logs out of their reach.
chmod 700 /var/lib/bastion /var/lib/bastion/qr
chmod 750 /var/log/bastion
[ -f /var/lib/bastion/users.db ] && chmod 600 /var/lib/bastion/users.db
[ -f /var/lib/bastion/users.db.bak ] && chmod 600 /var/lib/bastion/users.db.bak

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

# Common Gunicorn options. --umask 0o077 keeps everything the web app creates
# (database, logs, its listening socket) private to www-data.
# --no-control-socket: Gunicorn 25.1+ otherwise opens a runtime-management
# socket (worker scaling, reload, shutdown) under the web user's home. Nothing
# here uses it, so keep it off and the listeners exactly as before.
GUNICORN_OPTS="--umask 0o077 --no-control-socket --error-logfile /var/log/bastion/gunicorn-error.log --access-logfile /var/log/bastion/gunicorn-access.log"

# Address for the plain-HTTP listener on port 8000 when no TLS certificates
# are installed. Defaults to loopback: the web admin is then reached through
# an SSH tunnel (the "Bastion Web Admin" menu entry, or `servers.sh --admin`)
# instead of being exposed, unencrypted, on the network.
# Set WEB_BIND_ADDRESS=0.0.0.0 to listen on all interfaces as older releases did.
WEB_BIND_ADDRESS=${WEB_BIND_ADDRESS:-127.0.0.1}
if [ "$WEB_BIND_ADDRESS" != "127.0.0.1" ] && [ "$WEB_BIND_ADDRESS" != "0.0.0.0" ]; then
    echo "WARNING: Invalid WEB_BIND_ADDRESS value '$WEB_BIND_ADDRESS' (use 127.0.0.1 or 0.0.0.0), defaulting to 127.0.0.1"
    WEB_BIND_ADDRESS=127.0.0.1
fi

# Optional: HTTPS without a supplied certificate. Only when asked for, and only
# when no certificate exists, so a deployment that relies on plain HTTP or
# that mounts its own certificate is never switched over by surprise.
if is_true "${TLS_SELF_SIGNED:-}" && [ ! -e /etc/bastion/certs/fullchain.pem ] && [ ! -e /etc/bastion/certs/privkey.pem ]; then
    # The directory must be root's own: /etc/bastion is group-writable by the
    # web user, who must not be able to supply the certificate directory.
    if [ ! -e /etc/bastion/certs ]; then
        mkdir -m 755 /etc/bastion/certs
    fi
    if [ -d /etc/bastion/certs ] && [ ! -L /etc/bastion/certs ] && [ "$(stat -c %u /etc/bastion/certs)" = "0" ]; then
        /opt/venv/bin/python /root/bin/gen-selfsigned.py
    else
        echo "WARNING: /etc/bastion/certs is not a root-owned directory; not generating a self-signed certificate."
    fi
fi

# Start Gunicorn as www-data and optionally Nginx for HTTPS
if [ -f "/etc/bastion/certs/fullchain.pem" ] && [ -f "/etc/bastion/certs/privkey.pem" ]; then
    echo "TLS certificates found. Starting Nginx with HTTPS on port 443."
    # Nginx reaches Gunicorn over a private Unix socket; the app only trusts
    # X-Forwarded-* headers on requests arriving that way. The loopback TCP
    # listener stays for the SSH-tunnelled "Bastion Web Admin" connection.
    mkdir -p /run/bastion
    chown www-data:www-data /run/bastion
    chmod 750 /run/bastion
    rm -f /run/bastion/gunicorn.sock
    GUNICORN_BIND="-b 127.0.0.1:8000 -b unix:/run/bastion/gunicorn.sock"
    START_NGINX=1
else
    echo "No TLS certificates found at /etc/bastion/certs/. Running without HTTPS on $WEB_BIND_ADDRESS:8000."
    if [ "$WEB_BIND_ADDRESS" = "127.0.0.1" ]; then
        echo "The web admin listens on loopback only. Reach it through an SSH tunnel:"
        echo "  ./servers.sh --admin      (or the 'Bastion Web Admin' menu entry)"
        echo "  ssh -L 8000:localhost:8000 <user>@<bastion>   then open http://localhost:8000"
        echo "To expose it directly on port 8000 instead, start the container with -e WEB_BIND_ADDRESS=0.0.0.0"
        if [ ! -s /var/lib/bastion/users.db ]; then
            echo "First run: no web administrator exists yet. Create an SSH user to tunnel with:"
            echo "  docker exec -it <container> /root/bin/adduser.sh <username>"
            echo "then open the tunnel and complete setup at http://localhost:8000"
        fi
    else
        echo "WARNING: the web admin is reachable over plain HTTP on all interfaces; admin passwords cross the network unencrypted."
    fi
    GUNICORN_BIND="-b $WEB_BIND_ADDRESS:8000"
    START_NGINX=0
fi

start_gunicorn() {
    su -s /bin/bash www-data -c "/opt/venv/bin/gunicorn -w $GUNICORN_WORKERS $GUNICORN_BIND --daemon --chdir /opt/bastion/web/ $GUNICORN_OPTS wsgi:app"
}
start_gunicorn
[ "$START_NGINX" = "1" ] && nginx

# Verify Gunicorn started successfully
sleep 2
if ! pgrep -f "gunicorn.*wsgi:app" > /dev/null; then
    echo "ERROR: Gunicorn failed to start. Check /var/log/bastion/gunicorn-error.log"
    cat /var/log/bastion/gunicorn-error.log 2>/dev/null
    echo "Retrying Gunicorn startup..."
    start_gunicorn
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

# Keep the backup of the account files current. Admin actions already call
# BackupUsers.sh, but a user changing their own password with `passwd` did
# not, so the new password was lost the next time the container was recreated
# (accounts are restored from /root/bastion on start).
(
    tick=0
    while sleep 60; do
        # Every 10 minutes, reload the target-restriction firewall rules so
        # destinations given as hostnames follow DNS changes.
        tick=$(( (tick + 1) % 10 ))
        if [ "$tick" -eq 0 ] && [ -s /root/bastion/restrictions ]; then
            /root/bin/restrictions.sh apply >/dev/null 2>&1
        fi
        # Only once a backup exists: its presence is what marks an install as
        # established on the next start, and that is left to the admin scripts.
        [ -f /root/bastion/shadow ] || continue
        if [ /etc/shadow -nt /root/bastion/shadow ] || [ /etc/passwd -nt /root/bastion/passwd ]; then
            /root/bin/BackupUsers.sh >/dev/null 2>&1
        fi
    done
) &

# Optional: copy the web audit log to the container log, for log collectors
# that read container stdout.
if is_true "${AUDIT_LOG_STDOUT:-}"; then
    touch /var/log/bastion/audit.log
    chown www-data:www-data /var/log/bastion/audit.log
    ( tail -n 0 -F /var/log/bastion/audit.log 2>/dev/null | sed -u 's/^/[audit] /' ) &
fi

# sshd logs to the container log as before (-e), and additionally to a file
# the web interface's activity page can read. The directory is root-owned and
# outside the web user's own log directory, so root never writes through a
# path that user controls.
SSHD_LOG_DIR=/var/log/bastion-sshd
mkdir -p "$SSHD_LOG_DIR"
chown root:www-data "$SSHD_LOG_DIR"
chmod 750 "$SSHD_LOG_DIR"
SSHD_LOG="$SSHD_LOG_DIR/sshd.log"
# Bounded: start a fresh file once it passes 5 MB, keeping one old copy.
if [ -f "$SSHD_LOG" ] && [ "$(stat -c %s "$SSHD_LOG")" -gt 5242880 ]; then
    mv -f "$SSHD_LOG" "$SSHD_LOG.1"
fi
touch "$SSHD_LOG"
chown root:www-data "$SSHD_LOG"
chmod 640 "$SSHD_LOG"

# Each line goes to the container log unchanged and to the file with a
# timestamp (sshd -e does not add one).
/usr/sbin/sshd -f /etc/ssh/sshd_config -D -e 2> >(
    while IFS= read -r line; do
        printf '%s\n' "$line" >&2
        printf '%(%Y-%m-%d %H:%M:%S)T %s\n' -1 "$line" >> "$SSHD_LOG"
    done
)
