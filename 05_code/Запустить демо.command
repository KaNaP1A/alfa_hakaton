#!/bin/sh
set -eu
cd "$(dirname "$0")"
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
if [ -x "$PWD/.venv/bin/python" ]; then
  exec "$PWD/.venv/bin/python" -m alfa_reco serve --hybrid --open-browser --port 0
fi
exec python3 -m alfa_reco serve --hybrid --open-browser --port 0
