#!/usr/bin/env bash
set -euo pipefail

python3 -m venv venv
./venv/bin/python -m pip install --upgrade pip
./venv/bin/python -m pip install -r requirements.txt

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi

echo "Bootstrap completed."
echo "Bot run: ./scripts/run.sh"
echo "Web service run (dev): python scripts/run_web_service.py --profile dev"
