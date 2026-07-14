#!/bin/bash

# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title 미팅 끝
# @raycast.mode silent
# @raycast.packageName Meeting Flow

# Optional parameters:
# @raycast.icon ✅
# @raycast.argument1 { "type": "text", "placeholder": "참석자 수/이름 (예: 4 또는 예림,철수)", "optional": true }

set -euo pipefail

MANUAL_ATTENDEES="${1:-}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../config.env"

STATE_FILE="$MEETINGS_DIR/.current_session.json"

if [[ ! -f "$STATE_FILE" ]]; then
  echo "진행 중인 녹음이 없습니다."
  exit 1
fi

PID=$(python3 -c "import json;print(json.load(open('$STATE_FILE'))['pid'])")
PREV_OUTPUT=$(python3 -c "import json;print(json.load(open('$STATE_FILE'))['prev_output'])")
MODE=$(python3 -c "import json;print(json.load(open('$STATE_FILE'))['mode'])")

# 1) ffmpeg 정상 종료 (SIGINT → 파일 마무리)
if kill -0 "$PID" 2>/dev/null; then
  kill -INT "$PID"
  # 최대 10초 대기
  for _ in $(seq 1 20); do
    kill -0 "$PID" 2>/dev/null || break
    sleep 0.5
  done
fi

# 2) 오디오 출력 복원 (화상 모드였을 때)
if [[ "$MODE" == "video" ]] && command -v SwitchAudioSource >/dev/null 2>&1; then
  RESTORE_TO="${PREV_OUTPUT:-$DEFAULT_OUTPUT_DEVICE}"
  [[ -n "$RESTORE_TO" ]] && SwitchAudioSource -t output -s "$RESTORE_TO" || true
fi

# 3) macOS 집중 모드 끄기
if [[ -n "${FOCUS_SHORTCUT_OFF:-}" ]]; then
  shortcuts run "$FOCUS_SHORTCUT_OFF" || true
fi

# 4) Slack DND 해제 + 상태 초기화
curl -s -X POST "https://slack.com/api/dnd.endSnooze" \
  -H "Authorization: Bearer $SLACK_USER_TOKEN" > /dev/null || true

curl -s -X POST "https://slack.com/api/users.profile.set" \
  -H "Authorization: Bearer $SLACK_USER_TOKEN" \
  -H "Content-Type: application/json; charset=utf-8" \
  -d '{"profile":{"status_text":"","status_emoji":""}}' > /dev/null || true

# 5) 후처리 파이프라인을 백그라운드로 실행 (STT + 요약, 수 분 소요)
# venv가 있으면 venv python 사용 (setup.sh가 생성)
PYBIN="$SCRIPT_DIR/../.venv/bin/python3"
[[ -x "$PYBIN" ]] || PYBIN="python3"

nohup "$PYBIN" "$SCRIPT_DIR/process_meeting.py" "$STATE_FILE" "$MANUAL_ATTENDEES" \
  > "$MEETINGS_DIR/.process.log" 2>&1 &

echo "✅ 녹음 종료 — 회의록 생성 중 (완료 시 알림)"
