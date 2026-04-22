# Bastion

**Bastion** is a collection of scripts and tools to configure a Linux-based system as a secure bastion (jump) host. It is designed to run either directly on Linux (including WSL on Windows) or inside a Docker container.

## Features

- Handles multiple remote access protocols
- Minimal setup for quick deployment
- Docker support for containerized operation
- Optional web interface for session access
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
  -p 8000:8000 \
  -v /home:/home \
  -v /root/bastion:/root/bastion \
  -v /etc/bastion:/etc/bastion \
  -v /var/lib/bastion:/var/lib/bastion \
  -v /var/log/bastion:/var/log/bastion \
  --name bastion djlactose/bastion
```

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
| 8000 | Web interface for session access (direct, no TLS)    |

## TLS/HTTPS (Optional)

To enable HTTPS via Nginx, place your TLS certificates in the `/etc/bastion/certs/` volume:

- `fullchain.pem`
- `privkey.pem`

When certificates are present, Nginx serves HTTPS on port 443 and the web interface binds to `127.0.0.1:8000` internally. Without certificates, the web interface is accessible directly on port 8000.

## Security

- The web interface (Gunicorn/Flask) runs as `www-data`, not root. Web app data is isolated in `/var/lib/bastion/` with restricted ownership.
- SSHD and Nginx run as root (required for privileged ports, PAM authentication, and user management).
- Session cookies are marked `Secure` when TLS certificates are present.
- Audit log at `/var/log/bastion/audit.log` records login attempts, config changes, and user-management actions. Control characters from user input are scrubbed to prevent log injection.
- Python dependencies are pinned in `web/requirements.txt` for reproducible builds.
- Docker image builds include SBOM and provenance attestations for supply chain verification.

### Key rotation

**Flask `SECRET_KEY` (automatic).** On every container start, `web/migrate.py` inspects `/var/lib/bastion/secret_key`. If the stored key is smaller than 32 bytes (older containers generated 24-byte keys), it is rotated in place: the previous key is moved to `secret_key.old` and a fresh 32-byte key is written. The old key is kept as a Flask `SECRET_KEY_FALLBACKS` entry so existing admin sessions and CSRF tokens remain valid through the rotation, then removed automatically on the next container start after a one-hour grace window. No operator action or session re-login required.

**SSH host keys (manual).** Run the rotation script via `docker exec` whenever you want to re-issue the bastion's host keys (e.g. when moving off legacy 2048-bit RSA, after a suspected compromise, or as part of a scheduled hygiene rotation):

```bash
docker exec -it bastion /root/bin/rotate-host-keys.sh
# non-interactive form:
docker exec bastion /root/bin/rotate-host-keys.sh --yes
```

The script backs up the current `/etc/ssh/ssh_host_*` keys to `/root/bastion/keys-rotated-<timestamp>/` (persistent volume), generates new RSA-4096 / ECDSA-P521 / Ed25519 keys, mirrors them back to `/root/bastion/` so the next upgrade persists them, and reloads `sshd` via `SIGHUP`. Existing SSH sessions are not interrupted. Any client whose `~/.ssh/known_hosts` pins the old fingerprint will see a host-key-changed warning and must accept the new fingerprint; clients using the bundled `servers.sh` are unaffected because it disables strict host-key checking. Rollback is a one-line `cp` from the backup directory printed at the end of the run.

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
     --security-opt=no-new-privileges \
     -p 22:22 -p 80:80 -p 443:443 -p 8000:8000 \
     -v /home:/home -v /root/bastion:/root/bastion \
     -v /etc/bastion:/etc/bastion -v /var/lib/bastion:/var/lib/bastion \
     -v /var/log/bastion:/var/log/bastion \
     --name bastion djlactose/bastion
   ```

   If your Scout policy allows per-image exceptions, configure `default-non-root-user` as "not applicable" for this image and document the capability-drop recipe above as the compensating control.

## Environment Variables

| Variable           | Default | Description                        |
|--------------------|---------|------------------------------------|
| `GUNICORN_WORKERS` | `2`     | Number of Gunicorn worker processes |

## File Overview

| File/Directory         | Purpose                                                  |
|------------------------|----------------------------------------------------------|
| `Dockerfile`           | Docker build instructions for the bastion image          |
| `run.sh`               | Container entrypoint: initializes SSH keys, starts Gunicorn and SSHD |
| `servers.sh`           | Client-side connection and tunneling script               |
| `docker publish.ps1`   | PowerShell script to build and publish Docker image       |
| `config/`              | SSH, PAM, Nginx, and sudoers configuration files          |
| `utils/`               | User management, backup/restore, and upgrade scripts      |
| `web/`                 | Flask web interface application                           |

## License

This project is licensed under the terms of the included `LICENSE` file.

---

**Note:** This project is currently under development. Features such as the web interface are in beta and subject to change.
