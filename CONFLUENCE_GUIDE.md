# [Confluence 게시용 초안] Meeting Flow — 회의록 자동화 도구 온보딩 가이드

> 이 문서를 Confluence에 붙여넣고, 📸 표시 위치에 본인 설치 때 캡처한 스크린샷을 넣으면 완성입니다.

---

## 이게 뭔가요?

맥북에서 Raycast로 **`미팅 시작`** 을 실행하면 녹음이 시작되고(+Slack 방해금지),
**`미팅 끝`** 을 실행하면 몇 분 뒤 **화자분리된 회의록 + AI 요약**이 Obsidian에 자동 저장되는 도구입니다.

- 오프라인 회의실 / 화상회의 모두 지원
- 회의명은 본인 캘린더 일정에서 자동으로 가져옴
- 결과물: 요약 / 주요 논의 / 결정사항 / 액션아이템 + 화자별 전체 전사록

⏱ 설치 소요: 약 30분 (대부분 1회성 세팅)
💰 비용: 1시간 회의당 약 2,000~2,600원 (팀 공용 토큰 사용 — 아래 참고)

## 준비물

| 항목 | 어디서 | 비고 |
|---|---|---|
| Raycast | https://raycast.com | 무료 |
| Homebrew | https://brew.sh | 이미 있으면 생략 |
| 팀 공용 API 키 | 담당자(예림)에게 요청 | NCP 키 2종 + CLOVA 2종 + Anthropic 키 |
| Slack 토큰 (선택) | 본인이 직접 발급 (아래 안내) | 없어도 녹음/회의록은 동작 |
| Obsidian vault | 본인 것 | 없으면 아무 폴더나 지정해도 md는 생성됨 |

> 🔑 **팀 공용 키 정책**: NCP/CLOVA/Anthropic 키는 팀 계정으로 관리합니다.
> 키를 개인 메신저로 재공유하지 마시고, 퇴사/이동 시 담당자에게 알려주세요.

## 설치 (자동)

```bash
git clone <repo-url> ~/meeting-flow
cd ~/meeting-flow
./setup.sh
```

setup.sh가 의존성 설치 → Python 환경 → 설정 파일 생성까지 대화형으로 진행합니다.
키 값을 물어보면 담당자에게 받은 값을 붙여넣으세요.

📸 (setup.sh 실행 화면)

> 💡 **막히면 AI에게**: Claude Desktop/Claude Code에서 이 폴더를 열고
> "SETUP_GUIDE.md 읽고 설치 도와줘"라고 하면 환경별 문제를 대화로 해결해줍니다.

## 수동 세팅 (GUI, 1회)

### 1. 오디오 장치 — 5분

BlackHole 설치 후 **재부팅**하고, Spotlight에서 "오디오 MIDI 설정" 실행:

1. 좌하단 `+` → **집계 기기 생성** → `MacBook Pro 마이크` + `BlackHole 2ch` 체크
2. `+` → **다중 출력 기기 생성** → 평소 스피커/이어폰 + `BlackHole 2ch` 체크

📸 (집계 기기 설정 화면)

터미널에서 장치 번호 확인 후 config.env의 `AUDIO_DEVICE_INDEX`에 입력:

```bash
ffmpeg -f avfoundation -list_devices true -i ""
```

audio devices 목록에서 `Aggregate Device`(집계 기기)의 `[숫자]`를 찾으면 됩니다.
마지막 줄의 빨간 "Error opening input"은 정상이니 무시하세요.

📸 (장치 목록 출력, 집계 기기 번호 표시)

### 2. Slack 토큰 (선택) — 5분

회의 중 자동 방해금지 + 상태 "🎙 회의 중" 표시 기능입니다. 나중에 해도 됩니다.

1. https://api.slack.com/apps → **Create New App** → From scratch
2. **OAuth & Permissions** → **User Token Scopes**(⚠️ Bot 아님)에
   `dnd:write`, `users.profile:write` 추가
3. **Install to Workspace** → `xoxp-`로 시작하는 토큰을 config.env에 입력

📸 (User Token Scopes 설정 화면)

### 3. 캘린더 확인 — 2분

Mac 캘린더 앱에 회사 계정이 연동돼 있어야 합니다.
(안 돼 있으면: 시스템 설정 > 인터넷 계정 > Google 추가)

```bash
icalBuddy calendars
```

목록에서 회사 캘린더 이름을 config.env의 `CALENDAR_NAME`에 정확히 입력.

### 4. Raycast 등록 — 2분

Raycast 설정(⌘,) → Extensions → 좌하단 `+` → **Add Script Directory**
→ `~/meeting-flow/scripts` 선택. `미팅 시작` / `미팅 끝`이 생깁니다.
단축키 추천: ⌥⌘M(시작) / ⌥⌘E(끝)

📸 (Raycast Script Commands 화면)

## 설치 검증

```bash
cd ~/meeting-flow && ./doctor.sh
```

모든 항목이 ✅면 준비 완료. ❌가 있으면 옆의 힌트대로 수정 후 재실행하세요.

📸 (doctor.sh 전체 통과 화면)

## 사용법

| 상황 | 실행 |
|---|---|
| 오프라인 회의 | Raycast → `미팅 시작` |
| 화상회의 (Zoom/Meet) | Raycast → `미팅 시작` + 인자 `화상` |
| 회의 종료 | Raycast → `미팅 끝` (선택: 참석자 수나 이름 입력 시 화자분리 정확도↑) |

첫 실행 시 마이크/캘린더 권한 팝업이 뜨면 **모두 허용**하세요.
`미팅 끝` 후 몇 분 뒤 "회의록 완성 ✅" 알림이 오고, Obsidian에 md가 생성됩니다.

📸 (완성된 회의록 예시 — 민감 내용 가리고)

⚠️ **녹음 에티켓**: 회의 시작 시 참석자에게 녹음 사실을 알려주세요.

## 자주 묻는 문제

| 증상 | 해결 |
|---|---|
| 녹음 파일이 0바이트 | 오디오 인덱스 재확인 (블루투스 연결/해제 시 번호가 바뀔 수 있음) |
| "미팅 시작" 해도 반응이 없어 보임 | 정상일 수 있음 — `ls -lh ~/Meetings/`로 wav 크기 증가 확인 |
| 회의록 생성 실패 알림 | `cat ~/Meetings/.process.log` 내용과 함께 담당자/AI에게 문의 |
| 화상회의 소리가 녹음 안 됨 | `미팅 시작`에 `화상` 인자를 줬는지 확인 |
| Obsidian에 파일이 안 보임 | config.env의 `OBSIDIAN_DIR` 경로 확인 |

문의: #febusiness-ai (또는 담당자 DM)
