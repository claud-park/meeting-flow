#!/bin/bash
# tick.py를 5분마다 실행하는 launchd 에이전트를 설치(또는 갱신)한다.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PYBIN="$REPO_DIR/.venv/bin/python3"
[[ -x "$PYBIN" ]] || PYBIN="$(command -v python3)"
MEETINGS_DIR="$(grep -E '^MEETINGS_DIR=' "$REPO_DIR/config.env" 2>/dev/null | cut -d'"' -f2 | sed "s|\$HOME|$HOME|")"
MEETINGS_DIR="${MEETINGS_DIR:-$HOME/Meetings}"
mkdir -p "$MEETINGS_DIR"

LABEL="com.meetingflow.tick"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
mkdir -p "$HOME/Library/LaunchAgents"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PYBIN</string>
    <string>$SCRIPT_DIR/tick.py</string>
  </array>
  <key>StartInterval</key><integer>300</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$MEETINGS_DIR/.tick.log</string>
  <key>StandardErrorPath</key><string>$MEETINGS_DIR/.tick.log</string>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string></dict>
</dict>
</plist>
EOF

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "설치: $PLIST (5분 간격, 로그: $MEETINGS_DIR/.tick.log)"
echo "상태 확인: launchctl print gui/$(id -u)/$LABEL | head -20"
