#!/bin/bash
# SwiftBar 플러그인: 미팅 녹음 상태 표시
# 파일명의 .5s 가 갱신 주기(5초)를 의미합니다 — 이름을 바꾸면 주기도 바뀜.
#
# <xbar.title>Meeting Flow Recording Indicator</xbar.title>
# <xbar.desc>녹음 중이면 메뉴바에 🔴 경과시간 표시, 클릭 시 미팅 끝</xbar.desc>

MEETINGS_DIR="$HOME/Meetings"
STATE_FILE="$MEETINGS_DIR/.current_session.json"
# meeting-flow 설치 경로 (본인 환경에 맞게 수정)
FLOW_DIR="$HOME/Documents/flo/AX/meeting-flow"

if [[ ! -f "$STATE_FILE" ]]; then
  # 녹음 중 아님 — 메뉴바에 아무것도 표시하지 않음
  # (빈 칸이 거슬리면 아래 주석을 해제해 회색 마이크로 대체)
  # echo "🎙 | sfcolor=gray"
  echo ""
  exit 0
fi

# start_ts 추출 (jq 없이 grep으로)
START_TS=$(grep -o '"start_ts":[[:space:]]*[0-9]*' "$STATE_FILE" | grep -o '[0-9]*$')
MODE=$(grep -o '"mode":[[:space:]]*"[a-z]*"' "$STATE_FILE" | grep -o '[a-z]*"$' | tr -d '"')

NOW=$(date +%s)
ELAPSED=$((NOW - ${START_TS:-$NOW}))
H=$((ELAPSED / 3600))
M=$(((ELAPSED % 3600) / 60))
S=$((ELAPSED % 60))
if (( H > 0 )); then
  TIMER=$(printf "%d:%02d:%02d" "$H" "$M" "$S")
else
  TIMER=$(printf "%02d:%02d" "$M" "$S")
fi

ICON="🔴"
[[ "$MODE" == "video" ]] && ICON="🔴📹"

# 메뉴바 표시줄
echo "$ICON $TIMER"
echo "---"
# 드롭다운 메뉴
echo "녹음 중 (${MODE:-offline} 모드)"
echo "미팅 끝 — 회의록 생성 | bash='$FLOW_DIR/scripts/meeting-end.sh' terminal=false refresh=true"
echo "녹음 폴더 열기 | bash='/usr/bin/open' param1='$MEETINGS_DIR' terminal=false"
