#!/bin/bash
# 타임블록 검토 팝업을 연다. 알림 클릭(terminal-notifier -execute)과
# Raycast/Quick Action 트리거가 공용으로 사용한다.
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYBIN="$SCRIPT_DIR/../.venv/bin/python3"
[[ -x "$PYBIN" ]] || PYBIN="python3"
exec "$PYBIN" "$SCRIPT_DIR/review-open.py"
