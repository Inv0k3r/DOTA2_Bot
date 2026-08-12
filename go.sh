#!/usr/bin/env bash
set -euo pipefail

python3 -m pip install -r requirements.txt
exec python3 run.py
