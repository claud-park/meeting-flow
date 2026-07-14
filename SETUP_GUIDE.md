# SETUP_GUIDE.md — AI 어시스턴트와 함께 설치하기

> **사용법**: 이 저장소를 클론한 뒤, Claude Desktop / Claude Code에게
> "이 폴더의 SETUP_GUIDE.md를 읽고 Meeting Flow 설치를 도와줘"라고 요청하세요.
> 이 문서는 사람과 AI 모두를 위한 설치 명세 + 실전에서 검증된 트러블슈팅 지식입니다.

## 시스템 개요

macOS에서 `미팅 시작`/`미팅 끝` 트리거로 동작하는 회의록 자동화:

```
미팅 시작 → Slack DND(선택) → ffmpeg 녹음 (집계 오디오 장치, 16kHz mono)
미팅 끝  → 녹음 종료 → icalBuddy로 캘린더 이벤트명 바인딩
         → NCP Object Storage 업로드 → CLOVA Speech 화자분리 (sync)
         → Claude API 요약 → Obsidian vault에 md 저장 → macOS 알림
```

- 트리거: Raycast Script Commands (`scripts/meeting-start.sh`, `meeting-end.sh`)
- 후처리: `scripts/process_meeting.py` (venv 사용)
- 설정: `config.env` (config.env.example 참고)
- 진단: `./doctor.sh` — **설치 후 반드시 실행**

## AI 어시스턴트를 위한 설치 절차

1. `./setup.sh` 실행을 안내 (brew 의존성, venv, config.env 대화형 생성)
2. 사용자와 함께 GUI 단계 진행:
   - 오디오 MIDI 설정에서 집계 기기(마이크+BlackHole) / 다중 출력 기기(스피커+BlackHole) 생성
   - NCP 콘솔: 장문 인식 도메인 + Object Storage 버킷 + **도메인-버킷 연동**
   - Slack 앱 생성 (선택): User Token Scopes에 `dnd:write`, `users.profile:write`
3. `./doctor.sh` 실행 → 실패 항목을 아래 트러블슈팅 표로 해결
4. 테스트: Raycast `미팅 시작` → 30초 발화 → `미팅 끝` → Obsidian에 md 확인

## 검증된 트러블슈팅 지식 (실제 설치에서 발생했던 이슈)

| 증상 | 원인 | 해결 |
|---|---|---|
| `pip install` 시 `externally-managed-environment` | Homebrew Python 정책 | venv 사용 (setup.sh가 자동 처리). 스크립트는 `.venv/bin/python3`을 자동 감지 |
| BlackHole이 오디오 장치 목록에 없음 | 드라이버 미로드 | 재부팅 또는 `sudo killall coreaudiod` 후 오디오 MIDI 설정 재실행. MDM이 차단하면 시스템 설정 > 개인정보 보호에서 허용 |
| config.env `unexpected EOF while looking for matching...` | 따옴표 짝 불일치 (붙여넣기 중 유실) | `awk 'gsub(/"/,"\"")%2==1{print NR": "$0}' config.env`로 홀수 따옴표 줄 탐색. doctor.sh가 자동 검출 |
| NCP 업로드 `AccessDenied` — list는 되는데 put만 실패 | **boto3 1.36+ 기본 체크섬 전송을 NCP가 미지원** | boto3 클라이언트에 `Config(request_checksum_calculation="when_required", response_checksum_validation="when_required")` — 이미 코드에 반영됨. 절대 제거하지 말 것 |
| CLOVA 400 `callback url이나 resultToObs 설정이 필요합니다` | `completion: async`는 콜백 필수 | `completion: "sync"` + timeout 1800s 사용 — 이미 코드에 반영됨 |
| CLOVA `Object Storage 경로가 존재하지 않습니다` | (a) 파일이 실제로 버킷에 없음 (b) 도메인이 다른 버킷에 연동 | (a) 업로드 성공 여부 먼저 확인 (b) CLOVA 콘솔에서 도메인의 연동 버킷 확인 |
| 녹음 파일 0바이트 | 오디오 인덱스 오류 또는 마이크 권한 | `ffmpeg -f avfoundation -list_devices true -i ""`로 재확인. 블루투스 기기 연결/해제 시 인덱스가 밀림. 마이크 권한: 시스템 설정 > 개인정보 보호 > 마이크 > Raycast |
| `미팅 시작`이 조용히 아무것도 안 함 | silent 모드 토스트를 놓침 / 권한 미허용 | `ls -lh ~/Meetings/`로 wav 증가 확인. 터미널에서 직접 `scripts/meeting-start.sh` 실행하면 전체 출력 보임 |
| ffmpeg 장치 목록 명령 끝의 `Error opening input` | 정상 (입력 파일이 없어서 나는 에러) | 무시 |
| 한글 dataKey 관련 이슈 가능성 | S3 호환 스토리지의 non-ASCII 키 처리 | 업로드 키는 ASCII 타임스탬프 사용 — 이미 코드에 반영됨 (로컬 파일명/노트는 한글 유지) |

## 로그 위치

- `~/Meetings/.ffmpeg.log` — 녹음 문제
- `~/Meetings/.process.log` — 후처리 (캘린더/업로드/CLOVA/요약/저장) 문제
- `~/Meetings/.current_session.failed.json` — 실패한 세션 백업.
  재처리: `.venv/bin/python3 scripts/process_meeting.py <failed.json 경로>`

## AI 어시스턴트 행동 지침

- 코드의 boto3 `Config(...)` 체크섬 설정과 CLOVA `sync` 모드는 검증된 필수 사항이니 "단순화" 명목으로 제거하지 말 것
- 사용자 환경마다 오디오 장치 구성이 다르므로, 항상 `ffmpeg -list_devices` 실제 출력을 확인한 후 인덱스를 안내할 것
- 문제 발생 시 임의 추측 대신 `./doctor.sh` 출력과 위 로그를 먼저 확인할 것
- API 키를 채팅에 노출하지 않도록 안내할 것 (config.env에만 저장)
