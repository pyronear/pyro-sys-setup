#!/usr/bin/env python3
import os
from dotenv import load_dotenv

from picamera import PiCamera
import subprocess
from time import sleep

load_dotenv()

MAIN_RPI_USER = os.environ.get("MAIN_RPI_USER")
MAIN_RPI_IP = os.environ.get("MAIN_RPI_IP")


class TakePicture:
    """Takes a picture with PiCamera and send it over ssh to the master rpi."""

    def __init__(self, path_to_image_folder, main_rpi_user, main_rpi_ip):
        self.path_to_image_folder = path_to_image_folder
        self.main_rpi_user = main_rpi_user
        self.main_rpi_ip = main_rpi_ip
        self.camera = PiCamera()
        self.camera.rotation = 180

    def launch_camera(self):
        self.camera.start_preview()

    def stop_camera(self):
        self.camera.stop_preview()

    def send_over_ssh(self, path_to_image_file):
        subprocess.call(
            [
                "rsync",
                "-rhavz",
                "-e",
                "ssh",
                path_to_image_file,
                f"{self.main_rpi_user}@{self.main_rpi_ip}:{path_to_image_file}",
            ]
        )

    def get_picture(self):
        for i in range(5):
            sleep(5)
            path_to_image_file = "/home/pi/images/image%s.jpg" % i
            if os.path.exists(path_to_image_file):
                os.remove(path_to_image_file)
            self.camera.capture(path_to_image_file)
            self.send_over_ssh(path_to_image_file)


if __name__ == "__main__":
    path_to_image_folder = "/home/pi/images"
    picture_taker = TakePicture(path_to_image_folder, MAIN_RPI_USER, MAIN_RPI_IP)
    picture_taker.launch_camera()
    picture_taker.get_picture()
    picture_taker.stop_camera()
