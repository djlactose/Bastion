#!/bin/bash
# Per-user target restrictions: limit which host:port destinations an SSH user
# may reach through this bastion.
#
#   restrictions.sh set       replace all restrictions with the list on stdin
#   restrictions.sh apply     re-apply the stored list (container start, DNS refresh)
#   restrictions.sh status    print "firewall=yes" or "firewall=no"
#
# Input / state format, one destination per line:
#   <user> <host> <port>      the user may reach host:port
#   <user> - -                the user is restricted and has no destinations
# A user that does not appear is unrestricted.
#
# Two layers are generated from the list:
#   1. An sshd drop-in with "Match User" + PermitOpen, which limits SSH port
#      forwarding (what servers.sh uses).
#   2. An nftables table matching each restricted user's UID on outbound
#      traffic. This is what covers accounts with a shell: without it a user
#      could simply run ssh or nc on the bastion itself. It needs the
#      container to have the NET_ADMIN capability; without it only layer 1 is
#      in force and "status" reports firewall=no.
#
# Runs as root via sudo from the web app (www-data), so every field is
# validated here again and only regular login users (UID >= 1000) are touched.
STATE=/root/bastion/restrictions
DROPIN=/etc/ssh/sshd_config.d/30-bastion-restrictions.conf
TABLE=bastion_restrict
MAX_LINES=5000

user_re='^[a-z_][a-z0-9_-]{0,31}$'
host_re='^[a-zA-Z0-9._-]{1,253}$'
ipv4_re='^([0-9]{1,3}\.){3}[0-9]{1,3}$'
ipv6_re='^[0-9a-fA-F:]{2,39}$'

action="$1"

firewall_capable() {
    command -v nft >/dev/null 2>&1 && nft list tables >/dev/null 2>&1
}

is_login_user() {
    local uid
    uid=$(id -u "$1" 2>/dev/null) || return 1
    [ "$uid" -ge 1000 ] && [ "$1" != "nobody" ]
}

# Users named in a state file that exist as regular login users.
restricted_users() {
    local u
    awk '{print $1}' "$1" 2>/dev/null | sort -u | while read -r u; do
        is_login_user "$u" && echo "$u"
    done
}

# Validate the list on stdin and write it, normalised and sorted, to $1.
read_spec() {
    local out="$1" raw n=0 user host port extra
    raw=$(mktemp) || return 1
    while read -r user host port extra || [ -n "$user" ]; do
        [ -z "$user" ] && continue
        n=$((n + 1))
        if [ "$n" -gt "$MAX_LINES" ]; then
            echo "Too many entries (maximum $MAX_LINES)." >&2; rm -f "$raw"; return 2
        fi
        if ! [[ "$user" =~ $user_re ]] || [ -n "$extra" ]; then
            echo "Entry $n is not valid." >&2; rm -f "$raw"; return 2
        fi
        if [ "$host" = "-" ] && [ "$port" = "-" ]; then
            echo "$user - -" >> "$raw"
            continue
        fi
        if ! [[ "$host" =~ $host_re ]] || [[ "$host" == -* ]] || [[ "$host" == *..* ]]; then
            echo "Entry $n has an invalid host." >&2; rm -f "$raw"; return 2
        fi
        if ! [[ "$port" =~ ^[0-9]{1,5}$ ]] || [ "$((10#$port))" -lt 1 ] || [ "$((10#$port))" -gt 65535 ]; then
            echo "Entry $n has an invalid port." >&2; rm -f "$raw"; return 2
        fi
        echo "$user $host $((10#$port))" >> "$raw"
    done < <(head -c 524288 | tr -d '\r')
    sort -u "$raw" > "$out"
    rm -f "$raw"
}

# Write the sshd drop-in for state file $1 to $2.
build_sshd_dropin() {
    local state="$1" out="$2" u opens
    : > "$out"
    for u in $(restricted_users "$state"); do
        opens=$(awk -v u="$u" '$1 == u && $2 != "-" {printf " %s:%s", $2, $3}' "$state")
        {
            echo "Match User $u"
            echo "    PermitOpen${opens:- none}"
            echo "    AllowStreamLocalForwarding no"
        } >> "$out"
    done
    # Close the last Match block so nothing included after this file can end
    # up inside it.
    [ -s "$out" ] && echo "Match all" >> "$out"
    return 0
}

# Install the drop-in built from state file $1. Returns 1 (leaving the old one
# in place) if sshd would refuse the resulting configuration.
install_sshd_dropin() {
    local state="$1" new old
    new=$(mktemp) || return 1
    build_sshd_dropin "$state" "$new"
    mkdir -p "$(dirname "$DROPIN")"
    if [ -f "$DROPIN" ] && cmp -s "$new" "$DROPIN"; then
        rm -f "$new"
        return 0
    fi
    if [ ! -s "$new" ] && [ ! -f "$DROPIN" ]; then
        rm -f "$new"
        return 0
    fi
    old=$(mktemp) || { rm -f "$new"; return 1; }
    [ -f "$DROPIN" ] && cp "$DROPIN" "$old"
    if [ -s "$new" ]; then
        cp "$new" "$DROPIN"
        chmod 644 "$DROPIN"
    else
        rm -f "$DROPIN"
    fi
    if ! /usr/sbin/sshd -t -f /etc/ssh/sshd_config 2>/dev/null; then
        if [ -s "$old" ]; then cp "$old" "$DROPIN"; else rm -f "$DROPIN"; fi
        rm -f "$new" "$old"
        echo "sshd rejected the generated restrictions; nothing was changed." >&2
        return 1
    fi
    rm -f "$new" "$old"
    # Running sshd re-reads its configuration on SIGHUP. Not running yet at
    # container start, where this is called before sshd is launched.
    if [ -s /run/sshd.pid ]; then
        kill -HUP "$(cat /run/sshd.pid)" 2>/dev/null
    fi
    return 0
}

# Addresses for a host: itself if it is an IPv4 literal, else what it resolves to.
resolve_host() {
    if [[ "$1" =~ $ipv4_re ]]; then
        echo "$1"
    else
        getent ahosts "$1" 2>/dev/null | awk '{print $1}' | sort -u
    fi
}

# Load the firewall rules for state file $1. Returns 1 if they could not be loaded.
apply_firewall() {
    local state="$1" rules users u uid host port addr ns
    users=$(restricted_users "$state")
    if ! firewall_capable; then
        [ -z "$users" ]
        return
    fi
    rules=$(mktemp) || return 1
    {
        # Declare-then-delete makes the replacement atomic whether or not the
        # table already exists.
        echo "table inet $TABLE"
        echo "delete table inet $TABLE"
        if [ -n "$users" ]; then
            echo "table inet $TABLE {"
            for u in $users; do
                uid=$(id -u "$u")
                echo "    chain u$uid {"
                while read -r _ host port; do
                    [ "$host" = "-" ] && continue
                    for addr in $(resolve_host "$host"); do
                        if [[ "$addr" =~ $ipv4_re ]]; then
                            echo "        ip daddr $addr tcp dport $port accept"
                        elif [[ "$addr" =~ $ipv6_re ]]; then
                            echo "        ip6 daddr $addr tcp dport $port accept"
                        fi
                    done
                done < <(awk -v u="$u" '$1 == u' "$state")
                # The bastion's own web admin (and the HTTPS front end for it)
                # is a destination like any other: reachable only when granted
                # above. Everything else on loopback stays available (the
                # container's DNS resolver, X11 forwarding).
                echo '        oifname "lo" tcp dport { 80, 443, 8000 } reject with tcp reset'
                echo '        oifname "lo" accept'
                while read -r ns; do
                    if [[ "$ns" =~ $ipv4_re ]]; then
                        echo "        ip daddr $ns meta l4proto { tcp, udp } th dport 53 accept"
                    elif [[ "$ns" =~ $ipv6_re ]]; then
                        echo "        ip6 daddr $ns meta l4proto { tcp, udp } th dport 53 accept"
                    fi
                done < <(awk '$1 == "nameserver" {print $2}' /etc/resolv.conf 2>/dev/null)
                echo "        meta l4proto tcp counter reject with tcp reset"
                echo "        counter reject"
                echo "    }"
            done
            echo "    chain output {"
            echo "        type filter hook output priority 0; policy accept;"
            for u in $users; do
                uid=$(id -u "$u")
                echo "        meta skuid $uid jump u$uid"
            done
            echo "    }"
            echo "}"
        fi
    } > "$rules"
    if ! nft -f "$rules" 2>/dev/null; then
        rm -f "$rules"
        return 1
    fi
    rm -f "$rules"
    return 0
}

report_firewall() {
    if [ "$1" = "0" ] && firewall_capable; then
        echo "firewall=yes"
    else
        echo "firewall=no"
    fi
}

case "$action" in
    status)
        fw=0
        if [ -n "$(restricted_users "$STATE")" ] && ! nft list table inet "$TABLE" >/dev/null 2>&1; then
            fw=1
        fi
        report_firewall "$fw"
        ;;
    apply)
        [ -f "$STATE" ] || exit 0
        install_sshd_dropin "$STATE" || exit 1
        apply_firewall "$STATE"
        fw=$?
        report_firewall "$fw"
        if [ "$fw" != "0" ]; then
            echo "WARNING: target restrictions are configured but the firewall rules could not be loaded. Restricted users are limited for SSH port forwarding only; start the container with --cap-add=NET_ADMIN to also confine their shell sessions." >&2
        fi
        ;;
    set)
        new=$(mktemp) || exit 1
        trap 'rm -f "$new"' EXIT
        read_spec "$new" || exit 2
        old=$(mktemp) || exit 1
        trap 'rm -f "$new" "$old"' EXIT
        [ -f "$STATE" ] && cp "$STATE" "$old"
        install_sshd_dropin "$new" || exit 1
        install -m 600 "$new" "$STATE"
        apply_firewall "$STATE"
        fw=$?
        # Rules for forwarding are fixed when a session logs in, so end the
        # open sessions of every user whose list changed.
        for u in $(cat "$old" "$new" | awk '{print $1}' | sort -u); do
            if [ "$(awk -v u="$u" '$1 == u' "$old")" != "$(awk -v u="$u" '$1 == u' "$new")" ] && is_login_user "$u"; then
                pkill -KILL -u "$u" 2>/dev/null
            fi
        done
        report_firewall "$fw"
        ;;
    *)
        echo "Usage: restrictions.sh set|apply|status" >&2
        exit 2
        ;;
esac
exit 0
