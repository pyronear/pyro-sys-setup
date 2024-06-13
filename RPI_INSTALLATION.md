# Installing raspberry pi image

## Flash SD Card with Raspbian 

You can install Raspberry Pi OS using [Raspberry Pi Imager](https://www.raspberrypi.com/software/). See [this article from raspberrypi.org](https://www.raspberrypi.org/documentation/installation/installing-images/) to help you out writing the image.

You need to :
- choose `Raspberry Pi OS Lite 64-bit`.
- add a wifi network (Optionnal)
- add a robust password
- set a device hostname
- enable ssh

Once this is done, you can eject the SD Card, plug it into your RPI and power the RPI. You can then ssh on it, using your local machine (**careful the RPI needs to be on the same local network as your machine, for exemple by connecting you RPI using ethernet cable to your internet box**)

Also, if you would configure muliple sd card, for each sd flashed, the RPI has to be unplugged and plugged to properly boot for the first time ! 

```bash
ssh pi@THE_CHOSEN_HOSTNAME.local
```

The password is the default one `raspberry` but if you but you should have another if you have followed this tutorial correctly :)