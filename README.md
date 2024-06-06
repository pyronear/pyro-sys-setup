# pyro-sys-setup
Set-up and manage Pyronear hardware fire detection systems.

## Setup

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
PI_USERNAME="pi" 
PI_HOST="THE ACTUAL IP ADRESS OF YOUR RPI" 

## SSH KEYS
# Path to directory containing SSH public keys
SSH_KEYS_DIR_NAME="SSH_PUB_KEYS"

## VPN config info
OPENVPN_CONFIG_FILE_NAME="NAME_OF_YOUR_OPEN_VPN_FILE.ovpn"
OPEN_VPN_PASSWORD="THE_RPI_OPEN_VPN_PASSWORD"

## pyro-engine config files
PYROENGINE_ENV_FILE_NAME=".env"
PYROENGINE_CREDENTIALS_FILE_NAME="credentials.json"

## Network
# Wifi 
WIFI_SSID="NAME_THE_WIFI_ACESS_POINT"
WIFI_PASSWORD="THE_PASSWORD_OF_YOUR_WIFI"
# Static ip
STATIC_ETHERNET_IP="169.254.40.99"
DEFAULT_GATEWAY="192.168.1.254"
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
