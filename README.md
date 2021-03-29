# pyro-sys-setup
Set-up and manage our hardware fire detection systems.

Actually, this is a proposed skeleton of this project and guidelines for clean and tidy usage. These are subject to future developments.

## Table of contents

- [pyro-sys-setup](#pyro-sys-setup)
  * [Table of contents](#table-of-contents)
  * [Getting started](#getting-started)
    + [Prerequisites](#prerequisites)
    + [Installation](#installation)
  * [Usage](#usage)
  * [Directory layout](#directory-layout)
  * [First steps](#first-steps-before-running-any-playbooks)
  * [Use master.yml playbook](#use-masteryml-playbook)
  * [Example of playbooks to run independently](#example-of-playbooks-to-run-independently)
  * [Contributing](#contributing)
  * [License](#license)

## Getting started

### Prerequisites

- Python 3.6 (or more recent)
- [pip](https://pip.pypa.io/en/stable/)

### Installation

You can clone and install the project dependencies as follows:

```bash
git clone https://github.com/pyronear/pyro-sys-setup.git
pip install -r pyro-sys-setup/requirements.txt
ansible-galaxy install requirements.yml
```

## Usage
By convention, we will use YAML format for inventory files.

Following Ansible [guidelines](https://docs.ansible.com/ansible/latest/user_guide/sample_setup.html), you can find below the structure of the project

## Directory layout

```bash
.
├── CONTRIBUTING.md
├── LICENSE
├── README.md
├── group_vars		            # directory to assign variables to particular groups
│   └── group_example.yml       
├── host_vars                   # directory to assign variables to particular systems
│   └── hosts.yml         # inventory file 
├── files                       # directory to gather files and folders needed for system roles/tasks
├── requirements.txt
├── camera.rpi.requirements.txt        # requirements which need to be install on the camera RPI (only)
├── main.rpi.requirements.txt        # requirements which need to be install on the main RPI (only)
├── requirements.yml
├── roles                       # directory to gather roles
│   └── common
│       └── main_exemple.yml
├── scripts_common                     
│   └── some_script.py
├── scripts_camera_rpi                     
│   └── some_script.py
├── scripts_main_rpi                  
│   └── some_script.py
├── ansible.cfg                 # user config file, overrides the default config if present
└── master.yml                    # main playbook
```

## First steps, before running any playbooks

You need sshpass on your local machine:
````bash
brew install hudochenkov/sshpass/sshpass
````

**CAREFUL** You also need to modify `host_vars/hosts.yml` to put your own rpi `ansible_host`, `ansible_user`, `ansible_password` and `ansible_python_interpreter`.

Finally, refer to RpiSETUP.md for simple instructions upon flashing your SD Card.

## Use master.yml playbook:
This is the master playbook, used to setup our fleet of RPI. To run it:

```bash
ansible-playbook master.yml
```

## Example of playbooks to run independently:

If rather than using directly the master playbook you'd like to take a look at each playbook independently, you can follow these steps:

On first try:
````bash
ansible-playbook playbooks/add_ssh_key_playbook.yml
````
with role to set up ssh connexion with keys

Then, to deactivate password authentification:
````bash
ansible-playbook playbooks/deactivate_password_playbook.yml
````

To run enable camera usage on RPI:
```bash
ansible-playbook playbooks/enable_camera_playbook.yml
```

To run the core playbook:
```bash
ansible-playbook playbooks/common_playbook.yml
```
**CAREFUL** `tags=always` are always run ! 

To stop a service:
```bash
ansible-playbook playbooks/stop_service_playbook.yml --extra-vars service=docker
```
## Environment variables

In the `.env.dist` file, you'll find a template of the `.env` which you need to add to your clone version of this repository. 
It contains the `MAIN_RPI_USER` which is the user used to connect to the main RPI and its ip address `MAIN_RPI_IP`. This is currently 
used to send image files over `rsync` from the RPI with camera to the main one for storage.

## Contributing
Please refer to `CONTRIBUTING` if you wish to contribute to this project.

## License 
Distributed under the Apache 2.0 License. See LICENSE for more information.





