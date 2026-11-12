# Bastion

**Bastion** is a collection of scripts and tools to configure a Linux-based system as a secure bastion (jump) host. It is designed to run either directly on Linux (including WSL on Windows) or inside a Docker container.

## Features

- Handles multiple remote access protocols
- Minimal setup for quick deployment
- Docker support for containerized operation
- Web admin interface for managing the client server list, menu theme, web admins, and SSH users (including Google Authenticator 2FA enrollment)
- SSH user lifecycle from the web interface: disable or re-enable an account, set an expiry date, manage public keys (including FIDO2 security keys), and re-issue a lost authenticator
- Two-factor login and passkeys for web administrators
- Activity page showing connected SSH sessions, recent SSH logins and the audit log
- Configuration export and import
- Persistent volume storage to preserve accounts and settings

## Getting Started

### Using the Prebuilt Docker Image

You can quickly get started using the prebuilt image available on Docker Hub:

```bash
docker pull djlactose/bastion
```

#### Release channels

The GitHub Actions pipeline publishes two channels and an immutable per-build tag:

| Tag | Source branch | Intended audience |
|------|---------------|-------------------|
| `latest`, `ubuntu` | `master` | Production rollouts |
| `beta` | `develop` | Canary / pre-release validation |
| `sha-<commit>` | Any push | Digest-pinnable rollback target (every build) |

For production we recommend pinning to a specific digest rather than a mutable tag so unreviewed rebuilds cannot auto-upgrade running containers:

```bash
docker image inspect djlactose/bastion:latest --format='{{range .RepoDigests}}{{.}}{{"\n"}}{{end}}'
# -> djlactose/bastion@sha256:<64-hex-digest>
docker run ... djlactose/bastion@sha256:<64-hex-digest>
```

To run:

```bash
docker run -d \
  -p 22:22 \
  -p 80:80 \
  -p 443:443 \
  -v /home:/home \
  -v /root/bastion:/root/bastion \
  -v /etc/bastion:/etc/bastion \
  -v /var/lib/bastion:/var/lib/bastion \
  -v /var/log/bastion:/var/log/bastion \
  --name bastion djlactose/bastion
```

Port 8000 (the web admin without TLS) is not published here because it listens on loopback inside the container by default and is reached through an SSH tunnel. See [Ports](#ports) and [First-run setup](#first-run-setup).

> 📌 Make sure the volume paths exist to maintain persistent configuration and user data.

### Building Locally

To build the Docker image from source:

```bash
docker build -t bastion .
```

Then run using the same instructions as above, replacing `djlactose/bastion` with `bastion`.

### Client Connection Script (Non-Docker)

The `servers.sh` script is a client-side tool for connecting through the bastion host via SSH tunnels. To use it outside of Docker:

1. Copy `servers.sh` to your local machine
2. Run it and follow the prompts to configure your bastion host address and port
3. A `servers.conf` configuration file will be downloaded from the bastion on first run

#### Connection types

Each server in the list has a connection type: one of the built-in codes (`W` RDP, `L` SSH, `B` web admin, etc., listed in the web interface's dropdown) or **Other**, which forwards a single port. An **Other** value must be a port number (1–65535). Free-text values are rejected because `servers.sh` passes them straight to `ssh`. Hostnames may contain only letters, digits, `.`, `-`, and `_`, and may not start with `-`.

#### Command-line options

| Option | Purpose |
|--------|---------|
| `-m`, `--multi` | Connect to several machines from one terminal window |
| `-x`, `--exit` | Close the terminal window when done |
| `-u`, `--update` | Check for a script and configuration update, then exit |
| `-a`, `--admin` | Open the Bastion Web Admin tunnel (`http://localhost:8000`) and exit, even if that entry was removed from the menu |
| `-c`, `--ssh-config` | Print an `ssh_config` snippet for the configured machines and exit |

`--ssh-config` is for people who prefer plain `ssh`, `scp`, `sftp` or an editor's remote feature. Append its output to `~/.ssh/config`: Linux machines become hosts reached through the bastion (`ssh Web-Server-1`), and every other entry becomes a `<name>-tunnel` host that opens the same port forward as the menu (`ssh -N SQL-Box-tunnel`).

The menu's **Change password** entry runs `passwd` on the bastion for the signed-in user. Password changes made this way are kept across container upgrades.

The script also runs on macOS for SSH and port-forward entries (this has not been tested on a Mac yet; Windows RDP entries are not supported there).

#### Menu colors

The `servers.sh` menus (drawn with `whiptail` or `dialog`) support color themes: `default`, `dark`, `blue`, `green`, `red`, `purple`, `cyan`, `amber`, and `custom`. An administrator selects the theme on the web interface's configuration page — each option shows a live preview of the menu colors — and the choice reaches every client through the auto-updating `servers.conf`.

The `custom` theme is fully configurable: picking it on the configuration page reveals six color roles (screen background, dialog background, text, title, highlight background, highlight text), each set to one of the eight ANSI colors (`black`, `red`, `green`, `yellow`, `blue`, `magenta`, `cyan`, `white`), with the preview card updating live as colors are chosen.

Individual users can override the pushed theme in their local hidden `.servers.cust` file (created next to the script on first run):

```bash
theme=dark                                                    # pick a named theme
theme=custom custom_bg=blue custom_fg=white                   # or build your own from the custom_* colors
custom_newt_colors='root=white,blue;window=black,lightgray'   # raw whiptail NEWT_COLORS override
custom_dialogrc=/path/to/dialogrc                             # raw dialog theme file override
```

Raw overrides take precedence over a named theme, and any setting in `.servers.cust` takes precedence over the server-pushed value.

## Persistent Volumes

For proper operation and data persistence, mount the following directories:

- `/home` — user home directories
- `/root/bastion` — SSH host keys and user account backups
- `/etc/bastion` — server configuration, TLS certificates
- `/var/lib/bastion` — web interface database and secret key
- `/var/log/bastion` — Gunicorn access and error logs

> **Upgrading from older versions:** If you previously used `/root/web/instance` for web data, it has been replaced by `/var/lib/bastion`. On first startup, existing data (`users.db`, `secret_key`) is automatically migrated from `/root/bastion/` to `/var/lib/bastion/`.

## Ports

| Port | Purpose                                              |
|------|------------------------------------------------------|
| 22   | SSH entry point to the bastion                       |
| 80   | HTTP (Nginx, only active with TLS certificates)      |
| 443  | HTTPS (Nginx, only active with TLS certificates)     |
| 8000 | Web admin interface without TLS (loopback only by default) |

### Reaching the web admin

Without TLS certificates the web interface listens on `127.0.0.1:8000` inside the container, so it is never exposed unencrypted on the network. Reach it through an SSH tunnel, using any of:

```bash
./servers.sh --admin                             # opens the tunnel and your browser
# or pick "Bastion Web Admin" in the servers.sh menu
ssh -L 8000:localhost:8000 <user>@<bastion>      # plain ssh, then open http://localhost:8000
```

Because the listener is on loopback, publishing the port with `-p 8000:8000` has no effect. To serve plain HTTP on all interfaces as releases before this change did, start the container with `-e WEB_BIND_ADDRESS=0.0.0.0` and publish the port. **Admin passwords then cross the network unencrypted**; prefer TLS or the tunnel.

> **Upgrading:** if you reached the web interface directly on port 8000, either switch to the tunnel above or add `-e WEB_BIND_ADDRESS=0.0.0.0` to keep the old behavior.

### First-run setup

On a fresh container with no web accounts, the web interface redirects to `/setup`, and **whoever reaches it first becomes the administrator**.

A fresh container has no SSH users yet, so there is nobody to open the tunnel as. Create the first SSH user from the Docker host, then tunnel in and complete setup:

```bash
docker exec -it bastion /root/bin/adduser.sh <username>    # prompts for a password, prints the authenticator QR code
ssh -L 8000:localhost:8000 <username>@<bastion>            # then open http://localhost:8000
```

Alternatively start the container once with `-e WEB_BIND_ADDRESS=0.0.0.0 -p 127.0.0.1:8000:8000`, complete setup from the Docker host at `http://localhost:8000`, and recreate it without those options.

To make sure nobody else can claim the administrator account first, start the container with `-e SETUP_TOKEN=<secret>`; the setup page then also asks for that value.

## TLS/HTTPS (Optional)

To enable HTTPS via Nginx, place your TLS certificates in the `/etc/bastion/certs/` volume:

- `fullchain.pem`
- `privkey.pem`

When certificates are present, Nginx serves HTTPS on port 443 and talks to the web interface over a private Unix socket; `127.0.0.1:8000` stays available for the SSH-tunnelled "Bastion Web Admin" connection. Without certificates, the web interface is available on port 8000 over plain HTTP, on loopback only unless `WEB_BIND_ADDRESS=0.0.0.0` is set (see [Reaching the web admin](#reaching-the-web-admin)).

## Host verification (SSH CA)

By default the `servers.sh` client historically accepted any SSH host key when connecting to the bastion, which lets someone on the network path impersonate it and capture a user's password and authenticator code. Host verification closes that gap without ever prompting users to accept a fingerprint.

- On first start each install generates its own SSH certificate authority: a key pair at `/root/bastion/ssh_host_ca` (private, root only) and `ssh_host_ca.pub`. No external CA or service is involved.
- On every start the container signs its SSH host keys with that CA. Existing host keys are not changed, so anyone connecting with plain `ssh` sees no difference.
- When **Verify bastion host identity** is switched on in the web interface, the CA public key and `verify_host="yes"` are written to `servers.conf`. Clients then require the bastion to present a certificate signed by that CA and refuse anything else. They use their own known-hosts file (`.servers.known_hosts` next to the script); `~/.ssh/known_hosts` is not touched.
- If the bastion has a publicly trusted TLS certificate, clients also fetch the CA key from `https://<bastion>/ssh-ca.pub`, which anchors the SSH identity in that certificate.
- Machines reached *through* the bastion (the `L` and `T` connection types) are remembered on first use and refused only if their key later changes. If a target is legitimately rebuilt, remove its entry with `ssh-keygen -R target-<address>-<port> -f .servers.known_hosts`.

**New installs** have verification on. **Existing installs keep their previous behavior** until an administrator switches it on, because one setup needs a manual step first:

> **Several bastions, or replicas behind one name.** Every bastion that clients can reach must present a certificate from the *same* CA. Copy `/root/bastion/ssh_host_ca` and `/root/bastion/ssh_host_ca.pub` from one container to the `/root/bastion` volume of all the others, restart them, and only then enable verification. Each container keeps its own host keys.

Because clients trust the CA rather than an individual key, host keys can be rotated and replicas added without any client noticing. Clients running an OpenSSH older than 7.6 ignore the setting and behave as before.

## Security

- The web interface (Gunicorn/Flask) runs as `www-data`, not root. Web app data in `/var/lib/bastion/` (admin database, secret key) and the logs in `/var/log/bastion/` are readable only by `www-data` and root, so SSH users with a shell in the container cannot read them.
- `/etc/bastion` is owned by root with the sticky bit set: the web interface can rewrite its own two config files but cannot replace `servers.sh` (which every client downloads and runs) or the `certs/` directory.
- The `servers.sh` client can verify the bastion's identity through a per-install SSH CA, see [Host verification](#host-verification-ssh-ca). Its self-update downloads into a private temporary directory and syntax-checks the result before installing it.
- Web sessions are revoked server-side on logout and on a password change, so a copied session cookie stops working. Logout is a POST protected by the CSRF token.
- Responses carry a `Content-Security-Policy` limiting scripts, styles and form posts to the app itself and the Bootstrap CDN, and `Cache-Control: no-store`.
- SSHD and Nginx run as root (required for privileged ports, PAM authentication, and user management).
- The `sudoers` allowlist lets `www-data` run only `adduser.sh`, `deluser.sh`, and `resetpw.sh`. Those scripts validate the username and refuse to touch root or any system account (UID < 1000), so a compromised web process cannot use them to take over root.
- Only administrators can sign in to the web interface, and an admin who is demoted loses their active session on their next request.
- Logins are rate-limited (5 per minute per client IP). `X-Forwarded-For` is trusted only on requests that reach the app from Nginx over its private Unix socket, so the limit can't be bypassed (or the audit log's IP forged) by sending that header to the port-8000 listener, including through an SSH tunnel.
- Session cookies are marked `Secure` when TLS certificates are present. The app sets `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, and `Referrer-Policy: same-origin` on every response; Nginx adds HSTS.
- Bootstrap assets are loaded from the CDN with Subresource Integrity hashes.
- Audit log at `/var/log/bastion/audit.log` records login attempts, config changes, and user-management actions. Control characters from user input are scrubbed to prevent log injection.
- Python dependencies, including transitive ones, are pinned by version and SHA-256 hash in `web/requirements.txt` (generated from `web/requirements.in`) and installed with `--require-hashes`. `pip` is uninstalled from the runtime image afterwards.
- Docker image builds include SBOM and provenance attestations for supply chain verification.

### Dependency patching (automated)

Keeping the image free of fixable CVEs is automated end to end:

1. **Detect + bump.** [Dependabot](.github/dependabot.yml) opens a PR whenever an upstream fix ships — immediately for security advisories, weekly for routine version updates. Python-package fixes bump a pin in `web/requirements.txt`; the GitHub Actions used in CI are kept current the same way. (The base image is intentionally *not* watched — it stays on Ubuntu 24.04 LTS, and OS CVEs are handled by step 3.)
2. **Verify (PR gate).** [`security-scan.yml`](.github/workflows/security-scan.yml) builds the image and runs **Trivy** on each PR, failing the check on any *fixable* HIGH/CRITICAL CVE (`--ignore-unfixed`, mirroring the manual `docker scout cves --only-fixed` loop). The same workflow runs **pip-audit** against the hash-pinned lockfile and **ShellCheck** against the shell scripts. Review the green PR and merge.
3. **Rebuild + publish.** Merging to `master` triggers [`docker-publish.yml`](.github/workflows/docker-publish.yml) (rebuild `--no-cache`, push `:latest`/`:ubuntu`). That workflow also runs **weekly on a schedule**, so OS-package CVEs from the Ubuntu `-security` pocket are picked up by `apt-get upgrade` with no commit required. Both PR and publish scans upload findings to the repo **Security** tab.

Accepted/false-positive suppressions live in [`.trivyignore`](.trivyignore). For a manual local spot-check you can still run `docker scout cves --only-fixed` (or `trivy image --ignore-unfixed --severity HIGH,CRITICAL <image>`) against a freshly built image.

### Key rotation

**Flask `SECRET_KEY` (automatic).** On every container start, `web/migrate.py` inspects `/var/lib/bastion/secret_key`. If the stored key is smaller than 32 bytes (older containers generated 24-byte keys), it is rotated in place: the previous key is moved to `secret_key.old` and a fresh 32-byte key is written. The old key is kept as a Flask `SECRET_KEY_FALLBACKS` entry so existing admin sessions and CSRF tokens remain valid through the rotation, then removed automatically on the next container start after a one-hour grace window. No operator action or session re-login required.

**SSH host keys (manual).** Run the rotation script via `docker exec` whenever you want to re-issue the bastion's host keys (e.g. when moving off legacy 2048-bit RSA, after a suspected compromise, or as part of a scheduled hygiene rotation):

```bash
docker exec -it bastion /root/bin/rotate-host-keys.sh
# non-interactive form:
docker exec bastion /root/bin/rotate-host-keys.sh --yes
```

The script backs up the current `/etc/ssh/ssh_host_*` keys to `/root/bastion/keys-rotated-<timestamp>/` (persistent volume), generates new RSA-4096 / ECDSA-P521 / Ed25519 keys, mirrors them back to `/root/bastion/` so the next upgrade persists them, and reloads `sshd` via `SIGHUP`. Existing SSH sessions are not interrupted. The new keys are signed with the install's SSH CA as part of the rotation. Any client whose own `~/.ssh/known_hosts` pins the old fingerprint will see a host-key-changed warning and must accept the new fingerprint; clients using the bundled `servers.sh` are unaffected, because with [host verification](#host-verification-ssh-ca) on they trust the CA rather than the individual key, and with it off they do not check the host key. Rollback is a one-line `cp` from the backup directory printed at the end of the run.

On every container start, `run.sh` emits a warning to stderr if any persisted host key is below current strength recommendations (`<3072-bit RSA`, `<384-bit ECDSA`) so older deployments surface the need for rotation in their logs.

### Running as a non-root user

Bastion is, by design, a multi-user SSH jump host. The container's main process (`sshd`) needs real root inside the container in order to:

- bind the privileged SSH port (22),
- read `/etc/shadow` for PAM password authentication,
- `setuid()` into each SSH user's login shell on connection,
- invoke `useradd` / `userdel` / `chpasswd` from the web UI (via a narrow `sudoers` allowlist).

Because of this the Dockerfile has no `USER` instruction, and Docker Scout's `default-non-root-user` policy will flag the image. The deviation is a genuine technical requirement, not an oversight. Operators have two good ways to mitigate it without modifying the image:

1. **Rootless Docker / Podman.** Running the container under user-namespace remapping causes UID 0 inside the container to map to an unprivileged UID on the host. A container escape then lands on a nobody-level host account rather than on real root. This is the highest-value hardening step.

2. **Drop Linux capabilities.** The default capability set given to a container includes ~30 root powers (raw sockets, loading kernel modules, mount, ptrace, etc.) that Bastion does not need. Start the container with only the capabilities it actually uses:

   ```bash
   docker run -d \
     --cap-drop=ALL \
     --cap-add=NET_BIND_SERVICE \
     --cap-add=SETUID \
     --cap-add=SETGID \
     --cap-add=CHOWN \
     --cap-add=FOWNER \
     --cap-add=DAC_OVERRIDE \
     --cap-add=DAC_READ_SEARCH \
     --cap-add=AUDIT_WRITE \
     --cap-add=SYS_CHROOT \
     -p 22:22 -p 80:80 -p 443:443 \
     -v /home:/home -v /root/bastion:/root/bastion \
     -v /etc/bastion:/etc/bastion -v /var/lib/bastion:/var/lib/bastion \
     -v /var/log/bastion:/var/log/bastion \
     --name bastion djlactose/bastion
   ```

   If you [limit users to certain machines](#limiting-a-user-to-certain-machines), also add `--cap-add=NET_ADMIN` so the limit covers shell sessions.

   Do not add `--security-opt=no-new-privileges`: the web interface creates, deletes and resets SSH users through `sudo`, which that flag blocks, so those actions fail.

   If your Scout policy allows per-image exceptions, configure `default-non-root-user` as "not applicable" for this image and document the capability-drop recipe above as the compensating control.

## Web interface features

### SSH users

On the **System Users** page each SSH user has:

- **Disable / Enable.** Disabling blocks every kind of login, including public keys, and ends the user's open sessions. The account, home directory and authenticator are kept.
- **Set expiry.** Logins stop working on the chosen date, for temporary access.
- **SSH Keys.** View, add and remove the user's public keys. Only plain public keys are accepted (no key options). FIDO2 security keys (`sk-ssh-ed25519@openssh.com`, `sk-ecdsa-sha2-nistp256@openssh.com`) are supported and labelled.
- **Reset Authenticator.** Issues a new Google Authenticator secret and shows its QR code once, for a user who lost their phone. Nothing else about the account changes.
- **Allowed Machines.** Limits the user to the machines you tick from the configured list. See below.

#### Limiting a user to certain machines

By default every SSH user can reach any machine through the bastion. On **Allowed Machines** you can limit a user to chosen entries of the server list; the user can then connect only to those addresses and ports. Users you never restrict are unaffected. Saving a change ends that user's open sessions.

The limit is enforced in two layers:

1. **SSH port forwarding** (everything the `servers.sh` menu does) is restricted by `sshd`. This always applies.
2. **Shell sessions on the bastion** are restricted by a firewall rule on the user's outbound connections, so running `ssh` or `nc` from a shell on the bastion is covered too. This layer needs the container to be started with `--cap-add=NET_ADMIN`. Without it the page shows a warning, and a restricted user with a shell can still connect onward from that shell.

Notes:

- A restricted user can still sign in to the bastion itself. The "Bastion Host SSH" and "SOCKS Proxy" entries cannot be ticked because they have no fixed destination; a restricted user's SOCKS proxy only reaches their allowed machines.
- The bastion's own web admin is treated like any other machine: a restricted user reaches it only if the "Bastion Web Admin" entry is ticked.
- If you change a machine's address or connection type on the configuration page, it is removed from users' lists; tick it again. A restricted user never becomes unrestricted this way.
- Machines given as hostnames are resolved when the rules are loaded and again every 10 minutes.
- The `servers.sh` menu still lists every machine; connections to ones that are not allowed fail.
- Restrictions are included in the configuration export. Importing a file that contains them replaces the current ones.

By default a public key lets a user sign in without their password and authenticator code. Two optional container settings change that (see [Environment Variables](#environment-variables)): `SSH_REQUIRE_KEY_AND_2FA` makes a key login also pass the password and code prompts, and `SSH_PUBKEY_SECURITY_KEYS_ONLY` accepts only FIDO2 security keys and requires their PIN or biometric, so a key login is two-factor on its own. Security keys need a hardware key (or Windows Hello) and OpenSSH 8.2 or later on the client; passkeys synced through iCloud or a Google account cannot be used for SSH.

### Administrator sign-in

- **Two-factor login** (shield icon in the navigation bar). Each administrator can add an authenticator-app code to their sign-in and receives eight one-time recovery codes.
- **Passkeys** (fingerprint icon). An administrator can register passkeys and use **Sign in with a passkey** on the login page instead of a password. A passkey only works on the address it was registered on: one registered through the SSH tunnel (`http://localhost:8000`) does not work on `https://bastion.example.com`, so register one for each address you use. Browsers only allow passkeys over HTTPS or on `localhost`. The password remains available as a fallback.

### Activity

The **Activity** page lists the SSH sessions currently connected, recent SSH logins and failures, and the last 200 entries of the web audit log.

### Backup and restore of the configuration

**Export** on the configuration page downloads the saved server list and settings as JSON; **Import** replaces them from such a file, checked by the same rules as the form.

### Logs and alerts

`AUDIT_LOG_STDOUT`, `SYSLOG_ADDRESS` and `ALERT_WEBHOOK_URL` (see below) send the web audit log to the container log, to a syslog collector, or selected events (failed logins, account and configuration changes) to a webhook as JSON with a `text` field.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `GUNICORN_WORKERS` | `2` | Number of Gunicorn worker processes |
| `WEB_BIND_ADDRESS` | `127.0.0.1` | Address of the plain-HTTP web listener on port 8000 when no TLS certificates are installed. Set to `0.0.0.0` to expose it on all interfaces (unencrypted). |
| `SETUP_TOKEN` | unset | When set, creating the first administrator on `/setup` also requires this value. |
| `SSH_REQUIRE_KEY_AND_2FA` | unset | Set to `true` so that a public-key login must also pass the password and authenticator-code prompts. By default a key in `authorized_keys` is sufficient on its own. |
| `SSH_DISABLE_X11_AGENT_FORWARDING` | unset | Set to `true` to turn off X11 and SSH agent forwarding. |
| `SSH_PUBKEY_SECURITY_KEYS_ONLY` | unset | Set to `true` to accept only FIDO2 security keys for public-key logins, with the key's PIN or biometric required. Password + authenticator-code logins are unaffected. |
| `TLS_SELF_SIGNED` | unset | Set to `true` to generate a self-signed certificate in `/etc/bastion/certs/` when none is present, so the web interface is served over HTTPS on port 443. Browsers will warn about the certificate. `TLS_SELF_SIGNED_NAMES` adds comma-separated host names or IP addresses to it. |
| `AUDIT_LOG_STDOUT` | unset | Set to `true` to copy web audit log entries to the container log, prefixed with `[audit]`. |
| `SYSLOG_ADDRESS` | unset | `host:port` of a UDP syslog collector that should also receive web audit log entries. |
| `ALERT_WEBHOOK_URL` | unset | URL that receives a JSON POST for failed logins and for account and configuration changes. |

## File Overview

| File/Directory         | Purpose                                                  |
|------------------------|----------------------------------------------------------|
| `Dockerfile`           | Docker build instructions for the bastion image          |
| `run.sh`               | Container entrypoint: initializes SSH keys, starts Gunicorn and SSHD |
| `servers.sh`           | Client-side connection and tunneling script               |
| `docker publish.ps1`   | PowerShell script to build and publish Docker image       |
| `config/`              | SSH, PAM, Nginx, and sudoers configuration files          |
| `utils/`               | User management, backup/restore, host-key signing and rotation, and upgrade scripts |
| `web/`                 | Flask web interface application                           |

## License

This project is licensed under the terms of the included `LICENSE` file.

---

**Note:** This project is currently under development. Features such as the web interface are in beta and subject to change.
