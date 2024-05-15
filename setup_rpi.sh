#!/bin/bash

# === Load Config ===
# Source variables from the variables file
source config.sh

# === Adding some authorized public keys ===
echo "=== Adding some authorized public keys ==="
for pubkey_file in $SSH_KEYS_DIR/*.pub; do
    echo $pubkey_file
    ssh-copy-id -f -i $pubkey_file $PI_USERNAME@$PI_HOST

    if [ $? -eq 0 ]; then
        echo "Public key $pubkey_file successfully added."
    else
        echo "Error adding Public key $pubkey_file."
    fi
done

# === Running main apt install commands ===
echo "=== Running main apt install commands ==="
commands=(
    "sudo apt-get update && sudo apt-get --allow-releaseinfo-change update"
    "sudo apt-get install -y python3-dev python3-pip git openvpn"
    "curl -sSL https://get.docker.com | sh && sudo usermod -aG docker pi"
)

for cmd in "${commands[@]}"; do
    ssh $PI_USERNAME@$PI_HOST "$cmd"
    if [ $? -eq 0 ]; then
        echo "Command \"$cmd\" executed successfully."
    else
        echo "Error while executing command \"$cmd\"."
    fi
done

# === VPN setup steps ===
echo "=== VPN setup steps ==="
scp $OPENVPN_CONFIG_FILE_PATH $PI_USERNAME@$PI_HOST:/home/pi/client.conf

if [ $? -eq 0 ]; then
    echo "VPN Configuration file sent successfully."
else
    echo "Error sending VPN configuration file"
fi

commands=(
    "sudo mv /home/pi/client.conf /etc/openvpn/client.conf"
    "sudo echo askpass /etc/openvpn/auth.txt >> /etc/openvpn/client.conf"
    "sudo touch /etc/openvpn/auth.txt"
    "echo "$OPEN_VPN_PASSWORD" | sudo tee -a /etc/openvpn/auth.txt >/dev/null"

)

for cmd in "${commands[@]}"; do
    ssh $PI_USERNAME@$PI_HOST "$cmd"
    if [ $? -eq 0 ]; then
        echo "Command \"$cmd\" executed successfully."
    else
        echo "Error while executing command \"$cmd\"."
    fi
done

# === PYRO ENGINE setup steps ===
echo "=== PYRO ENGINE setup steps ==="

# clone pyro-engine main branch
ssh $PI_USERNAME@$PI_HOST sudo git clone --branch main https://github.com/pyronear/pyro-engine.git

# Transfer env file & move it to pyro-engine folder
scp $PYROENGINE_ENV_FILE_PATH $PI_USERNAME@$PI_HOST:.env
ssh  $PI_USERNAME@$PI_HOST sudo mv /home/pi/.env /home/pi/pyro-engine/.env

# Transfer credentials file & move it to pyro-engine folder
scp $PYROENGINE_CREDENTIALS_LOCAL_PATH $PI_USERNAME@$PI_HOST:credentials.json

commands=(
    "sudo mkdir -p /home/pi/pyro-engine/data/"
    "sudo mv /home/pi/credentials.json /home/pi/pyro-engine/data/credentials.json"
)
for cmd in "${commands[@]}"; do
    ssh $PI_USERNAME@$PI_HOST "$cmd"
    if [ $? -eq 0 ]; then
        echo "Command \"$cmd\" executed successfully."
    else
        echo "Error while executing command \"$cmd\"."
    fi
done
# === CRONTAB setup ===
echo "=== CRONTAB setup ==="

NEW_CRON_TAB=$(cat << EOF
# Update from github
0 * * * * bash /home/pi/pyro-engine/scripts/update_script.sh
# Check internet connection
*/10 * * * * bash /home/pi/pyro-engine/scripts/check_internet_connection.sh
EOF
)

echo "$NEW_CRON_TAB" | ssh $PI_USERNAME@$PI_HOST "crontab -"

# === reboot ===
echo "=== reboot ==="

ssh  $PI_USERNAME@$PI_HOST sudo reboot

echo "Waiting for the Raspberry Pi to be restarted"
sleep 10
while ! ping -c 1 $PI_HOST &> /dev/null; do
    sleep 1
done
echo "The raspberry Pi is now available "

# === Start pyro-engine services ===
echo "=== Start pyro-engine services ==="
ssh  $PI_USERNAME@$PI_HOST "cd /home/pi/pyro-engine/ && make run"
