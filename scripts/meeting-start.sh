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

# 4) 녹음 장치 선택 + ffmpeg 녹음 시작 (16kHz mono wav)
# 오프라인(대면) 모드는 시스템 오디오(BlackHole)가 필요 없는데, Aggregate Device의
# IO가 간헐적으로 BlackHole 서브 디바이스에 묶여 마이크 신호를 놓치는 경우가 있어
# 오프라인 모드는 물리 마이크를 이름으로 찾아 직접 지정한다.
REC_DEVICE_INDEX="$AUDIO_DEVICE_INDEX"
if [[ "$MODE" == "offline" && -n "${OFFLINE_MIC_NAME:-}" ]]; then
  # ffmpeg는 -list_devices 후 항상 0이 아닌 상태로 종료하므로(디바이스만 나열하고
  # 실제 입력은 열지 않기 때문), set -e/pipefail에 걸리지 않도록 || true로 무시한다.
  MIC_IDX="$(ffmpeg -f avfoundation -list_devices true -i "" 2>&1 \
    | awk '/AVFoundation audio devices:/{f=1;next} f' \
    | grep -F "] $OFFLINE_MIC_NAME" | head -1 | sed -E 's/.*\[([0-9]+)\] .*/\1/' || true)"
  if [[ -n "$MIC_IDX" ]]; then
    REC_DEVICE_INDEX="$MIC_IDX"
  else
    echo "[경고] '$OFFLINE_MIC_NAME' 마이크를 못 찾음 — AUDIO_DEVICE_INDEX로 폴백"
  fi
fi

START_TS="$(date +%s)"
WAV_PATH="$MEETINGS_DIR/rec_$(date +%Y%m%d_%H%M%S).wav"

nohup ffmpeg -hide_banner -loglevel error \
  -f avfoundation -i ":${REC_DEVICE_INDEX}" \
  -ac 1 -ar 16000 "$WAV_PATH" \
  > "$MEETINGS_DIR/.ffmpeg.log" 2>&1 &
FFMPEG_PID=$!

sleep 1
if ! kill -0 "$FFMPEG_PID" 2>/dev/null; then
  echo "녹음 시작 실패 — .ffmpeg.log 확인 (오디오 장치 인덱스 점검)"
  exit 1
fi

# 5) 무음 감지 프로브 (백그라운드, 논블로킹)
# 장치는 열렸지만 신호가 안 들어오는 경우(권한 꼬임, 라우팅 문제 등) 회의가
# 끝날 때까지 모르고 통째로 날리는 사고를 막기 위해, 녹음 시작 직후 같은
# 장치로 3초짜리 별도 프로브를 떠서 레벨을 확인한다.
# -80dB 기준: 디지털 무음 바닥(-91dB)보다는 높고 정상 실내 잡음(-40~-60dB)보다는
# 훨씬 낮아, 신호가 아예 안 들어오는 경우만 잡도록 잡은 값.
(
  sleep 3
  PROBE_WAV="$MEETINGS_DIR/.silence_probe.wav"
  ffmpeg -hide_banner -loglevel error -f avfoundation -i ":${REC_DEVICE_INDEX}" \
    -t 3 -ac 1 -ar 16000 -y "$PROBE_WAV" < /dev/null 2>>"$MEETINGS_DIR/.silence_probe.log"
  MEAN_DB=$(ffmpeg -hide_banner -v info -i "$PROBE_WAV" -af volumedetect -f null - 2>&1 \
    | sed -n 's/.*mean_volume: \(-\{0,1\}[0-9.]*\) dB.*/\1/p' | head -1)
  rm -f "$PROBE_WAV"
  echo "$(date '+%H:%M:%S') mean_volume=${MEAN_DB:-측정불가}dB" >> "$MEETINGS_DIR/.silence_probe.log"
  if [[ -z "$MEAN_DB" ]] || awk -v v="$MEAN_DB" 'BEGIN{exit !(v <= -80)}'; then
    osascript -e 'display notification "오디오 입력이 무음입니다 — 마이크 권한/Aggregate Device 라우팅을 확인하세요" with title "⚠️ 녹음 무음 감지"' || true
  fi
) > /dev/null 2>&1 &

# 6) 세션 상태 저장
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
