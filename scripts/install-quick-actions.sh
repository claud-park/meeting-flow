#!/bin/bash
# Raycast 없이 "미팅 시작/끝"을 실행하기 위한 macOS Quick Action(Services) 설치기.
# ~/Library/Services/ 에 .workflow 번들 3개를 만들고, 시스템 설정 > 키보드 >
# 키보드 단축키 > 서비스 에서 단축키를 지정할 수 있게 한다.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SERVICES_DIR="$HOME/Library/Services"

if [[ ! -x "$SCRIPT_DIR/meeting-start.sh" || ! -x "$SCRIPT_DIR/meeting-end.sh" || ! -x "$SCRIPT_DIR/review-open.sh" ]]; then
  echo "scripts/meeting-start.sh, meeting-end.sh 에 실행 권한이 없습니다: chmod +x scripts/*.sh" >&2
  exit 1
fi

mkdir -p "$SERVICES_DIR"

xml_escape() {
  sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g' <<< "$1"
}

install_quick_action() {
  local name="$1" command_string="$2" slug="$3"
  local bundle="$SERVICES_DIR/${name}.workflow"
  local escaped_name escaped_command
  escaped_name="$(xml_escape "$name")"
  escaped_command="$(xml_escape "$command_string")"

  rm -rf "$bundle"
  mkdir -p "$bundle/Contents"

  cat > "$bundle/Contents/document.wflow" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>AMApplicationBuild</key>
	<string>523</string>
	<key>AMApplicationVersion</key>
	<string>2.10</string>
	<key>AMDocumentVersion</key>
	<string>2</string>
	<key>actions</key>
	<array>
		<dict>
			<key>action</key>
			<dict>
				<key>AMAccepts</key>
				<dict>
					<key>Container</key>
					<string>List</string>
					<key>Optional</key>
					<true/>
					<key>Types</key>
					<array>
						<string>com.apple.applescript.object</string>
					</array>
				</dict>
				<key>AMActionVersion</key>
				<string>2.0.3</string>
				<key>AMApplication</key>
				<array>
					<string>Automator</string>
				</array>
				<key>AMParameterProperties</key>
				<dict>
					<key>COMMAND_STRING</key>
					<dict/>
					<key>CheckedForUserDefaultShell</key>
					<dict/>
					<key>inputMethod</key>
					<dict/>
					<key>shell</key>
					<dict/>
					<key>source</key>
					<dict/>
				</dict>
				<key>AMProvides</key>
				<dict>
					<key>Container</key>
					<string>List</string>
					<key>Types</key>
					<array>
						<string>com.apple.applescript.object</string>
					</array>
				</dict>
				<key>ActionBundlePath</key>
				<string>/System/Library/Automator/Run Shell Script.action</string>
				<key>ActionName</key>
				<string>Run Shell Script</string>
				<key>ActionParameters</key>
				<dict>
					<key>COMMAND_STRING</key>
					<string>${escaped_command}</string>
					<key>CheckedForUserDefaultShell</key>
					<true/>
					<key>inputMethod</key>
					<integer>0</integer>
					<key>shell</key>
					<string>/bin/bash</string>
					<key>source</key>
					<string></string>
				</dict>
				<key>BundleIdentifier</key>
				<string>com.apple.RunShellScript</string>
				<key>CFBundleVersion</key>
				<string>2.0.3</string>
				<key>CanShowSelectedItemsWhenRun</key>
				<false/>
				<key>CanShowWhenRun</key>
				<true/>
				<key>Category</key>
				<array>
					<string>AMCategoryUtilities</string>
				</array>
				<key>Class Name</key>
				<string>RunShellScriptAction</string>
				<key>InputUUID</key>
				<string>11111111-1111-1111-1111-111111111111</string>
				<key>Keywords</key>
				<array>
					<string>Shell</string>
					<string>Script</string>
					<string>Command</string>
					<string>Run</string>
					<string>Unix</string>
				</array>
				<key>OutputUUID</key>
				<string>22222222-2222-2222-2222-222222222222</string>
				<key>UUID</key>
				<string>33333333-3333-3333-3333-333333333333</string>
				<key>UnlocalizedApplications</key>
				<array>
					<string>Automator</string>
				</array>
				<key>arguments</key>
				<dict/>
				<key>isViewVisible</key>
				<true/>
			</dict>
			<key>isViewVisible</key>
			<true/>
		</dict>
	</array>
	<key>connectors</key>
	<dict/>
	<key>workflowMetaData</key>
	<dict>
		<key>serviceInputTypeIdentifier</key>
		<string>com.apple.Automator.nothing</string>
		<key>serviceOutputTypeIdentifier</key>
		<string>com.apple.Automator.nothing</string>
		<key>serviceProcessesInput</key>
		<integer>0</integer>
		<key>workflowTypeIdentifier</key>
		<string>com.apple.Automator.servicesMenu</string>
	</dict>
</dict>
</plist>
EOF

  cat > "$bundle/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>CFBundleIdentifier</key>
	<string>com.meetingflow.quickaction.${slug}</string>
	<key>CFBundleName</key>
	<string>${escaped_name}</string>
	<key>NSServices</key>
	<array>
		<dict>
			<key>NSMenuItem</key>
			<dict>
				<key>default</key>
				<string>${escaped_name}</string>
			</dict>
			<key>NSMessage</key>
			<string>runWorkflowAsService</string>
		</dict>
	</array>
</dict>
</plist>
EOF

  echo "설치: ${name}"
}

install_quick_action "미팅 시작" "\"$REPO_DIR/scripts/meeting-start.sh\"" "start"
install_quick_action "미팅 시작 (화상)" "\"$REPO_DIR/scripts/meeting-start.sh\" 화상" "start-video"
install_quick_action "미팅 끝" "\"$REPO_DIR/scripts/meeting-end.sh\"" "end"
install_quick_action "타임블록 검토" "\"$REPO_DIR/scripts/review-open.sh\"" "review"

/System/Library/CoreServices/pbs -flush > /dev/null 2>&1 || true

cat <<'EOF'

Quick Action 4개를 ~/Library/Services/ 에 설치했습니다:
  - 미팅 시작
  - 미팅 시작 (화상)
  - 미팅 끝
  - 타임블록 검토

단축키 지정:
  시스템 설정 > 키보드 > 키보드 단축키... > 서비스
  → 위 4개 항목을 찾아 단축키를 지정하세요.

바로 실행해보려면:
  메뉴바(있다면) 또는 Finder에서 우클릭 > 서비스 메뉴에서 항목을 선택하세요.
  목록에 안 보이면 로그아웃 후 재로그인하거나 Automator 앱을 한 번 실행해보세요.

리포지토리를 다른 경로로 옮기면 이 스크립트를 다시 실행해야 합니다
(스크립트 경로가 설치 시점 기준으로 고정되기 때문).
EOF
