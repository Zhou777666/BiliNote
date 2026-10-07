#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python backend/build_backend.py "$@"
