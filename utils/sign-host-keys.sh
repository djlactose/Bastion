#!/bin/bash
# Sign the bastion's SSH host keys with this install's own SSH CA.
#
# Called from run.sh on every container start and from rotate-host-keys.sh.
# Clients that opt in to host verification (verify_host in servers.conf) trust
# the CA rather than an individual host key, so:
#   - replicas behind one name can each keep their own host key, as long as
#     they share the CA files below, and
#   - host keys can be rotated without any client seeing a warning.
#
# The CA is a plain key pair, generated once and kept on the persistent
# /root/bastion volume:
#   /root/bastion/ssh_host_ca       (private, root only)
#   /root/bastion/ssh_host_ca.pub
# To run several replicas behind one name, copy both files to every replica's
# /root/bastion volume before enabling verification in the web UI.
#
# Existing host keys are never modified. Every failure here is non-fatal:
# without a certificate sshd simply serves its plain host keys as before.

CA=/root/bastion/ssh_host_ca
DROPIN_DIR=/etc/ssh/sshd_config.d
DROPIN="$DROPIN_DIR/10-bastion-hostcert.conf"
PUBLISHED=/etc/bastion/ssh_ca.pub

if [ "$(id -u)" -ne 0 ]; then
    echo "sign-host-keys.sh must be run as root." >&2
    exit 1
fi

if [ ! -f "$CA" ]; then
    mkdir -p /root/bastion
    if ! ssh-keygen -q -t ed25519 -N '' -C 'bastion-host-ca' -f "$CA"; then
        echo "WARNING: could not generate the SSH host CA; host certificates disabled." >&2
        exit 0
    fi
    echo "Generated a new SSH host CA at $CA"
fi
chmod 600 "$CA"
if [ ! -f "$CA.pub" ]; then
    ssh-keygen -y -f "$CA" > "$CA.pub" || { echo "WARNING: could not derive $CA.pub" >&2; exit 0; }
fi

mkdir -p "$DROPIN_DIR"
tmp="$DROPIN.tmp"
: > "$tmp"
for keytype in rsa ecdsa ed25519; do
    key="/etc/ssh/ssh_host_${keytype}_key"
    [ -f "$key.pub" ] || continue
    rm -f "$key-cert.pub"
    # -h: host certificate. ssh refuses a host certificate without a principal
    # list, and the principal must equal the name the client looks the host up
    # under. servers.sh always connects with HostKeyAlias=bastion-host, so this
    # one fixed principal is valid whatever name, address or load balancer the
    # bastion is reached through. (A wildcard principal would also work, but
    # only OpenSSH 10+ clients accept those.) Keep in sync with bastionAlias in
    # servers.sh.
    if ssh-keygen -q -s "$CA" -I "bastion-host-${keytype}" -h -n 'bastion-host' "$key.pub" 2>/dev/null \
        && [ -f "$key-cert.pub" ]; then
        echo "HostCertificate $key-cert.pub" >> "$tmp"
    else
        echo "WARNING: could not sign $key.pub; it will be served without a certificate." >&2
    fi
done
mv -f "$tmp" "$DROPIN"
chmod 644 "$DROPIN"

# Publish the CA public key (type and key only, no comment) for the web app
# and for servers.conf.
ca_pub=$(awk '{print $1" "$2}' "$CA.pub")
if [[ "$ca_pub" =~ ^ssh-ed25519\ [A-Za-z0-9+/=]+$ ]] && [ -d /etc/bastion ]; then
    # Stage in a root-only directory, then rename into the (group-writable)
    # config directory, so root never opens a path there for writing.
    printf '%s\n' "$ca_pub" > /root/bastion/.ssh_ca.pub.tmp \
        && mv -f /root/bastion/.ssh_ca.pub.tmp "$PUBLISHED"
    chmod 644 "$PUBLISHED"
    # Keep an existing host_ca= line in servers.conf current. The line is only
    # ever updated, never added: a config without it stays in legacy mode.
    conf=/etc/bastion/servers.conf
    if [ -f "$conf" ] && [ ! -L "$conf" ] && grep -q '^host_ca=' "$conf"; then
        if ! grep -qxF "host_ca=\"$ca_pub\"" "$conf"; then
            updated=$(sed "s|^host_ca=.*|host_ca=\"$ca_pub\"|" "$conf")
            # Rewrite in place (no new inode) so ownership and mode are kept.
            # When the web user owns the file, write as that user so root
            # never writes through a path the web user controls.
            if [ "$(stat -c %U "$conf")" = "www-data" ]; then
                printf '%s\n' "$updated" | su -s /bin/sh www-data -c 'cat > /etc/bastion/servers.conf'
            else
                printf '%s\n' "$updated" > "$conf"
            fi
        fi
    fi
fi
exit 0
