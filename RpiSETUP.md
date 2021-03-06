# RPI Setup

The following steps need to be done **BEFORE** using Ansible and this repository to install PyroNear system on raspberry pis.

## Flash SD Card with Raspbian

You can choose the OS which best fits your needs in this [list](https://www.raspberrypi.org/software/operating-systems/). I chose `Raspberry Pi OS Lite`.

Then you can flash your SD Card with the chosen OS. See [this article from raspberrypi.org](https://www.raspberrypi.org/documentation/installation/installing-images/) to help you out writing the image.

## Enable SSH

SSH needs to be enabled so that you can log onto your RPI. To do so, an empty ssh file must be created, on linux or mac os, you can run the following command:

```bash
touch /Volumes/boot/ssh
```

## Add WiFi network information

First, you need to create the following file:
```bash
touch /Volumes/boot/wpa_supplicant.conf
vim /Volumes/boot/wpa_supplicant.conf
```
Then add your network information:
```
country=FR
ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
update_config=1

network={
    ssid="NETWORK-NAME"
    psk="NETWORK-PASSWORD"
}
```

Once this is done, you can eject the SD Card and plug it into your RPI. You can then ssh on it, using your local machine (**careful the RPI needs to be on the same local network as your machine**):
```bash
ssh pi@raspberrypi.local
```
or
```bash
ssh pi@raspberrypi.ipaddress
```
The password is the default one `raspberry`. Then you can use our repository to deactivate password connexion and enable ssh connexion only with public/private keys.

It might be useful to setup in advance a static ip address for each RPI using your DHCP server.

--- 
The previous file is inspired by this [post](https://desertbot.io/blog/headless-raspberry-pi-4-ssh-wifi-setup).
