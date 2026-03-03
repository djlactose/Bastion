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
- Docker image builds include SBOM and provenance attestations for supply chain verification.

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
