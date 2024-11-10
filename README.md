# pyro-sys-setup
pyro-sys-setup is used to configure Pyronear hardware fire detection systems. In particular, you can configure IP cameras (currently from Reolink) and a raspberry pi, by following the tutorial below.

## Cameras Setup
### 1. Connecting and powering up cameras on local network
- You will need factory-set Reolink cameras (either cameras are new/refurbished, so you don't need to do anything, or follow [this tutorial](https://support.reolink.com/hc/en-us/articles/360003516613-How-to-Reset-Bullet-or-Dome-Cameras/) to reset them to factory settings).
- These cameras are powered by POE. Connect the cameras via Ethernet to a POE switch connected to your local network (or directly to your computer).

### 2. Configuration requirements
At this step, you will use the reolink application to define a user and password and retrieve the IP address for each camera, and you will report these details in the required configuration files described below : 

*By default, files supposed to be available at the root of this repository, but will be able to prodvide a specific path to file at step 4 of this tutorial*

- `.env` file as requested in [pyro-engine](https://github.com/pyronear/pyro-engine/tree/main?tab=readme-ov-file#full-docker-orchestration).
   
- `cameras_config.json` file. You can find an example at the root of this repository. The purpose of this json is to list all the IP addresses of cameras to be configured, and for each of them certain characteristics to be defined. 


**2.1** Choose a username & password, for sake of simplicity, it will be the same user and password used for each cameras, and 
report these as CAM_USER and CAM_PWD in .env file

**2.2** Please follow the steps in [`REOLINK_APP_STEPS`](REOLINK_APP_STEPS.md) to set user, password ang get ip adresses with reolinkApp

### 3. Setting up cameras
If you have followed previous steps correctly, you have an .env file and a cameras_config.json file fullfilled. 

**3.1** install required librairies in running the following : 

```
pip install -r requirements.txt
```

**3.2** Now, from the root of this repository run:
 
*By default, the script is looking for .env and cameras_config in this repository but you can specify a path for each config file, use `python setup_reolink_cameras.py -h` for help*

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
