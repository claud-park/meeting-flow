#!/bin/bash
# Meeting Flow 진단 실행 래퍼
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYBIN="$SCRIPT_DIR/.venv/bin/python3"
[[ -x "$PYBIN" ]] || PYBIN="python3"
exec "$PYBIN" "$SCRIPT_DIR/scripts/doctor.py"
