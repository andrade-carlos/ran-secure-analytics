#!/usr/bin/env bash
# RAN-Secure Analytics Platform - one-time preparation of a fresh Ubuntu 24.04 server.
# Run as the default user (e.g. "ubuntu") with sudo rights:
#     curl -fsSL <raw-url-of-this-file> | bash      or      bash deploy/setup-ubuntu.sh
set -euo pipefail

echo "==> Updating the system"
sudo apt-get update -y
sudo DEBIAN_FRONTEND=noninteractive apt-get upgrade -y
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
  ca-certificates curl git unattended-upgrades fail2ban

echo "==> Enabling automatic security updates"
sudo dpkg-reconfigure -f noninteractive unattended-upgrades

echo "==> Enabling fail2ban (SSH brute-force protection)"
sudo systemctl enable --now fail2ban

echo "==> Installing Docker Engine + Compose plugin (official Docker repository)"
if ! command -v docker >/dev/null 2>&1; then
  sudo install -m 0755 -d /etc/apt/keyrings
  sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  sudo chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
  sudo apt-get update -y
  sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
sudo usermod -aG docker "$USER"

echo "==> Limiting Docker log size"
sudo mkdir -p /etc/docker
echo '{ "log-driver": "json-file", "log-opts": { "max-size": "20m", "max-file": "5" } }' \
  | sudo tee /etc/docker/daemon.json >/dev/null
sudo systemctl restart docker

echo "==> Creating a 2 GB swap file (safety margin for the JVM)"
if ! swapon --show | grep -q /swapfile; then
  sudo fallocate -l 2G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

echo
echo "Done. Log out and back in (so the docker group applies), then:"
echo "  git clone <your-repo-url> ran-secure-analytics && cd ran-secure-analytics"
echo "  cp .env.example .env && nano .env"
echo "  docker compose -f docker-compose.yml -f deploy/docker-compose.cloud.yml up -d --build"
echo "  ./scripts/provision.sh"
