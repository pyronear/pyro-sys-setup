# pyro-sys-setup
pyro-sys-setup is used to configure Pyronear hardware fire detection systems. In particular, you can configure IP cameras (currently from Reolink) and a raspberry pi, by following the tutorial below.

## Cameras Setup
### 1. Connecting and powering up cameras on local network
- You will need factory-set Reolink cameras (either cameras are new/refurbished, so you don't need to do anything, or follow [this tutorial](https://support.reolink.com/hc/en-us/articles/360003516613-How-to-Reset-Bullet-or-Dome-Cameras/) to reset them to factory settings).
- These cameras are powered by POE. Connect the cameras via Ethernet to a POE switch connected to your local network (or directly to your computer).

### 2. Automated provisioning (recommended)

`provision_reolink.py` replaces the manual Reolink-app steps entirely: **it discovers factory-fresh Reolink cameras on your LAN over the Baichuan protocol, sets the admin password and enables HTTP/HTTPS without the app, assigns each camera a static IP, then runs the standard setup script.**

**2.1** Fill in two files at the root of the repository:

- `.env` — set `CAM_USER` and `CAM_PWD` (the admin username/password to apply to every camera). Same file requested by [pyro-engine](https://github.com/pyronear/pyro-engine/tree/main?tab=readme-ov-file#full-docker-orchestration).
- `provision_config.json` — the intended fleet: the pool of target static IPs to hand out (one per camera), plus the `type` (`ptz`/`static`), `mask` and `gateway` applied to all. An example is provided at the root of the repository.

**2.2** From the root of the repository, run :

```bash
uv run provision_reolink.py --run-setup
```

That's it. The script auto-detects your subnet, provisions every fresh camera it finds, generates `cameras_config.json`, and configures each camera. It is **idempotent** — safe to re-run; already-initialized cameras are detected and skipped, and a camera already on a target IP keeps it.

*Useful flags: `--ip <ip ...>` to target specific cameras and skip discovery, `--subnet <cidr>` to scan a different network, omit `--run-setup` to generate `cameras_config.json` without configuring yet. Run `uv run provision_reolink.py -h` for the full list.*

> Always re-run `provision_reolink.py` (not `setup_reolink_cameras.py` on its own) when adding cameras: it re-discovers the current IPs and regenerates `cameras_config.json` accordingly.

### 3. Manual setup (alternative)

If you prefer to provision cameras by hand with the Reolink app:

**3.1** Choose a username & password (the same for every camera) and report them as `CAM_USER` and `CAM_PWD` in the `.env` file.

**3.2** Follow the steps in [`REOLINK_APP_STEPS`](REOLINK_APP_STEPS.md) to set the user/password and get the IP addresses with the Reolink app, then fill in `cameras_config.json` (list each camera's IP and its characteristics; an example is at the root of the repository).

**3.3** Install the required libraries:

```
pip install -r requirements.txt
```

**3.4** Then, from the root of the repository, run:

*By default, the script looks for `.env` and `cameras_config.json` in this repository, but you can specify a path for each; use `python setup_reolink_cameras.py -h` for help.*

``` bash
python setup_reolink_cameras.py
```

## Raspberry pi Setup

### 1. Install raspberry pi os
Please follow the steps in [`RPI_INSTALLATION`](RPI_INSTALLATION.md) to have a rapsberry pi properly running

### 2. Configuration requirements

To configure the raspberry pi, you need to provide the following configuration files:

*Files supposed to be available at the root of this repository, but you can change path in rpi_config.env, see below*

- `.env` file as requested in [pyro-engine](https://github.com/pyronear/pyro-engine/tree/main?tab=readme-ov-file#full-docker-orchestration).
- `credentials.json` as requested in [pyro-engine](https://github.com/pyronear/pyro-engine/tree/main?tab=readme-ov-file#full-docker-orchestration).
- Authorized public keys files in `SSH_PUB_KEYS` directory.
- An OpenVPN (.ovpn) configuration file.
- A env file named `rpi_config.env` fullfilled with your information

So your `rpi_config.env` file should look like something similar to:

```
PI_HOST="THE ACTUAL IP ADRESS OF YOUR RPI" 

## SSH KEYS
# Path to directory containing SSH public keys
SSH_KEYS_DIR_PATH="PATH_TO_DIRECTORY_CONTAINING_SSH_PUB_KEYS"

## VPN config info
OPENVPN_CONFIG_FILE_PATH="PATH_TO_YOUR_OPEN_VPN_FILE.ovpn"
OPEN_VPN_PASSWORD="THE_RPI_OPEN_VPN_PASSWORD"

## pyro-engine config files
PYROENGINE_ENV_FILE_PATH="PATH_TO_PYROENGINE_ENV_FILE_NAME.env"
PYROENGINE_CREDENTIALS_LOCAL_PATH="PATH_TO_credentials.json"

## Network
# Wifi OPTIONAL
# Configuring a wifi is optional here, you can let the following variables as an empty string if you do not want to setup a wifi access
WIFI_SSID=""   #NAME_THE_WIFI_ACESS_POINT
WIFI_PASSWORD=""

# Static ip
STATIC_ETHERNET_IP="169.254.40.99"
DEFAULT_DNS="8.8.8.8 8.8.4.4"
```

### 3. Setting up the raspberry pi & run the services

Once configuration requirements are fullfilled, from the root of this repository run : 

*you will be asked the password you define previously*

```shell
bash setup_rpi.sh
```

## Contributing

Please refer to [`CONTRIBUTING`](CONTRIBUTING.md) if you wish to contribute to this project.

## Credits

This project is developed and maintained by the repo owner and volunteers from [Pyronear](https://pyronear.org/).

## License 
Distributed under the Apache 2 License. See [`LICENSE`](LICENSE) for more information.
