#!/usr/bin/env bash
# Get the newest code from GitHub and restart with it. Trading history and memory are kept.
#   bash deploy/update.sh            (add --https if you run the public HTTPS setup)
set -euo pipefail
cd "$(dirname "$0")/.."
git pull --ff-only
cd deploy
if [ "${1:-}" = "--https" ]; then
  docker compose --profile https up -d --build
else
  docker compose up -d --build
fi
docker image prune -f >/dev/null
docker compose ps
