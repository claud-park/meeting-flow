# Meeting Flow 자동 워크플로 설계

- 작성일: 2026-10-07
- 상태: 승인 대기 (브레인스토밍 합의 내용을 정리한 스펙)
- 범위: 회의록 이후 단계(내 액션 아이템 → 타임블록·미리알림)와 회의 이전 단계(브리핑)

## 1. 목표와 성공 기준

Meeting Flow는 `미팅 시작`과 `미팅 끝` 사이를 자동화하지만, 그 바깥은 사람이 한다.
이 설계는 두 축을 자동화한다.

1. **회의록 → 내 다음 행동.** 회의록이 완성되면 내 액션 아이템 중 기한이 있는 것을
   캘린더 타임블록 또는 미리알림 후보로 만들고, 검토 팝업에서 승인한 것만 반영한다.
2. **회의 전 브리핑.** 반복 회의 시작 15분 전에 지난 결정 사항, 미완료 액션 아이템,
   관련 프로젝트 근황을 한 장으로 만들어 알림으로 띄운다.

성공 기준: 회의가 끝나고 5분 안에 알림 클릭 한 번과 확인 버튼 한 번으로 내 다음 주
캘린더에 할 일 시간이 잡혀 있고, 다음 회의에 들어갈 때 지난 결정과 미완료 항목이
한 장으로 보인다.

범위 밖 (다음 사이클): 다른 참석자 몫의 액션 아이템 전달(Slack DM 초안 등),
캘린더 기반 자동 녹음, 주간 다이제스트, 실패 세션 자동 재처리.

## 2. 합의된 결정 사항

| 항목 | 결정 |
|---|---|
| 타임블록 반영 방식 | 검토 후 반영. 승인한 항목만 캘린더에 들어간다 |
| 검토 UI | 로컬 웹 팝업 (python 표준 라이브러리 HTTP 서버 + 브라우저 앱 모드) |
| 팝업 뜨는 시점 | 알림 클릭 시. 미처리 후보는 다음 날 아침 재알림. 수동 트리거도 제공 |
| 캘린더 쓰기 경로 | macOS 캘린더 앱에 AppleScript로 생성 → 회사 Google 계정으로 동기화 |
| 미리알림 경로 | macOS 미리알림 앱에 AppleScript로 생성 |
| 브리핑 대상 | 같은 제목의 지난 회의록이 있는 회의. 제목에 `[brief]`가 있으면 강제 |
| 브리핑 시점 | 시작 15분 전 (잠에서 깬 직후를 위해 시작 후 5분까지 허용) |
| 다른 참석자 몫 | 이번 범위에서 제외 |
| 실행 구조 | launchd 5분 주기 틱 + 필요할 때만 뜨는 팝업 서버. 상주 데몬 없음 |

## 3. 아키텍처

```
미팅 끝 ─→ process_meeting.py
            ├─ (기존) STT → 요약 → Obsidian 저장
            ├─ 브리핑이 있으면 요약 프롬프트에 포함, frontmatter에 brief 링크
            └─ actions.py: 내 액션 아이템 추출 → .pending/<note>.json → 알림(클릭 → review-open.sh)

알림 클릭 / 타임블록 검토 트리거 ─→ review-open.sh
            └─ review_server.py 기동(없을 때만) → 브라우저 앱 모드
                 ├─ GET /      : 후보 목록 + 7일 일정 + 제안 시간
                 └─ POST /apply: calendar_io로 캘린더·미리알림 생성
                                 → notes.py로 회의록에 ## 📅 타임블록 기록
                                 → pending을 done/으로 이동 → 결과 알림 → 서버 종료

launchd (5분) ─→ tick.py
            ├─ 미처리 후보 아침 재알림 / 만료 처리
            ├─ 15분 내 시작 이벤트 중 브리핑 대상 → brief.py → _briefs/ 저장 → 알림
            └─ done/, expired/ 30일 정리
```

상태는 모두 파일이다. `~/Meetings/.pending/`가 후보의 상태 저장소이고, Obsidian
회의록의 `## 📅 타임블록` 섹션이 사람이 읽는 기록이다.

## 4. 액션 아이템 추출 (`actions.py`)

**시점**: `process_meeting.py`가 회의록을 저장한 직후. 추출 실패는 회의록 생성 실패로
취급하지 않는다.

**입력**: 요약 본문의 `## ✅ 액션 아이템` 섹션, 참석자 명단, 회의 날짜, 다음 차수 날짜,
`MY_NAMES`.

**다음 차수 날짜**: `calendar_io`가 icalBuddy로 오늘 이후 30일 안에서 같은 정규화
제목의 가장 가까운 이벤트를 찾아 넘긴다. 없으면 `null`.

**호출**: 요약과 분리된 Claude 호출 한 번(`claude-sonnet-4-6`). JSON 배열만 출력하도록
지시하고, 파싱이 실패하면 "JSON만 출력"을 덧붙여 한 번 재시도한다. 두 번째도 실패하면
경고 알림을 보내고 후보를 만들지 않는다.

**항목 스키마**:

```json
{
  "id": "uuid4",
  "text": "법무 RNR 초안 작성",
  "owner": "Claud",
  "is_mine": true,
  "due": "2026-10-14",
  "due_source": "explicit | next_meeting | none",
  "kind": "block | reminder",
  "estimate_min": 60
}
```

- `is_mine`: `owner`가 `MY_NAMES` 중 하나와 일치(대소문자 무시)하면 참. 회의록에서
  `**공통**`으로 표기된 항목도 참으로 두되, 팝업에서 기본 체크를 해제한다.
- `is_mine`이 거짓인 항목은 후보 파일에 넣지 않는다.
- `due_source`가 `none`이면 후보에 넣되 기본 체크를 해제한다.
- `due`가 검토 시점에 이미 지난 항목은 기본 체크를 해제하고 "기한 지남" 표시를 붙인다.
- `kind`: 작업 시간이 필요하면 `block`, 확인·회신·참석처럼 짧으면 `reminder`.
  `estimate_min`은 30분 단위, `reminder`는 0.

**후보 파일** `~/Meetings/.pending/<회의록 파일명(.md 제외)>.json`:

```json
{
  "note_path": "/.../Meetings/2026-10-07_1005_[11층 몰디브] STR Weekly.md",
  "title": "[11층 몰디브] STR Weekly",
  "meeting_date": "2026-10-07",
  "created_at": "2026-10-07T11:40:00",
  "renotified_on": null,
  "items": [ ...위 스키마... ]
}
```

## 5. 검토 팝업과 반영 (`review_server.py`, `slots.py`, `calendar_io.py`)

**기동**: `review-open.sh`가 `.pending/.server.json`에 적힌 포트(기본 `REVIEW_PORT`)의
`/health`를 확인한다. 우리 서버가 아니면 서버를 띄우고, 포트가 다른 프로세스에
잡혀 있으면 다음 포트를 써서 `.server.json`에 기록한다. 브라우저는 Chrome이 있으면
`open -na "Google Chrome" --args --app=<url>`, 없으면 `open <url>`.
서버는 반영이 끝나거나 10분 동안 요청이 없으면 종료한다. 서버는 127.0.0.1에만 바인딩한다.

**화면**: 단일 HTML. 외부 자원 없음.

- 왼쪽: 회의별로 묶인 후보. 항목마다 체크박스, 종류(타임블록/미리알림), 제목, 날짜,
  시작 시간, 길이(30분 단위 select). `.pending/`의 모든 후보 파일을 한 화면에 보여 준다.
- 오른쪽: 오늘부터 7일간의 캘린더 일정을 날짜별로 압축 표시. 후보의 제안 시간은
  다른 색으로 겹쳐 표시하고, 항목의 날짜·시간을 고치면 즉시 갱신된다.
- 하단: "반영" 버튼. 승인된 항목 수와 결과 요약을 보여 준다.

**제안 시간 (`slots.py`)**:

1. 탐색 범위는 내일부터 `due` 전날까지의 평일. `due`가 없으면 제안하지 않고 날짜 입력을
   비워 둔다. `due`가 내일 이하면 `due` 당일 근무 시간을 범위로 한다.
2. `WORK_HOURS` 안에서 기존 일정과 겹치지 않는 구간을 찾되, 기한 전날부터 거꾸로
   올라가며 **가장 늦은** 빈 구간을 고른다. 길이는 `estimate_min`.
3. 같은 세션에서 이미 배치한 후보와도 겹치지 않게 한다.
4. 빈 구간이 없으면 기한 전날 근무 시간 끝에서 `estimate_min`만큼 앞선 시각으로 두고
   `conflict: true`를 붙여 화면에 "겹침"으로 표시한다.
5. `reminder`는 시간 대신 `due` 당일 `MORNING_REMIND_AT`을 기한 시각으로 쓴다.

**반영 (`POST /apply`)**: 요청 본문은 승인된 항목 목록(사용자 수정값 포함).

- `block`: AppleScript로 캘린더 앱의 `TIMEBLOCK_CALENDAR`(비면 `CALENDAR_NAME`)에
  이벤트 생성. summary는 제목, description은 `회의: <회의 제목>\n<obsidian 링크>`.
  obsidian 링크는 `obsidian://open?vault=<OBSIDIAN_VAULT_NAME>&file=<vault 상대 경로>`.
- `reminder`: AppleScript로 미리알림 앱의 `REMINDER_LIST`에 이름, 기한, 본문(회의 제목과
  링크)을 넣어 생성.
- 항목 단위로 실패를 격리한다. 실패한 항목은 응답에 오류 문구와 함께 돌려주고
  `.pending`에 남긴다. 성공한 항목은 `applied_at`을 기록해 재반영을 막는다.
- 모든 항목이 처리(반영 또는 건너뜀)되면 후보 파일을 `.pending/done/`으로 옮긴다.
- AppleScript 문자열은 따옴표·백슬래시를 이스케이프하고, 날짜는 `date "..."` 대신
  `current date`를 기준으로 연·월·일·시·분을 개별 설정해 로케일 영향을 피한다.
- 첫 실행 시 macOS가 캘린더·미리알림 자동화 권한을 묻는다. `doctor.sh`가 이를 안내한다.

**회의록 기록 (`notes.py`)**: 반영이 끝나면 회의록 끝(전사록 섹션 앞)에
`## 📅 타임블록` 섹션을 쓴다. 이미 있으면 그 섹션 안에 줄을 합친다. 형식:

```
## 📅 타임블록

- [x] 10/9(목) 14:00-15:00 · 법무 RNR 초안 작성 · 📅
- [x] 10/14(화) 09:00 · CIS 발표 자료 재구성 확인 · ⏰
- [ ] DBA 역할 담당자 확인 (건너뜀)
```

## 6. 알림과 틱 (`notify.py`, `tick.py`)

**알림**: `terminal-notifier`가 있으면 제목, 본문, 클릭 시 실행 명령(`-execute`)을 넘긴다.
없으면 `osascript display notification`으로 폴백하고 본문에 "타임블록 검토 트리거로
열어 주세요"를 덧붙인다. `process_meeting.py`의 기존 `notify()`도 이 모듈로 옮긴다.

**launchd**: `install-launchd.sh`가 `~/Library/LaunchAgents/com.meetingflow.tick.plist`를
설치한다. `StartInterval 300`, `RunAtLoad true`, 표준 출력·오류는 `~/Meetings/.tick.log`.
로그가 1MB를 넘으면 틱 시작 시 비운다. launchd는 잠자는 Mac을 깨우지 않으며, 놓친
틱은 깨어난 직후 한 번 실행된다.

**틱 한 번의 동작** (각 단계는 독립적으로 try로 감싸고 실패는 로그에만 남긴다):

1. **잠금**: `.pending/.tick.lock`에 pid를 기록. 살아 있는 pid가 있으면 즉시 종료.
2. **재알림**: `.pending/*.json` 중 `created_at`이 어제 이전이고 `renotified_on`이 오늘이
   아닌 것이 있으면, 현재 시각이 `MORNING_REMIND_AT` 이후일 때 "미처리 타임블록 후보
   N건" 알림을 한 번 보내고 `renotified_on`을 오늘로 기록한다. `created_at`에서
   `PENDING_EXPIRE_DAYS`가 지난 후보는 `.pending/expired/`로 옮기고 더 알리지 않는다.
3. **브리핑**: icalBuddy `eventsToday`로 오늘 일정을 읽어, `start - now ≤ BRIEF_LEAD_MIN`
   이고 `now - start ≤ 5분`인 이벤트를 고른다. 그중 아래 조건을 만족하고
   `_briefs/YYYY-MM-DD_<정규화 제목>.md`가 없는 이벤트에 대해 `brief.py`를 늦게 불러와
   생성한다.
   - 제목에 `BRIEF_FORCE_TAG`가 있거나,
   - `Meetings/`에 같은 정규화 제목의 회의록이 하나 이상 있다.
   생성 실패는 `.pending/.brief_attempts.json`에 이벤트별 횟수를 기록해 2회까지만
   재시도한다. 성공하면 알림을 보내고, 클릭 시 obsidian 링크로 노트를 연다.
4. **정리**: `done/`, `expired/`에서 30일 지난 파일 삭제.

**가벼움**: `tick.py`는 표준 라이브러리와 `icalBuddy` 서브프로세스만 쓴다. `requests`와
`brief.py`는 3단계에서 실제로 만들 이벤트가 있을 때만 import한다. `boto3`, `truststore`는
틱에서 절대 읽지 않는다.

**제목 정규화** (`notes.py`): 공백 정리와 `sanitize_filename` 적용. 회의록 파일명
`YYYY-MM-DD_HHMM_<제목>.md`에서 제목 부분을 떼어 비교한다. 정확히 일치할 때만 같은
회의로 본다.

## 7. 브리핑 (`brief.py`, `templates/brief.md`)

**역할 분담**: 사실 수집은 코드가, 서술은 Claude가 한다.

**입력 수집**:

1. 같은 정규화 제목의 회의록을 최신순으로 `BRIEF_HISTORY_COUNT`건 읽는다. 각 노트는
   `## 전체 전사록` 앞부분만 쓴다.
2. 각 노트에서 `## 📢 결정 사항` 본문, `## ✅ 액션 아이템`의 `- [ ]` 줄, `## 📅 타임블록`
   섹션을 뽑는다.
3. frontmatter `projects`의 노트를 `PROJECTS_DIR`에서 찾아 앞부분 1,500자씩 읽는다.
4. 강제 대상인데 1에서 아무것도 없으면, 최근 30일 안에 참석자가 둘 이상 겹치는 회의록을
   최신순 3건 쓴다. 그마저 없으면 참석자와 프로젝트 목록만으로 짧은 브리핑을 만든다.

**출력** `Meetings/_briefs/YYYY-MM-DD_<정규화 제목>.md`:

```
---
title: "[11층 몰디브] STR Weekly"
date: 2026-10-14
event_time: 10:00 - 11:00
sources: ["[[2026-10-07_1005_[11층 몰디브] STR Weekly]]", ...]
tags: [brief]
---

## 🧭 한 줄 맥락            (Claude)
## 📌 지난 결정 사항          (코드: 회차별 날짜 + 출처 링크)
## ⏳ 미완료 액션 아이템      (코드: 내 것 먼저, 담당자별, 출처 링크)
## 🔗 관련 프로젝트 근황      (Claude: 링크 + 두세 줄)
## ❓ 이번 회의에서 확인할 것  (Claude: 3개 이내)
```

Claude에는 코드가 만든 사실 목록과 프로젝트 발췌를 넘기고, Claude가 쓰는 세 섹션만
받아 템플릿에 끼운다. 모델은 `claude-sonnet-4-6`.

**회의록과의 연결**: `process_meeting.py`는 요약 단계에서 같은 날짜·정규화 제목의
브리핑이 있으면 프롬프트에 포함하고 "지난 회의의 결정 사항과 미완료 액션 아이템이 이번
회의에서 어떻게 진행되었는지 반영하라"는 지시를 덧붙인다. 회의록 frontmatter에
`brief: "[[브리핑 노트명]]"`을 기록한다.

## 8. 설정 추가 (`config.env.example`)

```
# --- 액션 아이템 → 타임블록 ---
MY_NAMES="Claud,클로드"            # 내 액션 아이템 식별용 이름 목록 (쉼표 구분)
TIMEBLOCK_CALENDAR=""             # 비우면 CALENDAR_NAME에 생성
REMINDER_LIST="미리알림"
WORK_HOURS="10:00-18:00"
MORNING_REMIND_AT="09:00"
PENDING_EXPIRE_DAYS="7"
REVIEW_PORT="47321"
OBSIDIAN_VAULT_NAME="_obsidian"   # obsidian:// 링크용 vault 이름

# --- 회의 전 브리핑 ---
BRIEF_LEAD_MIN="15"
BRIEF_HISTORY_COUNT="3"
BRIEF_FORCE_TAG="[brief]"
```

모든 값은 비어 있으면 위 기본값을 쓴다 (`MY_NAMES`만 필수. 비어 있으면 추출 단계를
건너뛰고 로그에 안내를 남긴다).

## 9. 코드 배치

```
scripts/
  process_meeting.py       # 기존 진입점. 끝에 추출 단계 호출, 브리핑 포함 추가
  tick.py                  # launchd 진입점 (표준 라이브러리만)
  review-open.sh           # 서버 기동 + 브라우저 열기 (알림 클릭·트리거 공용)
  review-timeblocks.sh     # Raycast / Quick Action 용 래퍼 (review-open.sh 호출)
  install-launchd.sh       # plist 설치/갱신
  meetingflow/
    __init__.py
    config.py              # load_config 이동 + 기본값
    notify.py              # terminal-notifier / osascript
    calendar_io.py         # icalBuddy 읽기·파싱, AppleScript 캘린더·미리알림 쓰기
    notes.py               # 회의록 파싱, 제목 정규화, 타임블록 섹션 기록
    actions.py             # 액션 아이템 추출 (Claude → JSON)
    pending.py             # .pending 파일 읽기/쓰기/상태 전이
    slots.py               # 빈 시간 제안
    review_server.py       # HTTP 서버 + 단일 HTML
    brief.py               # 브리핑 생성
templates/brief.md
tests/                     # pytest
```

기존 변경:

- `process_meeting.py`: `load_config`, `notify`, `parse_icalbuddy_events`를 패키지로
  옮기고 import로 대체. 나머지 함수는 유지.
- `setup.sh`: `terminal-notifier` 설치, `pytest` 설치, `install-launchd.sh` 실행 추가.
- `doctor.sh`: launchd 에이전트 로드 여부, `terminal-notifier` 존재, 캘린더·미리알림
  자동화 권한 안내 추가.
- `install-quick-actions.sh`: `타임블록 검토` 항목 추가.
- `README.md`: 새 기능 두 축과 설정 항목 문서화.

## 10. 오류 처리 원칙

회의록은 반드시 저장되고, 나머지는 실패해도 다음 기회에 다시 시도한다.

| 상황 | 처리 |
|---|---|
| 액션 아이템 추출 실패 | 경고 알림, 회의록은 정상 저장, 후보 없음 |
| JSON 파싱 실패 | "JSON만 출력" 덧붙여 1회 재시도 |
| 캘린더/미리알림 생성 실패 | 항목 단위 격리. 화면에 오류 표시, `.pending`에 유지 |
| 포트 충돌 | `/health`로 확인 후 다음 포트, `.server.json`에 기록 |
| icalBuddy 실패 (틱) | 브리핑 단계 건너뜀, 로그 |
| 브리핑 생성 실패 | 파일 미생성 → 다음 틱 재시도, 이벤트별 2회 한도 |
| 타임블록 섹션 중복 | 기존 섹션에 줄 합침 |
| 틱 중복 실행 | pid 잠금으로 즉시 종료 |
| 서버 유휴 | 10분 무요청 시 자동 종료 |

## 11. 테스트

`pytest`를 `.venv`에 추가하고 `tests/`에 둔다. 외부 시스템(캘린더, Claude, icalBuddy)은
호출하지 않는다.

- `test_notes.py`: 제목 정규화, 섹션 추출(결정 사항·액션 아이템·타임블록), 타임블록
  섹션 기록의 멱등성. 실제 회의록을 본뜬 fixture 사용.
- `test_slots.py`: 기한 전날 역순 탐색, 주말 건너뛰기, 같은 세션 후보 간 비겹침,
  빈 구간 없을 때 `conflict`, `due` 없음, `due`가 내일 이하인 경우.
- `test_pending.py`: 생성, 재알림 기록, 만료 이동, 완료 이동, 부분 반영(`applied_at`).
- `test_actions.py`: mock Claude 응답으로 파싱, `is_mine` 판정(대소문자, 공통), 다음 차수
  날짜 반영, 재시도, 두 번째 실패 시 후보 미생성.
- `test_calendar_io.py`: icalBuddy 출력 파싱(기존 테스트 케이스 이전), AppleScript 문자열
  생성과 이스케이프, 날짜 설정 방식.
- `test_brief.py`: 입력 수집(같은 제목 N건, 참석자 겹침 폴백), 코드 섹션 생성, Claude
  응답을 템플릿에 끼우는 조립.

수동 점검:

- `python3 scripts/tick.py --dry-run`: 지금 틱이 할 일을 출력만 한다.
- `python3 -m meetingflow.review_server --demo`: fixture 후보로 화면을 띄운다.
- `python3 -m meetingflow.calendar_io --smoke`: 테스트 캘린더에 이벤트 하나를 만들고
  지운다.

구현은 TDD로 진행한다.

## 12. 의존성 추가

- brew: `terminal-notifier`
- pip (`.venv`): `pytest`
- macOS 권한: 캘린더·미리알림 자동화(첫 실행 시 프롬프트), launchd 에이전트
