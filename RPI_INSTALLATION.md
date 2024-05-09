# RPI Setup

## Flash SD Card with Raspbian 

You can install Raspberry Pi OS using [Raspberry Pi Imager](https://www.raspberrypi.com/software/). See [this article from raspberrypi.org](https://www.raspberrypi.org/documentation/installation/installing-images/) to help you out writing the image.

You need to :
- choose `Raspberry Pi OS Lite 64-bit`.
- add a wifi network (Optionnal)
- add a robust password
- set a device hostname
- enable ssh

## Setup with command line (Optionnal)
### Enable SSH

SSH needs to be enabled so that you can log onto your RPI. To do so, an empty ssh file must be created, on linux or mac os, you can run the following command:

```bash
touch /Volumes/boot/ssh
```

### Add WiFi network information

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
ssh pi@THE_CHOSEN_HOSTNAME.local
```

The password is the default one `raspberry` but if you but you should have another if you have followed this tutorial correctly :)