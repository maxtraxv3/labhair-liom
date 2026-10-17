#!/usr/bin/env bash
# Launch relay + two demo clients in a single script (needs two extra terminals
# or use the printed commands yourself).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
PY="${ROOT}/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  echo "Create the venv first: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi

echo "Start relay:"
echo "  $PY $ROOT/server/relay.py --port 9473"
echo
echo "Alice:"
echo "  $PY $ROOT/client/main.py --user alice --display Alice --room demo --voice --video"
echo
echo "Bob:"
echo "  $PY $ROOT/client/main.py --user bob --display Bob --room demo --voice --video"
