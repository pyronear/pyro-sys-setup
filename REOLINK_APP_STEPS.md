
- Download [Reolink app](https://reolink.com/software-and-manual/)
- Start you reolink client, you are supposed to see your cameras (that usually take a few minutes to connect after plugging them in)
- Then for each camera : 
    - Click on “Uninitialized device” 
    - You will be asked to define a user & pwd : report information you have chosen in .env previously
    - To find the ip adresse of the camera
        - Access settings clicking the wheel near cameras name
        - Click then on "Network", then "network information"
        - You will be able to read the ip address of the camera. Report it in `cameras_config.json`
- You are done with the Reolink app

- Complete `cameras_config.json`
For each cameras, complete values associed to its ip address. 
```
{
        "type": "static", --> either "ptz" if it is a ptz camera, or "static"
        "LocalLink": {
            "type": "Static",   --> let this value as default
            "static": {
                "ip": "169.254.40.1",   --> advice to start with 169.254.40. and complete with 1 to N (N the number of cameras)
                "mask": "255.255.0.0",   --> let this value as default
                "gateway": "169.254.1.1" --> let this value as default
            }
```
