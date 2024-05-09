# pyro-sys-setup
Set-up and manage Pyronear hardware fire detection systems.

## Setup

### 1. Install raspberry pi os
Please follow the steps in [`RPI_INSTALLATION`](RPI_INSTALLATION.md) to have a rapsberry pi properly running

### 2. Configuration requirements

To configure the raspberry pi, you need to provide the following configuration files:
*Files supposed to be available at the root of this repository, but you can change path in CONFIG.sh*

- `.env` file as requested in [pyro-engine](https://github.com/pyronear/pyro-engine/tree/main?tab=readme-ov-file#full-docker-orchestration).
- `credentials.json` as requested in [pyro-engine](https://github.com/pyronear/pyro-engine/tree/main?tab=readme-ov-file#full-docker-orchestration).
- Authorized public keys files in `SSH_PUB_KEYS` directory.
- An OpenVPN (.ovpn) configuration file.
- the [`config.sh`](config.sh) fullfilled with your information

### 3. Setting up the raspberry pi & run the services

Once configuration requirements are fullfilled, from the root of this repository run : 

```shell
bash setup_rpi.sh
```

## Contributing

Please refer to [`CONTRIBUTING`](CONTRIBUTING.md) if you wish to contribute to this project.

## Credits

This project is developed and maintained by the repo owner and volunteers from [Pyronear](https://pyronear.org/).

## License 
Distributed under the Apache 2 License. See [`LICENSE`](LICENSE) for more information.
