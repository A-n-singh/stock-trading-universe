#!/usr/bin/env bash
# One-time server setup on a fresh Oracle Cloud Ubuntu VM. Run from the project folder:
#   bash deploy/setup-oracle.sh
set -euo pipefail

echo "== Installing Docker and git =="
sudo apt-get update -y
sudo apt-get install -y docker.io docker-compose-v2 git
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"

echo "== Opening web ports 80 and 443 in the server's own firewall (Oracle images block them) =="
for port in 80 443; do
  sudo iptables -C INPUT -p tcp --dport "$port" -m state --state NEW -j ACCEPT 2>/dev/null \
    || sudo iptables -I INPUT 5 -p tcp --dport "$port" -m state --state NEW -j ACCEPT
done
sudo apt-get install -y iptables-persistent
sudo netfilter-persistent save

if [ ! -f deploy/.env ]; then
  cp deploy/.env.example deploy/.env
  chmod 600 deploy/.env
  echo "== Created deploy/.env. Fill in your password and keys:  nano deploy/.env =="
fi

echo
echo "Done. Log out and back in once (so Docker works without sudo), then:"
echo "  cd $(pwd)/deploy && docker compose up -d --build"
