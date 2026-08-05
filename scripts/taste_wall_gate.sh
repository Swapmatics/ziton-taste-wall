#!/usr/bin/env bash
# Taste-wall technical contract gate
set -euo pipefail
cd "$(dirname "$0")/.."
python3 scripts/validate_taste_wall.py
