#!/usr/bin/env bash
set -euo pipefail

profile="dev"
if [[ "${1:-}" == "dev" || "${1:-}" == "prod" ]]; then
  profile="$1"
  shift
fi

if [ -x "./venv/bin/python" ]; then
  py="./venv/bin/python"
else
  py="python3"
fi

"$py" scripts/run_web_service.py --profile "$profile" "$@"
