# Ansible project on the main RPI

This directory contains all configuration files and playbooks to be run on the main RPI.

The layout is the following:
```bash
.
├── README.md    
├── hosts.yml                   # inventory file with the IP addresses of the rpi on camera once they are on site
├── requirements.txt
├── templates                   # directory containing templates
├── playbooks                   # directory to gather playbooks to be run by the main rpi
├── ansible.cfg                 # user config file, overrides the default config if present
├── vars                        # directory which will contain Ansible environment variables on the main rpi
└── requirements.yml
```

The `templates/python.env` file must contain:
- `WEBSERVER_IP`: the dns of the main rpi once it is installed on site (it should correspond to the `hostname` of the main rpi)
- `WEBSERVER_PORT`: the port exposed on the main rpi for the local webserver

### Playbooks:

-`configure_rpi_camera.yml` is used to setup the files and environnement needed on the rpi with camera to work.
- `update_rpi_camera.yml` is used to update the rpi with camera after the installation is done.
- `update_rpi_main.yml` is used to update the main rpi after the installation is done.
