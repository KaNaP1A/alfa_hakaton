#!/bin/sh
set -eu
cd "$(dirname "$0")"
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
.venv/bin/python scripts/run_relevance_pipeline.py --generate --install
printf '\nОбучение завершено. Нажмите Enter, чтобы закрыть окно.\n'
read -r reply
