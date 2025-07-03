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
  -p 8000:8000 \  # Optional web interface
  -v /home:/home \
  -v /root/bastion:/root/bastion \
  -v /etc/bastion:/etc/bastion \
  -v /root/web/instance:/root/web/instance \
  --name bastion djlactose/bastion
```

> 📌 Make sure the volume paths exist to maintain persistent configuration and user data.

### Building Locally

To build the Docker image from source:

```bash
docker build -t bastion .
```

Then run using the same instructions as above, replacing `djlactose/bastion` with `bastion`.

### Minimal Setup (Non-Docker)

To run Bastion outside of Docker:

1. Use `servers.sh` to start the service
2. Configure it using `servers.conf`

Other scripts are optional and assist with setup and development.

## Persistent Volumes

For proper operation and data persistence, mount the following directories:

- `/home`
- `/root/bastion`
- `/etc/bastion`
- `/root/web/instance` *(only needed if using the web interface)*

## Ports

| Port | Purpose                                 |
|------|-----------------------------------------|
| 22   | SSH entry point to the bastion          |
| 8000 | (Optional) Web interface for session access (Beta) |

## Development Environment

This project includes `.devcontainer` support for Visual Studio Code to simplify setting up a consistent development environment.

## File Overview

| File/Script            | Purpose                                                  |
|------------------------|----------------------------------------------------------|
| `servers.sh`           | Main startup script for the bastion host                |
| `servers.conf`         | Bastion configuration file                              |
| `run.sh`               | Script to initialize services or run the container      |
| `docker publish.ps1`   | PowerShell script to publish Docker image               |
| `.devcontainer/`       | VSCode development container configuration              |
| `Dockerfile`           | Docker build instructions for the bastion image         |

## License

This project is licensed under the terms of the included `LICENSE` file.

---

**Note:** This project is currently under development. Features such as the web interface are in beta and subject to change.
