#!/bin/bash
# ============================================================
# Meeting Flow 설치 스크립트
#   brew 의존성 → venv → config.env 대화형 생성 → 다음 단계 안내
#   실행: ./setup.sh
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

bold() { printf "\033[1m%s\033[0m\n" "$1"; }
ok()   { printf "  \033[32m✅ %s\033[0m\n" "$1"; }
warn() { printf "  \033[33m⚠️  %s\033[0m\n" "$1"; }

bold "═══ Meeting Flow 설치 ═══"
echo ""

# ---------- 1. Homebrew 의존성 ----------
bold "[1/4] 의존성 설치"
if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew가 없습니다. https://brew.sh 에서 먼저 설치하세요."
  exit 1
fi

for pkg in ffmpeg ical-buddy switchaudio-osx; do
  if brew list "$pkg" >/dev/null 2>&1; then
    ok "$pkg (이미 설치됨)"
  else
    echo "  설치 중: $pkg ..."
    brew install "$pkg"
    ok "$pkg"
  fi
done

if ls /Library/Audio/Plug-Ins/HAL/ 2>/dev/null | grep -qi blackhole; then
  ok "BlackHole (이미 설치됨)"
else
  echo "  설치 중: blackhole-2ch (관리자 비밀번호 필요) ..."
  brew install --cask blackhole-2ch
  warn "BlackHole은 재부팅(또는 'sudo killall coreaudiod') 후 인식됩니다"
fi
echo ""

# ---------- 2. Python venv ----------
bold "[2/4] Python 가상환경"
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet boto3 requests
ok "venv + boto3, requests"
echo ""

# ---------- 3. config.env 대화형 생성 ----------
bold "[3/4] 설정 파일 (config.env)"
if [[ -f config.env ]]; then
  warn "config.env가 이미 있어 건너뜁니다 (수정: open -e config.env)"
else
  cp config.env.example config.env
  echo "  각 값을 입력하세요. 아직 모르면 Enter로 건너뛰고 나중에 채워도 됩니다."
  echo ""

  ask() {  # ask VAR_NAME "질문"
    local var="$1" prompt="$2" val
    read -r -p "  $prompt: " val </dev/tty || val=""
    if [[ -n "$val" ]]; then
      # sed 특수문자 이스케이프 후 치환
      local esc
      esc=$(printf '%s' "$val" | sed 's/[&/\]/\\&/g')
      sed -i '' "s|^$var=.*|$var=\"$esc\"|" config.env
    fi
  }

  ask NCP_ACCESS_KEY   "NCP Access Key"
  ask NCP_SECRET_KEY   "NCP Secret Key"
  ask NCP_BUCKET       "NCP 버킷 이름"
  ask CLOVA_INVOKE_URL "CLOVA Invoke URL"
  ask CLOVA_SECRET_KEY "CLOVA Secret Key"
  ask ANTHROPIC_API_KEY "Anthropic API Key"
  ask SLACK_USER_TOKEN "Slack User Token (없으면 Enter — DND 기능만 비활성)"
  ask OBSIDIAN_DIR     "Obsidian 회의록 폴더 경로 (예: \$HOME/Documents/vault/Meetings)"
  ok "config.env 생성됨"
fi

# 캘린더 이름 선택 안내
echo ""
echo "  사용 가능한 캘린더 목록:"
icalBuddy calendars 2>/dev/null | sed 's/^/    /' || warn "icalBuddy 실행 실패 — 캘린더 권한 허용 후 재시도"
echo "  → config.env의 CALENDAR_NAME에 위 목록 중 회사 캘린더 이름을 정확히 입력하세요."
echo ""

chmod +x scripts/*.sh

# ---------- 4. 남은 수동 단계 안내 ----------
bold "[4/4] 남은 수동 단계 (GUI라 자동화 불가)"
cat <<'GUIDE'

  ① 오디오 장치 (오디오 MIDI 설정 앱, 재부팅 후):
     - 집계 기기 생성: MacBook Pro 마이크 + BlackHole 2ch 체크
     - 다중 출력 기기 생성: 평소 스피커 + BlackHole 2ch 체크 (화상회의용)
     - 인덱스 확인: ffmpeg -f avfoundation -list_devices true -i ""
       → 집계 기기 번호를 config.env의 AUDIO_DEVICE_INDEX에 입력

  ② Raycast 등록:
     Raycast 설정 > Extensions > + > Add Script Directory > 이 폴더의 scripts/ 선택

  ③ 설치 검증:
     ./doctor.sh    ← 모든 연결을 자동 점검합니다

  ④ 첫 테스트:
     Raycast에서 '미팅 시작' → 30초 말하기 → '미팅 끝'
     (첫 실행 시 마이크/캘린더 권한 팝업 → 모두 허용)

GUIDE
bold "설치 스크립트 완료. 다음은 ./doctor.sh 를 실행하세요."
