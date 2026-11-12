#!/bin/sh
set -eu
cd "$(dirname "$0")"
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
export HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false
exec .venv/bin/python -m alfa_reco serve --relevance --no-llm --open-browser --start-page /lab --port 0
