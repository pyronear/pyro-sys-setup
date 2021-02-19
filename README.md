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
│   └── host_example.yml
├── hosts.yml                   # inventory file 
├── requirements.txt
├── roles                       # directory to gather roles
│   └── common
│       └── main_exemple.yml
├── scripts                     
│   └── some_script.py
└── site.yml                    # main playbook
```
## Contributing
Please refer to `CONTRIBUTING` if you wish to contribute to this project.

## License 
Distributed under the Apache 2.0 License. See LICENSE for more information.





