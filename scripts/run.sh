#!/usr/bin/env bash
set -euo pipefail

if [ -x "./venv/bin/python" ]; then
  ./venv/bin/python bot.py
else
  python3 bot.py
fi
