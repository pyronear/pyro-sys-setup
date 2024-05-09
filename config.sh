# VARIABLES.sh

PI_USERNAME="pi"
PI_HOST="THE_RPI_IP_ADDRESS"

## SSH KEYS
# Retrieve the absolute path of the directory containing the script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
# Path to directory containing SSH public keys
SSH_KEYS_DIR="$SCRIPT_DIR/SSH_PUB_KEYS"

## VPN config info
OPENVPN_CONFIG_FILE_PATH="$SCRIPT_DIR/THE_RPI_VPN_CONFIG_FILE.ovpn"
OPEN_VPN_PASSWORD="THE_RPI_OPEN_VPN_PASSWORD"

## pyro-engine config file
PYROENGINE_ENV_FILE_PATH="$SCRIPT_DIR/.env"
PYROENGINE_CREDENTIALS_LOCAL_PATH="$SCRIPT_DIR/credentials.json"