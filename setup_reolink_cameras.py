import argparse
import json
import logging
import os
from typing import List, Optional

import requests
import urllib3
from dotenv import load_dotenv

__all__ = ["ReolinkCamera"]

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Configure logging
logging.basicConfig(level=logging.INFO)


class ReolinkCamera:
    """
    A controller class for interacting with Reolink cameras.
    from https://support.reolink.com/hc/en-us/articles/900000625763-Introduction-to-CGI-API/

    Attributes:
        ip_address (str): IP address of the Reolink camera.
        username (str): Username for accessing the camera.
        password (str): Password for accessing the camera.
        cam_type (str): Type of the camera, e.g., 'static' or 'ptz' (pan-tilt-zoom).
        cam_poses (Optional[List[int]]): List of preset positions for PTZ cameras.
        protocol (str): Protocol used for communication, defaults to 'https'.
        verbose (bool): Flag to enable detailed logging.

    Methods:
        capture(pos_id): Captures an image from the camera. Moves to position `pos_id` if provided.
        move_camera(operation, speed, id): Moves the camera based on the operation type and speed.
        move_in_seconds(s, operation, speed): Moves the camera for a specific duration and then stops.
        get_ptz_preset(): Retrieves preset positions for a PTZ camera.
        set_ptz_preset(id): Sets a PTZ preset position using an ID.
    """

    def __init__(
        self,
        ip_address: str,
        username: str,
        password: str,
        cam_type: str,
        locallink: str,
        cam_poses: Optional[List[int]] = None,
        protocol: str = "https",
        port: str = 443,
        verbose: str = False,
    ):
        self.ip_address = ip_address
        self.username = username
        self.password = password
        self.cam_type = cam_type
        self.locallink = locallink
        self.cam_poses = cam_poses if cam_poses is not None else []
        self.protocol = protocol
        self.port = port
        self.verbose = verbose

    def _build_url(self, command: str) -> str:
        """Constructs a URL for API commands to the camera."""
        return f"{self.protocol}://{self.ip_address}:{self.port}/api.cgi?cmd={command}&user={self.username}&password={self.password}"

    def _handle_response(self, response, success_message: str):
        """Handles HTTP/HTTPS responses, logging success or errors based on response data."""

        if response.status_code == 200:
            response_data = response.json()
            if response_data[0]["code"] == 0:
                if self.verbose:
                    logging.info(success_message)
            else:
                logging.error(f"Error: {response_data}")
            return response_data
        else:
            logging.error("Failed operation: %d, %s",
                          response.status_code, response.text)

    def get_osd(self):
        """
        Get OSD paramater for Reolink Camera
        """
        command = "GetOSD"

        url = self._build_url(command)

        response = requests.post(url, verify=False)

        logging.info(f"{response.json()}")

        self._handle_response(response, "GetOSD successfully")

    def set_osd(self):
        """
        Sets default Pyronear OSD paramater for Reolink Camera
        It removes watermark, camera name and datetime from images
        """
        command = "SetOsd"

        url = self._build_url(command)

        data = [{"cmd": "SetOsd", "param": {"Osd": {
            "channel": 0, "osdChannel": {
                "enable": 0
            }, "osdTime": {
                "enable": 0}, "watermark": 0
        }}}]

        response = requests.post(url, json=data, verify=False)

        self._handle_response(
            response=response, success_message="OSD parameters are now set")

    def get_ai_alarm(self):
        """
        TODO
        """
        command = "GetAiAlarm"

        url = self._build_url(command)

        data = [{
            "cmd": "GetAiAlarm", "action": 0,
            "param": {
                "channel": 0,
                "ai_type": "vehicle"}
        }]

        response = requests.post(url, json=data, verify=False)

        self._handle_response(response, "Get ai alarm info sucessfully")

    def set_ai_alarm(self):
        """
        Sets default Pyronear ai alarm config by deactivating ai detection
        """
        command = "SetAiAlarm"

        url = self._build_url(command)

        for ai_type in ["vehicle", "people"]:
            data = [{
                "cmd": command,
                "param": {
                    "channel": 0,
                    'AiAlarm': {'ai_type': ai_type, 'channel': 0, 'max_target_height': 0.0, 'max_target_width': 0.0, 'min_target_height': 0.0, 'min_target_width': 0.0, 'scope': {'area': '000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000', 'cols': 120, 'rows': 67}, 'sensitivity': 0, 'stay_time': 0}

                }
            }]

            response = requests.post(url, json=data, verify=False)

            self._handle_response(response,
                                  f"deactivate ai type {ai_type} successfully")

    def get_ai_config(self):
        """
        Get ai configuration
        """
        command = "GetAiCfg"

        url = self._build_url(command)

        data = [{
                "cmd": "GetAiCfg", "action": 0, "param": {
                    "channel": 0}
                }]

        response = requests.post(url, json=data, verify=False)

        logging.info(f"{response.json()}")

    def set_ai_config(self):
        """
        Sets default Pyronear ai config paramater for Reolink Camera
        It deactivates any type of detection and tracking
        """
        command = "SetAiCfg"

        url = self._build_url(command)

        data = [{
                "cmd": "SetAiCfg",
                "action": 1,
                "param": {
                    "aiTrack": 0,
                    "trackType": {
                        "dog_cat": 0,
                        "face": 0,
                        "people": 0,
                        "vehicle": 0},
                    "AiDetectType": {
                        "people": 0,
                        "vehicle": 0,
                        "dog_cat": 0,
                        "face": 0},

                    "channel": 0}
                }]

        response = requests.post(url, json=data, verify=False)

        self._handle_response(response, "Ai Config is now set")

    def get_ability(self):
        """
        Gets Reolink Camera ability
        """
        command = "GetAbility"

        url = self._build_url(command)

        data = [
            {
                "cmd": "GetAbility",
                "param": {"User": {
                    "userName": "admin"}
                }
            }]

        response = requests.post(url, json=data, verify=False)

        logging.info(f"{response.json()}")

    def get_net_port(self):
        """
        Gets network port configuration
        """
        command = "GetNetPort"

        url = self._build_url(command)

        data = [{
                "cmd": command,
                "action": 1
                }]

        response = requests.post(url, json=data, verify=False)

    def set_net_port(self):
        """
        Sets network port to default Pyronear configuration
        """
        command = "SetNetPort"

        url = self._build_url(command)

        data = [{
            "cmd": command,
                "param": {
                    "NetPort": {
                        "httpEnable": 1,
                        "httpPort": 80,
                        "httpsEnable": 1,
                        "httpsPort": 443,
                        "onvifEnable": 1,
                        "onvifPort": 8000,
                        "rtspEnable": 1,
                        "rtspPort": 554
                    }}
                }]

        response = requests.post(url, json=data, verify=False)

        self._handle_response(response, "Network ports are now set")

    def get_locallink(self):
        """
        Gets local link configuration.
        """
        command = "GetLocalLink"

        url = self._build_url(command)

        data = [{
                "cmd": command,
                "action": 1
                }]

        response = requests.post(url, json=data, verify=False)

        print(response.status_code)
        print(response.json())

        self._handle_response(response, "")

    def set_local_link(self):
        """
        Sets local to the given configuration
        """
        command = "SetLocalLink"

        url = self._build_url(command)

        data = [{
            "cmd": command,
                "action": 0,
                "param": {"LocalLink": self.locallink
                          }}]

        response = requests.post(url, json=data, verify=False)

        self._handle_response(response, "Local link is now set")

    def setup(self):
        """
        Sets up Reolink camera to target speficic configuration
        """
        logging.info(f"{self.ip_address}")
        self.set_osd()
        self.set_ai_config()
        self.set_ai_alarm()
        self.set_net_port()
        self.set_local_link()


def main(args):

    # .env loading
    logging.info("Loading env file")

    load_dotenv(args.env_file_path)

    CAM_USER = os.environ.get("CAM_USER")
    CAM_PWD = os.environ.get("CAM_PWD")
    assert isinstance(CAM_USER, str) and isinstance(CAM_PWD, str)

    # Loading camera setup
    logging.info("Loading camera config file")

    with open(args.cam_config, "rb") as json_file:
        cameras_config = json.load(json_file)

    logging.info("Instancianting cameras classes")

    cams = [ReolinkCamera(_ip, CAM_USER, CAM_PWD,
                          cam_type=cameras_config[_ip]["type"],
                          locallink=cameras_config[_ip]["LocalLink"], verbose=True) for _ip in cameras_config]

    logging.info("Setting up cameras")

    [cam.setup() for cam in cams]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Reolink camera setup script", formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("--cam_config", type=str,
                        default="cameras_config.json", help="Camera config file")
    parser.add_argument("--env_file_path", type=str,
                        default=".env", help="Path to env file containing cameras credentials")
    args = parser.parse_args()

    main(args)
