# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**pyro-sys-setup** automates deployment of Pyronear wildfire detection hardware. It configures Reolink IP cameras and sets up Raspberry Pi edge devices that run [pyro-engine](https://github.com/pyronear/pyro-engine).

## Commands

### Camera setup
```bash
# Install dependencies
pip install -r requirements.txt

# Configure all cameras defined in cameras_config.json
python setup_reolink_cameras.py
```

### Raspberry Pi setup
```bash
# Full RPi provisioning (run from host machine via SSH)
bash setup_rpi.sh
```

### Linting
```bash
# YAML linting (also runs in CI via .github/workflows/yamllint.yml)
yamllint .
```

## Configuration Files

- **`.env`**: Camera credentials (`CAM_USER`, `CAM_PWD`)
- **`cameras_config.json`**: List of cameras with their current IPs, type (`static` or `ptz`), and target `LocalLink` static IP settings
- **`rpi_config.env`**: All paths and credentials needed by `setup_rpi.sh`: SSH key directory, OpenVPN config path, pyro-engine `.env`/`credentials.json` paths, WiFi credentials, network interface settings

## Architecture

### Camera Configuration (`setup_reolink_cameras.py`)

The `ReolinkCamera` class communicates with cameras over HTTPS using Reolink's CGI API (`/cgi-bin/api.cgi`). The `setup()` method orchestrates all configuration steps:

1. `set_osd()` — removes overlays (watermark, name, datetime) from video stream
2. `set_ai_config()` / `set_ai_alarm()` — disables AI detection and tracking to reduce CPU load
3. `set_net_port()` — configures HTTP/HTTPS/ONVIF/RTSP ports
4. `set_local_link()` — assigns static IP to the camera
5. `set_default_pos()` — saves PTZ home position (PTZ cameras only)

The script loads camera list from `cameras_config.json` and credentials from `.env`, then runs `setup()` on each camera in sequence. SSL verification is disabled for local network cameras.

### Raspberry Pi Provisioning (`setup_rpi.sh`)

Runs over SSH against a freshly flashed RPi. Sequence:

1. Copies SSH public keys from a local directory to the RPi
2. Runs `apt` updates and installs Python, git, OpenVPN, Docker
3. Configures OpenVPN (copies config + auth files, enables service)
4. Clones `pyro-engine` repo, copies `.env` and `credentials.json`
5. Adds cron jobs: GitHub updates polling and internet connectivity health check
6. Reboots RPi and waits for it to come back online
7. Starts pyro-engine via `make run`
8. Optionally configures WiFi and sets a static IP on `eth0` via NetworkManager

All paths, credentials, and network settings are read from `rpi_config.env`.

### Network Context

Cameras are accessed on a local PoE switch subnet. `aa.sh` is a utility that sets the host machine's `eth0` to a link-local static IP (`169.254.40.98/16`) using NetworkManager, allowing direct communication with cameras before they have a proper IP.
