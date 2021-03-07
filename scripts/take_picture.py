#!/usr/bin/env python3
import os
from dotenv import load_dotenv

from picamera import PiCamera
import subprocess
from time import sleep

load_dotenv()

MAIN_RPI_USER = os.environ.get("MAIN_RPI_USER")
MAIN_RPI_IP = os.environ.get("MAIN_RPI_IP")

camera = PiCamera()
camera.rotation = 180
camera.start_preview()
for i in range(5):
    sleep(5)
    path = "/home/pi/images/image%s.jpg" % i
    if os.path.exists(path):
        os.remove(path)
    camera.capture(path)
    subprocess.call(
        ["rsync", "-rhavz", "-e", "ssh", path, f"{MAIN_RPI_USER}@{MAIN_RPI_IP}:{path}"]
    )
camera.stop_preview()
