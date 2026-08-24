# Meeting Flow 🎙

맥북에서 `미팅 시작` / `미팅 끝` 한 마디로 돌아가는 회의록 자동화 파이프라인.

```
미팅 시작 ─→ Slack DND + 상태 "🎙 회의 중" + macOS 집중 모드 ─→ ffmpeg 녹음 시작
미팅 끝  ─→ 녹음 종료 ─→ 캘린더 이벤트명 바인딩 ─→ NCP 업로드
         ─→ CLOVA Speech 화자분리 ─→ Claude 요약 (회의 유형별 템플릿
         + 관련 프로젝트 링크) ─→ Obsidian 저장 ─→ 완료 알림
```

## 1. 의존성 설치

```bash
brew install ffmpeg ical-buddy switchaudio-osx blackhole-2ch
pip3 install boto3 requests
```

## 2. 오디오 장치 구성 (1회)

**집계 장치 만들기** — `오디오 MIDI 설정` 앱 → 좌하단 `+` → **집계 기기 생성**
→ `MacBook Pro 마이크` + `BlackHole 2ch` 체크. 이름 그대로 두면 됨.

**다중 출력 장치 만들기** (화상회의용) — 같은 앱에서 **다중 출력 기기 생성**
→ 평소 쓰는 스피커/헤드폰 + `BlackHole 2ch` 체크.

**장치 인덱스 확인**:
```bash
ffmpeg -f avfoundation -list_devices true -i ""
```
`[AVFoundation indev]` audio 목록에서 **집계 장치(Aggregate Device)** 의 번호를
`config.env`의 `AUDIO_DEVICE_INDEX`에 입력.

## 3. Slack 토큰 (1회)

1. https://api.slack.com/apps → Create New App (From scratch)
2. OAuth & Permissions → **User Token Scopes**에 `dnd:write`, `users.profile:write` 추가
3. Install to Workspace → `xoxp-` 로 시작하는 User OAuth Token 복사

## 3.5. macOS 집중 모드 연동 (선택, 1회)

Slack DND는 Slack 알림만 막으므로, 녹음(특히 화상 모드의 시스템 오디오)에
다른 앱 알림음이 섞이는 걸 막으려면 macOS 집중 모드를 함께 켠다.

1. 단축어 앱에서 두 개 생성:
   - 켜기: `집중 모드 설정 > 방해금지 > 끌 때까지 켜기` (until: Turned Off)
   - 끄기: 같은 동작에서 `끄기`
2. 두 단축어 이름을 `config.env`의 `FOCUS_SHORTCUT_ON` / `FOCUS_SHORTCUT_OFF`에 입력.
   비워두면 이 단계는 건너뛴다.

## 4. NCP 세팅 (1회)

1. Object Storage 버킷 생성 (예: `meeting-recordings`)
2. CLOVA Speech > **장문 인식 도메인** 생성 시 해당 버킷 연동
3. 도메인 상세에서 `Invoke URL`, `Secret Key` 복사
4. 마이페이지 > 인증키 관리에서 `Access Key` / `Secret Key` 발급 (Object Storage용)

## 5. 캘린더 이름 확인

```bash
icalBuddy calendars
```
목록에서 회사 계정 캘린더의 정확한 이름을 `CALENDAR_NAME`에 입력.
(Mac 캘린더 앱에 회사 Google 계정이 연동되어 있어야 함: 시스템 설정 > 인터넷 계정)

> 처음 실행 시 macOS가 캘린더 접근 권한을 물으면 허용. 터미널/Raycast에
> `시스템 설정 > 개인정보 보호 > 캘린더` 권한 필요.

## 6. 설정 파일

```bash
cp config.env.example config.env
# config.env 열어서 값 채우기
chmod +x scripts/*.sh
```

## 7. 트리거 등록

녹음 시작/종료를 실행할 방법을 하나 고른다. Raycast가 있으면 7-A, 없으면 7-B.

### 7-A. Raycast

Raycast > Settings > Extensions > Script Commands > **Add Directories**
→ 이 저장소의 `scripts/` 폴더 지정.

- `미팅 시작` — 인자 없이 실행하면 오프라인 모드
- `미팅 시작` + 인자 `화상` — 시스템 출력을 다중 출력 장치로 전환해 상대방 음성도 녹음
- `미팅 끝` — 녹음 종료 후 백그라운드에서 회의록 생성 (완료되면 macOS 알림)

각 커맨드에 단축키(예: `⌥⌘M` / `⌥⌘E`)를 걸어두면 더 빠름.

### 7-B. Raycast 없이 (macOS Quick Action)

Raycast 없이도 macOS 자체 기능(Automator Quick Action / Services)만으로 단축키를
쓸 수 있다.

```bash
./scripts/install-quick-actions.sh
```

`~/Library/Services/`에 아래 3개 항목이 설치된다:

- **미팅 시작** — 오프라인 모드
- **미팅 시작 (화상)** — 화상회의 모드
- **미팅 끝** — 녹음 종료 (참석자 인자가 필요하면 터미널에서
  `scripts/meeting-end.sh "이름1,이름2"` 로 직접 실행)

단축키 지정: **시스템 설정 > 키보드 > 키보드 단축키... > 서비스** 에서 위 3개
항목을 찾아 원하는 단축키를 지정. Finder나 메뉴바의 서비스(⚙️) 메뉴에서도 바로
실행 가능. 목록에 안 보이면 로그아웃 후 재로그인.

> 리포지토리를 다른 경로로 옮기면 스크립트 경로가 설치 시점 기준으로 고정되어
> 있으므로 `install-quick-actions.sh`를 다시 실행해야 한다.

## 트러블슈팅

- **녹음 파일이 0바이트**: `AUDIO_DEVICE_INDEX`가 잘못됨. 장치 목록 다시 확인.
  (블루투스 이어폰 연결 여부에 따라 인덱스가 바뀔 수 있음 — 집계 장치를 쓰면 영향 최소화)
- **마이크 권한**: 최초 실행 시 `시스템 설정 > 개인정보 보호 > 마이크`에서 터미널/Raycast 허용.
- **화상회의에서 상대방 소리가 안 들림**: 다중 출력 장치가 출력으로 선택되면 볼륨 조절이
  안 되는 것이 정상(macOS 제약). 다중 출력 기기 설정에서 기본 장치의 드리프트 보정 체크.
- **CLOVA 실패**: `~/Meetings/.process.log` 확인. 도메인-버킷 연동 여부가 흔한 원인.
- **처리 실패 후 재시도**: `~/Meetings/.current_session.failed.json`을 인자로
  `python3 scripts/process_meeting.py <파일>` 직접 실행하면 녹음본으로 재처리 가능.

## 파일 구조

```
meeting-flow/
├── config.env.example   # 설정 템플릿 (config.env로 복사)
├── scripts/
│   ├── meeting-start.sh           # 미팅 시작 (Raycast/Quick Action 공용)
│   ├── meeting-end.sh             # 미팅 끝 (Raycast/Quick Action 공용)
│   ├── install-quick-actions.sh   # Raycast 없이 쓰기 위한 macOS Quick Action 설치
│   └── process_meeting.py         # 후처리 파이프라인
├── templates/           # 회의 유형별 요약 템플릿
│   ├── default.md          # 기본 (매칭 없을 때)
│   ├── str-weekly.md       # STR Weekly
│   ├── ax-champion-weekly.md
│   └── ax-1on1.md          # [AX] 1-on-1
└── README.md
```

## 요약 템플릿

회의 제목(캘린더 이벤트명)에 따라 다른 요약 템플릿을 사용한다.
`config.env`의 `TEMPLATE_RULES`에 `키워드:템플릿명`을 쉼표로 나열하면,
제목에 키워드가 포함되는(대소문자 무시) 첫 규칙의 `templates/<템플릿명>.md`를
프롬프트 형식으로 사용한다. 매칭이 없으면 `templates/default.md`.

새 유형 추가: `templates/`에 md 파일을 만들고 `TEMPLATE_RULES`에 규칙 한 줄 추가.
코드 수정 불필요.

## 관련 프로젝트 자동 연결

`PROJECTS_DIR`을 Obsidian 프로젝트 노트 폴더로 지정하면, 요약 시 폴더의
노트 목록(하위 폴더 포함)을 Claude에게 함께 전달해 회의 제목·전사록 내용과
관련된 프로젝트를 고르게 한다. 결과는 두 곳에 반영된다:

- 회의록 끝의 `## 🔗 관련 프로젝트` 섹션 — `[[노트명]] (근거 한 줄)` 목록
- frontmatter의 `projects: ["[[노트명]]"]` — 그래프뷰/백링크에서 프로젝트별
  회의록이 자동으로 모임

실제로 존재하는 노트 이름만 링크로 저장되며(할루시네이션 차단),
`PROJECTS_DIR`을 비워두면 기능이 꺼진다.

**별칭**: 프로젝트가 회의에서 다른 이름으로 불린다면 `PROJECT_ALIASES`에
`별칭:노트명`을 쉼표로 나열한다. 같은 노트에 별칭 여러 개도 가능.

```
PROJECT_ALIASES="BI:ax-view360,법무검토:ax-legal-management-system"
```
