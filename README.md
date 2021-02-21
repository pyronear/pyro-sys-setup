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
  * [directory layout](#directory-layout)
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
```


## Usage
By convention, we will use YAML format for inventory files

Following ansisble [guidelines](https://docs.ansible.com/ansible/latest/user_guide/sample_setup.html), you can find below the structure of the project

## directory layout

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
├── rpi.requirements.txt        # requirements which need to be install on the RPI (only)
├── requirements.yml
├── roles                       # directory to gather roles
│   └── common
│       └── main_exemple.yml
├── scripts                     
│   └── some_script.py
├── ansible.cfg                 # user config file, overrides the default config if present
└── master.yml                    # main playbook
```

## Example to playbooks to run:

#### First:
- need sshpass on lacal machine:
````bash
brew install hudochenkov/sshpass/sshpass
````

On first try:
````bash
ansible-playbook add_ssh_key_playbook.yml -i host_vars/hosts_with_password.yml
````
with role to set up ssh connexion with keys

Then, to deactivate password authentification:
````bash
ansible-playbook deactivate_password_playbook.yml
````

To run enable camera usage on RPI:
```bash
ansible-playbook enable_camera_playbook.yml
```

To run the core playbook:
```bash
ansible-playbook common_playbook.yml
```
**CAREFUL** `tags=always` are always run ! 

To stop a service:
```bash
ansible-playbook stop_service_playbook.yml --extra-vars service=docker
```

## Contributing
Please refer to `CONTRIBUTING` if you wish to contribute to this project.

## License 
Distributed under the Apache 2.0 License. See LICENSE for more information.





