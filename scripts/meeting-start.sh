#!/bin/bash

# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title 미팅 시작
# @raycast.mode silent
# @raycast.packageName Meeting Flow

# Optional parameters:
# @raycast.icon 🎙
# @raycast.argument1 { "type": "text", "placeholder": "화상 (비우면 오프라인)", "optional": true }

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../config.env"

MODE="offline"
if [[ "${1:-}" == "화상" || "${1:-}" == "video" ]]; then
  MODE="video"
fi

STATE_FILE="$MEETINGS_DIR/.current_session.json"
mkdir -p "$MEETINGS_DIR"

# 이미 녹음 중이면 중단
if [[ -f "$STATE_FILE" ]]; then
  echo "이미 녹음 중입니다. 먼저 '미팅 끝'을 실행하세요."
  exit 1
fi

# 1) Slack DND + 상태 변경 (실패해도 녹음은 계속)
curl -s -X POST "https://slack.com/api/dnd.setSnooze" \
  -H "Authorization: Bearer $SLACK_USER_TOKEN" \
  -d "num_minutes=$SLACK_DND_MINUTES" > /dev/null || true

curl -s -X POST "https://slack.com/api/users.profile.set" \
  -H "Authorization: Bearer $SLACK_USER_TOKEN" \
  -H "Content-Type: application/json; charset=utf-8" \
  -d '{"profile":{"status_text":"회의 중","status_emoji":":studio_microphone:","status_expiration":0}}' > /dev/null || true

# 2) macOS 집중 모드 켜기 — 모든 앱 알림 차단 (녹음에 알림음 섞임 방지)
if [[ -n "${FOCUS_SHORTCUT_ON:-}" ]]; then
  shortcuts run "$FOCUS_SHORTCUT_ON" || true
fi

# 3) 화상 모드면 시스템 출력을 다중 출력 장치로 전환
PREV_OUTPUT=""
if [[ "$MODE" == "video" ]]; then
  if command -v SwitchAudioSource >/dev/null 2>&1; then
    PREV_OUTPUT="$(SwitchAudioSource -c -t output || true)"
    SwitchAudioSource -t output -s "$MULTI_OUTPUT_DEVICE" || true
  fi
fi

# 4) ffmpeg 녹음 시작 (집계 장치 → 16kHz mono wav)
START_TS="$(date +%s)"
WAV_PATH="$MEETINGS_DIR/rec_$(date +%Y%m%d_%H%M%S).wav"

nohup ffmpeg -hide_banner -loglevel error \
  -f avfoundation -i ":${AUDIO_DEVICE_INDEX}" \
  -ac 1 -ar 16000 "$WAV_PATH" \
  > "$MEETINGS_DIR/.ffmpeg.log" 2>&1 &
FFMPEG_PID=$!

sleep 1
if ! kill -0 "$FFMPEG_PID" 2>/dev/null; then
  echo "녹음 시작 실패 — .ffmpeg.log 확인 (오디오 장치 인덱스 점검)"
  exit 1
fi

# 5) 세션 상태 저장
cat > "$STATE_FILE" <<EOF
{
  "pid": $FFMPEG_PID,
  "start_ts": $START_TS,
  "wav_path": "$WAV_PATH",
  "mode": "$MODE",
  "prev_output": "$PREV_OUTPUT"
}
EOF

echo "🎙 녹음 시작 (${MODE}) — Slack DND·집중 모드 ON"
