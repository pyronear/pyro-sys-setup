#!/bin/bash

echo "📡 Setting up static IP on eth0 (169.254.40.98/16)"
echo "⚠️ If you're connected via Ethernet, you may temporarily lose the connection."

# Configuration
STATIC_ETHERNET_IP="169.254.40.98/16"
DEFAULT_DNS="8.8.8.8"

# Supprimer toute ancienne config nommée "static-eth0" si elle existe
nmcli connection delete static-eth0 2>/dev/null

# Créer une nouvelle connexion statique sur eth0
nmcli connection add type ethernet ifname eth0 con-name static-eth0 ipv4.addresses "$STATIC_ETHERNET_IP" ipv4.method manual

# Ajouter un DNS (optionnel mais recommandé)
nmcli connection modify static-eth0 ipv4.dns "$DEFAULT_DNS"

# Activer la connexion
nmcli connection up static-eth0
