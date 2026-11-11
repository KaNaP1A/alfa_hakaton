#!/bin/sh
set -eu
cd "$(dirname "$0")"
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m alfa_reco serve --hybrid --open-browser --port 8000
