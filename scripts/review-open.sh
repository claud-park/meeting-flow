#!/bin/bash
# 타임블록 검토 팝업을 연다. 알림 클릭과 Raycast/Quick Action 트리거가 공용으로 사용.
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYBIN="$SCRIPT_DIR/../.venv/bin/python3"
[[ -x "$PYBIN" ]] || PYBIN="python3"
if [[ ! -f "$SCRIPT_DIR/meetingflow/review_server.py" ]]; then
  echo "review_server.py가 아직 없습니다 (Task 9에서 추가)."
  exit 1
fi
exec "$PYBIN" "$SCRIPT_DIR/review-open.py"
