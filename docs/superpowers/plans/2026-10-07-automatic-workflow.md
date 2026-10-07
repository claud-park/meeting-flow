# Meeting Flow 자동 워크플로 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 회의록이 완성되면 내 액션 아이템을 타임블록·미리알림 후보로 만들어 로컬 팝업에서 승인한 것만 캘린더에 넣고, 반복 회의 15분 전에 브리핑 노트를 자동 생성한다.

**Architecture:** 기존 `process_meeting.py` 끝에 액션 아이템 추출 단계를 붙여 `~/Meetings/.pending/*.json`에 후보를 떨어뜨린다. 알림 클릭이 `review-open.sh`를 실행해 필요할 때만 `review_server.py`(표준 라이브러리 HTTP 서버)를 띄우고, 승인된 항목을 AppleScript로 macOS 캘린더·미리알림에 쓴다. launchd가 5분마다 `tick.py`를 실행해 재알림, 브리핑 생성, 정리를 맡는다. 공용 로직은 `scripts/meetingflow/` 패키지로 모은다.

**Tech Stack:** Python 3.14 (`.venv`), 표준 라이브러리 `http.server`·`json`·`subprocess`, `requests`(Claude API), `icalBuddy`(캘린더 읽기), `osascript`(캘린더·미리알림 쓰기), `terminal-notifier`(클릭 가능한 알림), launchd, pytest.

**Spec:** `docs/superpowers/specs/2026-10-07-automatic-workflow-design.md`

## Global Constraints

- 모든 python 실행은 `.venv/bin/python3`로 한다. 테스트는 `.venv/bin/python3 -m pytest tests -q`.
- `scripts/tick.py`와 그것이 import하는 모듈(`config`, `notify`, `pending`, `calendar_io`, `notes`)은 표준 라이브러리만 사용한다. `requests`는 `actions.py`, `brief.py` 안에서만 import한다. `boto3`, `truststore`는 `process_meeting.py`에만 남는다.
- 회의록은 반드시 저장된다. 새로 추가하는 단계의 실패는 `process_meeting.py`의 예외로 전파되지 않는다.
- 서버는 `127.0.0.1`에만 바인딩한다. 기본 포트는 `REVIEW_PORT="47321"`.
- 설정 기본값(스펙 8절): `MY_NAMES="Claud,클로드"`, `TIMEBLOCK_CALENDAR=""`, `REMINDER_LIST="미리알림"`, `WORK_HOURS="10:00-18:00"`, `MORNING_REMIND_AT="09:00"`, `PENDING_EXPIRE_DAYS="7"`, `REVIEW_PORT="47321"`, `OBSIDIAN_VAULT_NAME="_obsidian"`, `BRIEF_LEAD_MIN="15"`, `BRIEF_HISTORY_COUNT="3"`, `BRIEF_FORCE_TAG="[brief]"`.
- 파일 명명: 후보 `~/Meetings/.pending/<회의록 stem>.json`, 완료 `.pending/done/`, 만료 `.pending/expired/`, 브리핑 `<OBSIDIAN_DIR>/_briefs/YYYY-MM-DD_<정규화 제목>.md`.
- 회의록 기록 섹션 제목은 정확히 `## 📅 타임블록`. 줄 형식은 `- [x] 10/9(목) 14:00-15:00 · 제목 · 📅`, `- [x] 10/14(화) 09:00 · 제목 · ⏰`, `- [ ] 제목 (건너뜀)`.
- Claude 모델은 `claude-sonnet-4-6`, 엔드포인트와 헤더는 기존 `summarize()`와 동일.
- 코드 주석·로그·커밋 메시지는 저장소 관례대로 한국어. 로그 접두어는 `[actions]`, `[pending]`, `[review]`, `[tick]`, `[brief]`, `[calendar]`.
- 커밋은 태스크마다 한 번. 작업 트리에 이미 있는 `scripts/process_meeting.py`·`test_upload.py`의 truststore 변경은 이 계획과 무관하므로 Task 1에서 먼저 별도 커밋한다.

## Review Focus

스펙이 암시하지만 어느 태스크의 테스트도 직접 다루지 않는 입력 중, 실제 사용자를 가장 먼저 물 것들. 각 줄의 테스트는 해당 태스크에 추가되어 있다.

1. **회의 제목에 대괄호·슬래시·콜론이 섞인 경우** (`[11층 몰디브] STR Weekly`, `CoE 논의 (정기미팅)`): 정규화 제목 비교와 파일명·obsidian URL 인코딩이 일치해야 한다. → Task 4 `test_normalize_title_matches_filename_stem`, `test_obsidian_url_encodes_brackets`.
2. **AppleScript 주입**: 액션 아이템 텍스트에 `"`, `\`, 줄바꿈이 들어 있어도 스크립트가 깨지지 않아야 한다. → Task 3 `test_applescript_quote_escapes`.
3. **기한이 오늘 또는 과거인 항목**: 제안 시간이 과거가 되면 안 되고, 화면에서는 체크 해제와 "기한 지남" 표시가 되어야 한다. → Task 8 `test_due_today_uses_today_remaining_hours`, `test_due_past_marks_overdue`.
4. **같은 회의가 하루에 두 번 녹음된 경우** (같은 stem 충돌 없음: stem에 HHMM 포함) 및 **`.pending`에 같은 stem이 이미 있는 경우**: 덮어쓰지 않고 `-2` 접미사로 저장한다. → Task 5 `test_new_pending_does_not_overwrite`.
5. **잠에서 깬 직후 틱이 늦게 도는 경우**: 회의 시작 후 5분 이내면 브리핑을 만들고, 그 뒤면 건너뛴다. 하루 안에 같은 이벤트가 두 번 생성되지 않아야 한다. → Task 11 `test_brief_window_allows_5min_late`, `test_brief_not_regenerated_if_exists`.

---

### Task 1: 패키지 골격, 설정 모듈, pytest

**Files:**
- Create: `scripts/meetingflow/__init__.py`
- Create: `scripts/meetingflow/config.py`
- Create: `tests/conftest.py`
- Create: `tests/test_config.py`
- Create: `pytest.ini`
- Modify: `config.env.example` (설정 두 묶음 추가)
- Modify: `.gitignore` (`.pytest_cache/` 추가)

**Interfaces:**
- Produces:
  - `config.REPO_DIR: Path`, `config.SCRIPTS_DIR: Path`, `config.TEMPLATES_DIR: Path`, `config.CONFIG_PATH: Path`
  - `config.DEFAULTS: dict[str, str]`
  - `config.load_config(path: Path | None = None) -> dict[str, str]` (DEFAULTS 위에 파일 값을 덮고 `$HOME` 치환)
  - `config.meetings_dir(cfg) -> Path`, `config.obsidian_dir(cfg) -> Path`, `config.briefs_dir(cfg) -> Path` (`obsidian_dir / "_briefs"`)
  - `config.my_names(cfg) -> list[str]`
  - `config.parse_hhmm(s: str) -> datetime.time`
  - `config.work_hours(cfg) -> tuple[time, time]`
  - `config.int_cfg(cfg, key) -> int`

- [ ] **Step 1: 작업 트리의 기존 변경을 먼저 커밋한다**

```bash
git add scripts/process_meeting.py test_upload.py
git commit -m "회사 TLS 검사 장비 대응을 위해 truststore 주입, end_ts 상태값 사용"
```

- [ ] **Step 2: pytest 설치와 설정**

```bash
.venv/bin/pip install --quiet pytest
```

`pytest.ini`:

```ini
[pytest]
testpaths = tests
pythonpath = scripts
```

`.gitignore`에 한 줄 추가:

```
.pytest_cache/
```

- [ ] **Step 3: 실패하는 테스트 작성**

`tests/conftest.py`:

```python
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


@pytest.fixture
def cfg(tmp_path):
    """테스트용 설정: 모든 경로를 tmp_path 아래로 돌린다."""
    from meetingflow import config
    c = dict(config.DEFAULTS)
    c["MEETINGS_DIR"] = str(tmp_path / "Meetings")
    c["OBSIDIAN_DIR"] = str(tmp_path / "vault" / "Meetings")
    c["PROJECTS_DIR"] = str(tmp_path / "vault" / "Projects")
    c["CALENDAR_NAME"] = "work@example.com"
    c["ANTHROPIC_API_KEY"] = "test-key"
    (tmp_path / "Meetings").mkdir()
    (tmp_path / "vault" / "Meetings").mkdir(parents=True)
    (tmp_path / "vault" / "Projects").mkdir(parents=True)
    return c
```

`tests/test_config.py`:

```python
from datetime import time
from pathlib import Path

from meetingflow import config


def test_defaults_applied_when_key_missing(tmp_path):
    p = tmp_path / "config.env"
    p.write_text('MEETINGS_DIR="$HOME/M"\n', encoding="utf-8")
    cfg = config.load_config(p)
    assert cfg["REVIEW_PORT"] == "47321"
    assert cfg["MY_NAMES"] == "Claud,클로드"
    assert cfg["MEETINGS_DIR"] == str(Path.home() / "M")


def test_file_value_overrides_default(tmp_path):
    p = tmp_path / "config.env"
    p.write_text('REVIEW_PORT="50000"  # 주석\nWORK_HOURS=09:00-17:00\n', encoding="utf-8")
    cfg = config.load_config(p)
    assert cfg["REVIEW_PORT"] == "50000"
    assert config.work_hours(cfg) == (time(9, 0), time(17, 0))


def test_empty_value_falls_back_to_default(tmp_path):
    p = tmp_path / "config.env"
    p.write_text('TIMEBLOCK_CALENDAR=""\nCALENDAR_NAME="me@x.com"\n', encoding="utf-8")
    cfg = config.load_config(p)
    assert cfg["TIMEBLOCK_CALENDAR"] == ""
    assert config.timeblock_calendar(cfg) == "me@x.com"


def test_my_names_split_and_strip():
    assert config.my_names({"MY_NAMES": " Claud, 클로드 ,"}) == ["Claud", "클로드"]
    assert config.my_names({"MY_NAMES": ""}) == []


def test_briefs_dir_under_obsidian(cfg):
    assert config.briefs_dir(cfg) == Path(cfg["OBSIDIAN_DIR"]) / "_briefs"


def test_parse_hhmm():
    assert config.parse_hhmm("9:05") == time(9, 5)
    assert config.parse_hhmm("18:00") == time(18, 0)
```

- [ ] **Step 4: 실패 확인**

Run: `.venv/bin/python3 -m pytest tests/test_config.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'meetingflow'`

- [ ] **Step 5: 구현**

`scripts/meetingflow/__init__.py`: 빈 파일 (docstring 한 줄 `"""Meeting Flow 공용 모듈"""`).

`scripts/meetingflow/config.py`:

```python
"""설정 로드와 기본값. 표준 라이브러리만 사용한다 (tick.py가 import)."""
import re
from datetime import time
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = SCRIPTS_DIR.parent
TEMPLATES_DIR = REPO_DIR / "templates"
CONFIG_PATH = REPO_DIR / "config.env"

DEFAULTS = {
    "MEETINGS_DIR": str(Path.home() / "Meetings"),
    "OBSIDIAN_DIR": "",
    "PROJECTS_DIR": "",
    "CALENDAR_NAME": "",
    # 액션 아이템 → 타임블록
    "MY_NAMES": "Claud,클로드",
    "TIMEBLOCK_CALENDAR": "",
    "REMINDER_LIST": "미리알림",
    "WORK_HOURS": "10:00-18:00",
    "MORNING_REMIND_AT": "09:00",
    "PENDING_EXPIRE_DAYS": "7",
    "REVIEW_PORT": "47321",
    "OBSIDIAN_VAULT_NAME": "_obsidian",
    # 브리핑
    "BRIEF_LEAD_MIN": "15",
    "BRIEF_HISTORY_COUNT": "3",
    "BRIEF_FORCE_TAG": "[brief]",
}


def _parse_line(line: str):
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        return None
    key, _, val = line.partition("=")
    val = val.strip()
    m = re.match(r'^"([^"]*)"|^\'([^\']*)\'', val)
    if m:
        val = m.group(1) if m.group(1) is not None else m.group(2)
    else:
        val = val.split("#", 1)[0].strip()
    val = val.replace("$HOME", str(Path.home()))
    return key.strip(), val


def load_config(path: Path | None = None) -> dict:
    """config.env를 읽어 DEFAULTS 위에 덮는다. 파일이 없으면 DEFAULTS만 반환."""
    cfg = dict(DEFAULTS)
    path = Path(path) if path else CONFIG_PATH
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            parsed = _parse_line(line)
            if parsed:
                cfg[parsed[0]] = parsed[1]
    return cfg


def meetings_dir(cfg: dict) -> Path:
    return Path(cfg.get("MEETINGS_DIR") or DEFAULTS["MEETINGS_DIR"])


def obsidian_dir(cfg: dict) -> Path:
    return Path(cfg["OBSIDIAN_DIR"])


def briefs_dir(cfg: dict) -> Path:
    return obsidian_dir(cfg) / "_briefs"


def my_names(cfg: dict) -> list:
    return [n.strip() for n in cfg.get("MY_NAMES", "").split(",") if n.strip()]


def timeblock_calendar(cfg: dict) -> str:
    return cfg.get("TIMEBLOCK_CALENDAR") or cfg.get("CALENDAR_NAME", "")


def parse_hhmm(s: str) -> time:
    h, m = s.strip().split(":")
    return time(int(h), int(m))


def work_hours(cfg: dict) -> tuple:
    a, _, b = (cfg.get("WORK_HOURS") or DEFAULTS["WORK_HOURS"]).partition("-")
    return parse_hhmm(a), parse_hhmm(b)


def int_cfg(cfg: dict, key: str) -> int:
    return int(cfg.get(key) or DEFAULTS[key])
```

- [ ] **Step 6: 통과 확인**

Run: `.venv/bin/python3 -m pytest tests/test_config.py -q`
Expected: 6 passed

- [ ] **Step 7: config.env.example에 설정 추가**

`# --- Claude API (요약용) ---` 블록 바로 앞에 삽입:

```
# --- 액션 아이템 → 타임블록 ---
# 회의록 액션 아이템에서 "내 것"을 고르기 위한 이름 목록 (쉼표 구분, 대소문자 무시)
MY_NAMES="Claud,클로드"
# 타임블록을 만들 캘린더 이름 (비우면 CALENDAR_NAME에 생성)
TIMEBLOCK_CALENDAR=""
# 미리알림을 넣을 목록 이름
REMINDER_LIST="미리알림"
# 타임블록을 제안할 근무 시간대
WORK_HOURS="10:00-18:00"
# 미처리 후보 재알림 시각 (하루 한 번)
MORNING_REMIND_AT="09:00"
# 이 일수가 지난 미처리 후보는 만료 처리
PENDING_EXPIRE_DAYS="7"
# 검토 팝업 로컬 포트 (127.0.0.1 전용)
REVIEW_PORT="47321"
# obsidian:// 링크용 vault 이름 (Obsidian 설정의 vault 폴더명)
OBSIDIAN_VAULT_NAME="_obsidian"

# --- 회의 전 브리핑 ---
# 회의 시작 몇 분 전에 브리핑을 만들지
BRIEF_LEAD_MIN="15"
# 브리핑에 참고할 지난 회의록 수
BRIEF_HISTORY_COUNT="3"
# 지난 회의록이 없어도 브리핑을 강제할 캘린더 제목 표식
BRIEF_FORCE_TAG="[brief]"

```

- [ ] **Step 8: 커밋**

```bash
git add scripts/meetingflow pytest.ini .gitignore tests/conftest.py tests/test_config.py config.env.example
git commit -m "meetingflow 패키지 골격과 설정 모듈 추가, pytest 도입"
```

---

### Task 2: 알림 모듈 (terminal-notifier / osascript 폴백)

**Files:**
- Create: `scripts/meetingflow/notify.py`
- Create: `tests/test_notify.py`
- Modify: `scripts/process_meeting.py:52-62` (`notify` 함수를 패키지 import로 대체)

**Interfaces:**
- Produces:
  - `notify.has_terminal_notifier() -> bool`
  - `notify.build_command(title, message, execute=None, open_url=None, group=None) -> list[str]` (terminal-notifier 인자 목록)
  - `notify.notify(title: str, message: str, execute: str | None = None, open_url: str | None = None, group: str | None = None, run=subprocess.run) -> None`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_notify.py`:

```python
from meetingflow import notify


def test_build_command_with_execute():
    cmd = notify.build_command("제목", "본문", execute="/x/review-open.sh", group="meetingflow")
    assert cmd[0] == "terminal-notifier"
    assert cmd[cmd.index("-title") + 1] == "제목"
    assert cmd[cmd.index("-message") + 1] == "본문"
    assert cmd[cmd.index("-execute") + 1] == "/x/review-open.sh"
    assert cmd[cmd.index("-group") + 1] == "meetingflow"
    assert "-open" not in cmd


def test_build_command_with_open_url():
    cmd = notify.build_command("t", "m", open_url="obsidian://open?vault=v&file=f")
    assert cmd[cmd.index("-open") + 1] == "obsidian://open?vault=v&file=f"


def test_notify_falls_back_to_osascript(monkeypatch):
    calls = []
    monkeypatch.setattr(notify, "has_terminal_notifier", lambda: False)
    notify.notify("t", "m", execute="/x.sh", run=lambda cmd, **kw: calls.append(cmd))
    assert calls and calls[0][0] == "osascript"
    assert "타임블록 검토" in calls[0][-1]  # 클릭 불가 안내 덧붙임


def test_notify_osascript_without_execute_has_no_hint(monkeypatch):
    calls = []
    monkeypatch.setattr(notify, "has_terminal_notifier", lambda: False)
    notify.notify("t", "m", run=lambda cmd, **kw: calls.append(cmd))
    assert "타임블록 검토" not in calls[0][-1]


def test_notify_uses_terminal_notifier_when_present(monkeypatch):
    calls = []
    monkeypatch.setattr(notify, "has_terminal_notifier", lambda: True)
    notify.notify("t", "m", execute="/x.sh", run=lambda cmd, **kw: calls.append(cmd))
    assert calls[0][0] == "terminal-notifier"


def test_notify_never_raises(monkeypatch):
    monkeypatch.setattr(notify, "has_terminal_notifier", lambda: True)

    def boom(cmd, **kw):
        raise OSError("no binary")
    notify.notify("t", "m", run=boom)  # 예외가 밖으로 나오면 테스트 실패
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python3 -m pytest tests/test_notify.py -q`
Expected: FAIL, `cannot import name 'notify'` 또는 ModuleNotFoundError

- [ ] **Step 3: 구현**

`scripts/meetingflow/notify.py`:

```python
"""macOS 알림. terminal-notifier가 있으면 클릭 동작을 붙이고, 없으면 osascript로 폴백."""
import shutil
import subprocess


def has_terminal_notifier() -> bool:
    return shutil.which("terminal-notifier") is not None


def build_command(title: str, message: str, execute: str | None = None,
                  open_url: str | None = None, group: str | None = None) -> list:
    cmd = ["terminal-notifier", "-title", title, "-message", message]
    if execute:
        cmd += ["-execute", execute]
    if open_url:
        cmd += ["-open", open_url]
    if group:
        cmd += ["-group", group]
    return cmd


def _osascript_command(title: str, message: str, clickable: bool) -> list:
    if clickable:
        message = f"{message} (타임블록 검토 트리거로 열어 주세요)"
    safe_msg = message.replace("\\", "\\\\").replace('"', '\\"')
    safe_title = title.replace("\\", "\\\\").replace('"', '\\"')
    return ["osascript", "-e",
            f'display notification "{safe_msg}" with title "{safe_title}"']


def notify(title: str, message: str, execute: str | None = None,
           open_url: str | None = None, group: str | None = None,
           run=subprocess.run) -> None:
    """알림을 보낸다. 어떤 경우에도 예외를 밖으로 내지 않는다."""
    try:
        if has_terminal_notifier():
            cmd = build_command(title, message, execute, open_url, group)
        else:
            cmd = _osascript_command(title, message, clickable=bool(execute or open_url))
        run(cmd, check=False, capture_output=True, timeout=10)
    except Exception as e:  # noqa: BLE001
        print(f"[notify] 알림 실패: {e}")
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python3 -m pytest tests/test_notify.py -q`
Expected: 6 passed

- [ ] **Step 5: process_meeting.py가 패키지 notify를 쓰도록 교체**

`scripts/process_meeting.py`의 `def notify(...)` 함수 전체(`# ---------- 설정 로드 ----------` 아래 `def notify` 블록, 현재 52~62행)를 삭제하고, import 구역의 `import requests` 아래에 추가:

```python
sys.path.insert(0, str(Path(__file__).resolve().parent))  # scripts/ 를 모듈 경로에
from meetingflow.notify import notify  # noqa: E402
```

`SCRIPT_DIR` 정의가 import보다 아래에 있으므로 `Path(__file__).resolve().parent`를 직접 쓴다. 기존 `notify("회의록 완성 ✅", ...)`, `notify("회의록 생성 실패 ⚠️", ...)` 호출은 시그니처가 호환되므로 그대로 둔다.

- [ ] **Step 6: 전체 테스트와 import 확인**

Run: `.venv/bin/python3 -m pytest -q && .venv/bin/python3 -c "import sys; sys.path.insert(0,'scripts'); import process_meeting; print('ok')"`
Expected: 모든 테스트 통과, `ok` 출력

- [ ] **Step 7: 커밋**

```bash
git add scripts/meetingflow/notify.py tests/test_notify.py scripts/process_meeting.py
git commit -m "알림 모듈 분리: terminal-notifier 클릭 동작 지원, osascript 폴백"
```

---

### Task 3: 캘린더 읽기·쓰기 모듈

**Files:**
- Create: `scripts/meetingflow/calendar_io.py`
- Create: `tests/test_calendar_io.py`
- Modify: `scripts/process_meeting.py` (`parse_icalbuddy_events`, `clean_attendee`를 패키지 import로 대체)

**Interfaces:**
- Produces:
  - `calendar_io.parse_icalbuddy_events(out: str, today: date | None = None) -> list[dict]` (각 dict: `title`, `attendees`, `start_ts`, `end_ts`; 기존 함수 이전)
  - `calendar_io.clean_attendee(raw: str) -> str` (기존 함수 이전)
  - `calendar_io.run_icalbuddy(cfg, args: list[str], run=subprocess.run) -> str`
  - `calendar_io.events_today(cfg, run=...) -> list[dict]`
  - `calendar_io.events_between(cfg, start: date, end_inclusive: date, run=...) -> list[dict]`
  - `calendar_io.find_next_event(cfg, title: str, normalize, now: datetime, days: int = 30, run=...) -> dict | None`
  - `calendar_io.applescript_quote(s: str) -> str` (양쪽 따옴표 포함 AppleScript 문자열 리터럴 반환)
  - `calendar_io.applescript_date_expr(dt: datetime) -> str` (`current date`를 기준으로 연·월·일·시·분을 설정하는 식)
  - `calendar_io.build_calendar_event_script(calendar: str, summary: str, start: datetime, end: datetime, description: str) -> str`
  - `calendar_io.build_reminder_script(list_name: str, name: str, due: datetime, body: str) -> str`
  - `calendar_io.CalendarError(Exception)`
  - `calendar_io.run_applescript(script: str, run=subprocess.run) -> str` (실패 시 `CalendarError`)
  - `calendar_io.create_calendar_event(cfg, summary, start, end, description, run=...) -> None`
  - `calendar_io.create_reminder(cfg, name, due, body, run=...) -> None`
  - CLI: `python3 -m meetingflow.calendar_io --smoke` (테스트 이벤트 생성 후 삭제)

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_calendar_io.py`:

```python
from datetime import date, datetime

from meetingflow import calendar_io as cal

SAMPLE = """[11층 몰디브] STR Weekly
    2026-10-07 at 10:00 - 11:00
    attendees: mailto:a.kim@x.com, mailto:room-1@resource.calendar.google.com
회의
    2026-10-07 at 15:00 - 15:30
"""


def test_parse_events_basic():
    evs = cal.parse_icalbuddy_events(SAMPLE)
    assert [e["title"] for e in evs] == ["[11층 몰디브] STR Weekly", "회의"]
    assert evs[0]["attendees"] == ["a.kim"]
    s = datetime.fromtimestamp(evs[0]["start_ts"])
    assert (s.hour, s.minute) == (10, 0)


def test_parse_time_only_line_uses_today():
    out = "회의\n    11:45 - 12:30\n"
    evs = cal.parse_icalbuddy_events(out, today=date(2026, 10, 7))
    assert datetime.fromtimestamp(evs[0]["start_ts"]).date() == date(2026, 10, 7)


def test_clean_attendee():
    assert cal.clean_attendee("mailto:jane.doe@company.com") == "jane.doe"
    assert cal.clean_attendee("x@resource.calendar.google.com") == ""


def test_events_between_passes_date_range(cfg):
    seen = []

    def fake_run(cmd, **kw):
        seen.append(cmd)
        class R: stdout = SAMPLE
        return R()
    cal.events_between(cfg, date(2026, 10, 7), date(2026, 10, 13), run=fake_run)
    assert "eventsFrom:2026-10-07" in seen[0]
    assert "to:2026-10-13" in seen[0]
    assert cfg["CALENDAR_NAME"] in seen[0]


def test_find_next_event_by_normalized_title(cfg):
    def fake_run(cmd, **kw):
        class R:
            stdout = ("[11층 몰디브] STR Weekly\n    2026-10-14 at 10:00 - 11:00\n"
                      "[11층 몰디브]  STR Weekly\n    2026-10-21 at 10:00 - 11:00\n")
        return R()
    now = datetime(2026, 10, 7, 11, 0)
    ev = cal.find_next_event(cfg, "[11층 몰디브] STR Weekly",
                             normalize=lambda s: " ".join(s.split()), now=now, run=fake_run)
    assert datetime.fromtimestamp(ev["start_ts"]).date() == date(2026, 10, 14)


def test_find_next_event_none_when_no_match(cfg):
    def fake_run(cmd, **kw):
        class R: stdout = "다른 회의\n    2026-10-14 at 10:00 - 11:00\n"
        return R()
    assert cal.find_next_event(cfg, "STR Weekly", normalize=str.strip,
                               now=datetime(2026, 10, 7), run=fake_run) is None


def test_applescript_quote_escapes():
    q = cal.applescript_quote('그는 "A\\B" 라고\n말했다')
    assert q.startswith('"') and q.endswith('"')
    assert '\\"A\\\\B\\"' in q
    assert "\n" not in q  # 줄바꿈은 공백으로


def test_applescript_date_expr_sets_components():
    expr = cal.applescript_date_expr(datetime(2026, 10, 9, 14, 30))
    assert "set year of" in expr and "2026" in expr
    assert "set month of" in expr and "10" in expr
    assert "set day of" in expr and "9" in expr
    assert "set hours of" in expr and "14" in expr
    assert "set minutes of" in expr and "30" in expr
    assert "set seconds of" in expr


def test_build_calendar_event_script_targets_calendar():
    s = cal.build_calendar_event_script(
        "work@x.com", "법무 RNR 초안", datetime(2026, 10, 9, 14, 0),
        datetime(2026, 10, 9, 15, 0), "회의: STR Weekly\nobsidian://open?vault=v&file=f")
    assert 'tell application "Calendar"' in s
    assert 'calendar "work@x.com"' in s
    assert 'summary:"법무 RNR 초안"' in s
    assert "make new event" in s


def test_build_reminder_script():
    s = cal.build_reminder_script("미리알림", "확인하기", datetime(2026, 10, 14, 9, 0), "회의: X")
    assert 'tell application "Reminders"' in s
    assert 'list "미리알림"' in s
    assert "make new reminder" in s
    assert "due date" in s


def test_run_applescript_raises_on_failure():
    def fake_run(cmd, **kw):
        class R: returncode = 1; stdout = ""; stderr = "execution error: 권한 없음 (-1743)"
        return R()
    try:
        cal.run_applescript("tell me", run=fake_run)
    except cal.CalendarError as e:
        assert "-1743" in str(e)
    else:
        raise AssertionError("CalendarError expected")
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python3 -m pytest tests/test_calendar_io.py -q`
Expected: FAIL, ModuleNotFoundError

- [ ] **Step 3: 구현**

`scripts/meetingflow/calendar_io.py`:

```python
"""icalBuddy로 캘린더를 읽고, AppleScript로 캘린더·미리알림에 쓴다. 표준 라이브러리만 사용."""
import re
import subprocess
import sys
from datetime import date, datetime, timedelta

from . import config

ICALBUDDY_BASE = ["icalBuddy", "-npn", "-nc", "-b", "", "-nrd",
                  "-iep", "title,datetime,attendees",
                  "-df", "%Y-%m-%d", "-tf", "%H:%M"]


# ---------- 읽기 ----------

def clean_attendee(raw: str) -> str:
    """'mailto:jane.doe@company.com' → 'jane.doe'. 회의실 리소스 계정은 제외."""
    a = raw.strip().replace("mailto:", "")
    if not a:
        return ""
    if "resource.calendar.google.com" in a:
        return ""
    if "@" in a:
        a = a.split("@", 1)[0]
    return a


def parse_icalbuddy_events(out: str, today: date | None = None) -> list:
    """icalBuddy 출력을 이벤트 dict 리스트로 파싱 (title, attendees, start_ts, end_ts)."""
    events = []
    cur = None
    time_re = re.compile(r"(\d{4}-\d{2}-\d{2}).*?(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})")
    rel_re = re.compile(r"^(today|tomorrow|yesterday)\b(.*?)(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})", re.I)
    base_day = today or date.today()
    today_s = base_day.strftime("%Y-%m-%d")

    for line in out.splitlines():
        if not line.strip():
            continue
        if not line.startswith((" ", "\t")):
            cur = {"title": line.strip(), "attendees": [], "start_ts": None, "end_ts": None}
            events.append(cur)
            continue
        if cur is None:
            continue
        stripped = line.strip()
        if stripped.lower().startswith("attendees:"):
            raw = stripped.split(":", 1)[1]
            cur["attendees"] = [a for a in (clean_attendee(x) for x in raw.split(",")) if a]
            continue
        m = time_re.search(stripped)
        if m:
            date_s, t1, t2 = m.groups()
        else:
            rm = rel_re.search(stripped)
            if rm:
                rel, _, t1, t2 = rm.groups()
                d = base_day
                if rel.lower() == "tomorrow":
                    d += timedelta(days=1)
                elif rel.lower() == "yesterday":
                    d -= timedelta(days=1)
                date_s = d.strftime("%Y-%m-%d")
            else:
                tm = re.match(r"^(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})$", stripped)
                if not tm:
                    continue
                t1, t2 = tm.groups()
                date_s = today_s
        try:
            s = datetime.strptime(f"{date_s} {t1}", "%Y-%m-%d %H:%M")
            e = datetime.strptime(f"{date_s} {t2}", "%Y-%m-%d %H:%M")
            cur["start_ts"] = int(s.timestamp())
            cur["end_ts"] = int(e.timestamp())
        except ValueError:
            pass
    return events


def run_icalbuddy(cfg: dict, args: list, run=subprocess.run) -> str:
    cmd = ICALBUDDY_BASE + ["-ic", cfg["CALENDAR_NAME"]] + args
    try:
        return run(cmd, capture_output=True, text=True, timeout=30).stdout
    except Exception as e:  # noqa: BLE001
        print(f"[calendar] icalBuddy 실패: {e}")
        return ""


def events_today(cfg: dict, run=subprocess.run) -> list:
    return parse_icalbuddy_events(run_icalbuddy(cfg, ["eventsToday"], run=run))


def events_between(cfg: dict, start: date, end_inclusive: date, run=subprocess.run) -> list:
    out = run_icalbuddy(cfg, [f"eventsFrom:{start:%Y-%m-%d}", f"to:{end_inclusive:%Y-%m-%d}"], run=run)
    return parse_icalbuddy_events(out, today=start)


def find_next_event(cfg: dict, title: str, normalize, now: datetime,
                    days: int = 30, run=subprocess.run) -> dict | None:
    """now 이후 days일 안에서 정규화 제목이 같은 가장 가까운 이벤트."""
    target = normalize(title)
    evs = events_between(cfg, now.date(), now.date() + timedelta(days=days), run=run)
    future = [e for e in evs if e["start_ts"] and e["start_ts"] > int(now.timestamp())
              and normalize(e["title"]) == target]
    return min(future, key=lambda e: e["start_ts"]) if future else None


# ---------- 쓰기 (AppleScript) ----------

class CalendarError(Exception):
    pass


def applescript_quote(s: str) -> str:
    s = s.replace("\r", " ").replace("\n", " ")
    s = s.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'


def applescript_date_expr(dt: datetime) -> str:
    """로케일 영향을 받지 않도록 current date의 각 성분을 직접 설정하는 식.
    변수명 theDate를 쓰며, 호출 측은 이 블록 뒤에서 theDate를 사용한다."""
    return "\n".join([
        "set theDate to current date",
        f"set year of theDate to {dt.year}",
        f"set month of theDate to {dt.month}",
        f"set day of theDate to {dt.day}",
        f"set hours of theDate to {dt.hour}",
        f"set minutes of theDate to {dt.minute}",
        "set seconds of theDate to 0",
    ])


def build_calendar_event_script(calendar: str, summary: str, start: datetime,
                                end: datetime, description: str) -> str:
    start_expr = applescript_date_expr(start).replace("theDate", "startDate")
    end_expr = applescript_date_expr(end).replace("theDate", "endDate")
    return f"""{start_expr}
{end_expr}
tell application "Calendar"
    tell calendar {applescript_quote(calendar)}
        make new event with properties {{summary:{applescript_quote(summary)}, start date:startDate, end date:endDate, description:{applescript_quote(description)}}}
    end tell
end tell"""


def build_reminder_script(list_name: str, name: str, due: datetime, body: str) -> str:
    return f"""{applescript_date_expr(due)}
tell application "Reminders"
    tell list {applescript_quote(list_name)}
        make new reminder with properties {{name:{applescript_quote(name)}, due date:theDate, body:{applescript_quote(body)}}}
    end tell
end tell"""


def run_applescript(script: str, run=subprocess.run) -> str:
    res = run(["osascript", "-e", script], capture_output=True, text=True, timeout=60)
    if res.returncode != 0:
        raise CalendarError((res.stderr or res.stdout or "osascript 실패").strip())
    return (res.stdout or "").strip()


def create_calendar_event(cfg: dict, summary: str, start: datetime, end: datetime,
                          description: str, run=subprocess.run) -> None:
    run_applescript(build_calendar_event_script(
        config.timeblock_calendar(cfg), summary, start, end, description), run=run)
    print(f"[calendar] 이벤트 생성: {summary} {start:%m/%d %H:%M}-{end:%H:%M}")


def create_reminder(cfg: dict, name: str, due: datetime, body: str, run=subprocess.run) -> None:
    run_applescript(build_reminder_script(
        cfg.get("REMINDER_LIST") or config.DEFAULTS["REMINDER_LIST"], name, due, body), run=run)
    print(f"[calendar] 미리알림 생성: {name} {due:%m/%d %H:%M}")


# ---------- 수동 점검 ----------

def _smoke() -> int:
    """테스트 이벤트를 하나 만들고 바로 지운다. 첫 실행 시 자동화 권한 프롬프트가 뜬다."""
    cfg = config.load_config()
    cal_name = config.timeblock_calendar(cfg)
    start = datetime.now().replace(second=0, microsecond=0) + timedelta(days=1)
    end = start + timedelta(minutes=30)
    marker = f"meeting-flow smoke {int(start.timestamp())}"
    create_calendar_event(cfg, marker, start, end, "meeting-flow --smoke 테스트, 자동 삭제됨")
    run_applescript(f"""tell application "Calendar"
    tell calendar {applescript_quote(cal_name)}
        delete (every event whose summary is {applescript_quote(marker)})
    end tell
end tell""")
    print(f"[calendar] smoke OK: '{cal_name}'에 이벤트 생성·삭제 성공")
    return 0


if __name__ == "__main__":
    if "--smoke" in sys.argv:
        sys.exit(_smoke())
    print("사용법: python3 -m meetingflow.calendar_io --smoke")
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python3 -m pytest tests/test_calendar_io.py -q`
Expected: 11 passed

- [ ] **Step 5: process_meeting.py에서 중복 함수 제거**

`scripts/process_meeting.py`에서 `def parse_icalbuddy_events(...)` 함수와 `def clean_attendee(...)` 함수를 삭제하고, Task 2에서 추가한 import 아래에 한 줄 추가:

```python
from meetingflow.calendar_io import parse_icalbuddy_events  # noqa: E402
```

`get_meeting_info`는 `parse_icalbuddy_events(out)`를 그대로 호출하므로 수정 불필요.

- [ ] **Step 6: 전체 테스트와 import 확인**

Run: `.venv/bin/python3 -m pytest -q && .venv/bin/python3 -c "import sys; sys.path.insert(0,'scripts'); import process_meeting; print('ok')"`
Expected: 모두 통과, `ok`

- [ ] **Step 7: 커밋**

```bash
git add scripts/meetingflow/calendar_io.py tests/test_calendar_io.py scripts/process_meeting.py
git commit -m "캘린더 모듈 분리: icalBuddy 기간 조회, 다음 차수 탐색, AppleScript 이벤트·미리알림 생성"
```

---

### Task 4: 회의록 파싱·기록 모듈

**Files:**
- Create: `scripts/meetingflow/notes.py`
- Create: `tests/test_notes.py`
- Create: `tests/fixtures/str_weekly_2026-10-07.md`
- Modify: `scripts/process_meeting.py` (`sanitize_filename`을 패키지 import로 대체)

**Interfaces:**
- Produces:
  - `notes.sanitize_filename(name: str) -> str` (기존 함수 이전)
  - `notes.normalize_title(title: str) -> str` (공백 정리 후 `sanitize_filename`)
  - `notes.title_from_note_path(path: Path) -> str` (`YYYY-MM-DD_HHMM_` 접두 제거)
  - `notes.find_notes_by_title(meetings_dir: Path, title: str) -> list[Path]` (최신순, `_briefs` 제외, 정규화 제목 정확 일치)
  - `notes.split_frontmatter(text: str) -> tuple[dict, str]` (값은 원문 문자열, 없으면 `({}, text)`)
  - `notes.frontmatter_list(value: str) -> list[str]` (`[a, "b"]` → `["a","b"]`, `[[x]]` 보존)
  - `notes.body_before_transcript(text: str) -> str`
  - `notes.extract_section(body: str, keyword: str) -> str` (`## ` 제목에 keyword가 포함된 첫 섹션 본문)
  - `notes.parse_action_items(section: str) -> list[dict]` (`{"owner","text","done"}`; `**담당자**: 내용`, `담당자: 내용`, 담당자 없음 → `owner=""`)
  - `notes.append_timeblock_section(note_path: Path, lines: list[str]) -> None` (멱등, `## 전체 전사록` 앞의 `---` 구분선 앞에 삽입)
  - `notes.set_frontmatter_field(note_path: Path, key: str, value: str) -> None`
  - `notes.obsidian_url(vault_name: str, vault_root: Path, note_path: Path) -> str`
  - `notes.TIMEBLOCK_HEADING = "## 📅 타임블록"`, `notes.TRANSCRIPT_HEADING_PREFIX = "## 전체 전사록"`

- [ ] **Step 1: fixture 작성**

`tests/fixtures/str_weekly_2026-10-07.md`:

```markdown
---
title: "[11층 몰디브] STR Weekly"
date: 2026-10-07
time: 10:05 - 11:00
duration: 55분
participants: [Jennifer, Claud, Alex]
projects: ["[[ax-view360]]", "[[ax-legal-management-system]]"]
tags: [meeting]
audio: "/Users/me/Meetings/2026-10-07_1005_[11층 몰디브] STR Weekly.wav"
---

# [11층 몰디브] STR Weekly

## 🎯 요약

이번 주 진행 상황을 공유했다.

## 📢 결정 사항

- CIS 발표는 에반젤리스트 형식으로 간다.
- DBA 담당자는 준케이 콜 이후 확정한다.

## ✅ 액션 아이템

- [ ] **Jennifer**: 레드시프트-트리노 연결 정보 보호 검토 티켓 등록
- [x] **Claud**: 오늘 1시 보안/스트레스 테스트 TC 세션 진행
- [ ] **Claud**: CIS 발표 자료 — 에반젤리스트 스피치 형식으로 재구성 (10/14 전까지)
- [ ] **공통**: DBA 역할 현재 담당자 확인 (준케이 콜 전후)
- [ ] Alex: 챔피언 리스트 조정안 수령 후 협의

## 🔗 관련 프로젝트

- [[ax-view360]] (BI 요건 논의)

---

## 전체 전사록 (화자분리)

**화자1**: 안녕하세요.
```

- [ ] **Step 2: 실패하는 테스트 작성**

`tests/test_notes.py`:

```python
import shutil
from pathlib import Path

from meetingflow import notes

FIX = Path(__file__).parent / "fixtures" / "str_weekly_2026-10-07.md"


def _copy_fixture(dst_dir: Path, name="2026-10-07_1005_[11층 몰디브] STR Weekly.md") -> Path:
    dst = dst_dir / name
    shutil.copy(FIX, dst)
    return dst


def test_normalize_title_matches_filename_stem():
    t = "[11층 몰디브]  STR Weekly"
    assert notes.normalize_title(t) == "[11층 몰디브] STR Weekly"
    p = Path("2026-10-07_1005_[11층 몰디브] STR Weekly.md")
    assert notes.title_from_note_path(p) == "[11층 몰디브] STR Weekly"
    assert notes.normalize_title("CoE 논의 (정기미팅)") == "CoE 논의 (정기미팅)"
    assert notes.normalize_title("A/B: 테스트") == "A_B_ 테스트"


def test_find_notes_by_title_newest_first_excludes_briefs(tmp_path):
    md = tmp_path / "Meetings"; md.mkdir()
    _copy_fixture(md, "2026-09-30_1000_[11층 몰디브] STR Weekly.md")
    _copy_fixture(md, "2026-10-07_1005_[11층 몰디브] STR Weekly.md")
    _copy_fixture(md, "2026-10-07_1500_다른 회의.md")
    (md / "_briefs").mkdir()
    _copy_fixture(md / "_briefs", "2026-10-07_[11층 몰디브] STR Weekly.md")
    found = notes.find_notes_by_title(md, "[11층 몰디브] STR Weekly")
    assert [p.name for p in found] == [
        "2026-10-07_1005_[11층 몰디브] STR Weekly.md",
        "2026-09-30_1000_[11층 몰디브] STR Weekly.md",
    ]


def test_split_frontmatter_and_lists():
    fm, body = notes.split_frontmatter(FIX.read_text(encoding="utf-8"))
    assert fm["title"] == '"[11층 몰디브] STR Weekly"'
    assert notes.frontmatter_list(fm["participants"]) == ["Jennifer", "Claud", "Alex"]
    assert notes.frontmatter_list(fm["projects"]) == ["[[ax-view360]]", "[[ax-legal-management-system]]"]
    assert body.lstrip().startswith("# [11층 몰디브] STR Weekly")


def test_body_before_transcript_and_sections():
    text = FIX.read_text(encoding="utf-8")
    body = notes.body_before_transcript(text)
    assert "화자1" not in body
    decisions = notes.extract_section(body, "결정 사항")
    assert "에반젤리스트" in decisions
    assert "액션 아이템" not in decisions


def test_parse_action_items():
    text = FIX.read_text(encoding="utf-8")
    items = notes.parse_action_items(notes.extract_section(text, "액션 아이템"))
    assert items[0] == {"owner": "Jennifer", "text": "레드시프트-트리노 연결 정보 보호 검토 티켓 등록", "done": False}
    assert items[1]["done"] is True and items[1]["owner"] == "Claud"
    assert items[3]["owner"] == "공통"
    assert items[4] == {"owner": "Alex", "text": "챔피언 리스트 조정안 수령 후 협의", "done": False}


def test_append_timeblock_section_is_idempotent(tmp_path):
    p = _copy_fixture(tmp_path)
    lines = ["- [x] 10/9(목) 14:00-15:00 · CIS 발표 자료 재구성 · 📅",
             "- [ ] DBA 역할 담당자 확인 (건너뜀)"]
    notes.append_timeblock_section(p, lines)
    notes.append_timeblock_section(p, lines + ["- [x] 10/14(화) 09:00 · 확인 · ⏰"])
    text = p.read_text(encoding="utf-8")
    assert text.count(notes.TIMEBLOCK_HEADING) == 1
    assert text.count("CIS 발표 자료 재구성") == 2  # 액션 아이템 1 + 타임블록 1
    assert text.count("10/14(화) 09:00") == 1
    # 전사록 앞, 구분선 앞에 있어야 함
    assert text.index(notes.TIMEBLOCK_HEADING) < text.index("## 전체 전사록")
    assert text.index(notes.TIMEBLOCK_HEADING) > text.index("## 🔗 관련 프로젝트")


def test_append_timeblock_when_no_transcript(tmp_path):
    p = tmp_path / "n.md"
    p.write_text("---\ntitle: x\n---\n\n# x\n\n## ✅ 액션 아이템\n\n- [ ] a\n", encoding="utf-8")
    notes.append_timeblock_section(p, ["- [x] 10/9(목) 14:00-15:00 · a · 📅"])
    assert p.read_text(encoding="utf-8").rstrip().endswith("· a · 📅")


def test_set_frontmatter_field_adds_and_replaces(tmp_path):
    p = _copy_fixture(tmp_path)
    notes.set_frontmatter_field(p, "brief", '"[[2026-10-07_[11층 몰디브] STR Weekly]]"')
    notes.set_frontmatter_field(p, "brief", '"[[other]]"')
    fm, _ = notes.split_frontmatter(p.read_text(encoding="utf-8"))
    assert fm["brief"] == '"[[other]]"'
    assert p.read_text(encoding="utf-8").count("brief:") == 1


def test_obsidian_url_encodes_brackets(tmp_path):
    root = tmp_path / "_obsidian"
    note = root / "Meetings" / "2026-10-07_1005_[11층 몰디브] STR Weekly.md"
    url = notes.obsidian_url("_obsidian", root, note)
    assert url.startswith("obsidian://open?vault=_obsidian&file=")
    assert "%5B11%EC%B8%B5" in url  # '[' 와 한글이 인코딩됨
    assert "Meetings%2F2026" in url  # 경로 구분자도 인코딩 (Obsidian이 해석함)
    assert url.endswith("STR%20Weekly")  # .md 제거, 공백 인코딩
```

- [ ] **Step 3: 실패 확인**

Run: `.venv/bin/python3 -m pytest tests/test_notes.py -q`
Expected: FAIL, ModuleNotFoundError

- [ ] **Step 4: 구현**

`scripts/meetingflow/notes.py`:

```python
"""Obsidian 회의록 읽기·쓰기. 표준 라이브러리만 사용."""
import re
from pathlib import Path
from urllib.parse import quote

TIMEBLOCK_HEADING = "## 📅 타임블록"
TRANSCRIPT_HEADING_PREFIX = "## 전체 전사록"
_NOTE_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{4}_")
_ACTION_RE = re.compile(r"^- \[( |x|X)\]\s*(?:\*\*(.+?)\*\*\s*:|([^:*]{1,30}):)?\s*(.+?)\s*$")


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\n\r]+', "_", name).strip()
    return name[:80] or "회의"


def normalize_title(title: str) -> str:
    return sanitize_filename(" ".join(title.split()))


def title_from_note_path(path: Path) -> str:
    return _NOTE_PREFIX.sub("", Path(path).stem)


def find_notes_by_title(meetings_dir: Path, title: str) -> list:
    target = normalize_title(title)
    hits = [p for p in Path(meetings_dir).glob("*.md")
            if normalize_title(title_from_note_path(p)) == target]
    return sorted(hits, key=lambda p: p.name, reverse=True)


def split_frontmatter(text: str) -> tuple:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("\n---", 1)
    if len(parts) < 2:
        return {}, text
    head = parts[0][3:]
    body = parts[1][1:] if parts[1].startswith("\n") else parts[1]
    fm = {}
    for line in head.splitlines():
        if ":" in line and not line.startswith(" "):
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip()
    return fm, body


def frontmatter_list(value: str) -> list:
    v = value.strip()
    if v.startswith("[") and v.endswith("]"):
        v = v[1:-1]
    out = []
    for part in re.split(r",\s*(?![^\[]*\]\])", v):  # [[a]], [[b]] 안의 쉼표는 보호
        part = part.strip().strip('"').strip("'").strip()
        if part:
            out.append(part)
    return out


def body_before_transcript(text: str) -> str:
    idx = text.find(TRANSCRIPT_HEADING_PREFIX)
    if idx == -1:
        return text
    cut = text[:idx].rstrip()
    if cut.endswith("---"):
        cut = cut[:-3].rstrip()
    return cut


def extract_section(body: str, keyword: str) -> str:
    lines = body.splitlines()
    out, inside = [], False
    for line in lines:
        if line.startswith("## "):
            if inside:
                break
            inside = keyword in line
            continue
        if inside:
            out.append(line)
    return "\n".join(out).strip()


def parse_action_items(section: str) -> list:
    items = []
    for line in section.splitlines():
        m = _ACTION_RE.match(line.strip())
        if not m:
            continue
        done = m.group(1).lower() == "x"
        owner = (m.group(2) or m.group(3) or "").strip()
        items.append({"owner": owner, "text": m.group(4).strip(), "done": done})
    return items


def append_timeblock_section(note_path: Path, lines: list) -> None:
    """타임블록 섹션을 전사록 구분선 앞에 만들거나, 있으면 새 줄만 합친다."""
    note_path = Path(note_path)
    text = note_path.read_text(encoding="utf-8")
    if TIMEBLOCK_HEADING in text:
        head, _, rest = text.partition(TIMEBLOCK_HEADING)
        sec_lines, tail = [], []
        after = rest.split("\n")
        i = 0
        while i < len(after) and not (after[i].startswith("## ") or after[i].strip() == "---"):
            sec_lines.append(after[i]); i += 1
        tail = after[i:]
        existing = [l for l in sec_lines if l.strip()]
        new = [l for l in lines if l not in existing]
        section = "\n".join([TIMEBLOCK_HEADING, ""] + existing + new) + "\n\n"
        note_path.write_text(head + section + "\n".join(tail), encoding="utf-8")
        return
    section = "\n".join([TIMEBLOCK_HEADING, ""] + list(lines))
    idx = text.find(TRANSCRIPT_HEADING_PREFIX)
    if idx == -1:
        new_text = text.rstrip() + "\n\n" + section + "\n"
    else:
        before = text[:idx].rstrip()
        sep = ""
        if before.endswith("---"):
            before = before[:-3].rstrip()
            sep = "\n\n---\n"
        new_text = before + "\n\n" + section + "\n" + sep + "\n" + text[idx:]
    note_path.write_text(new_text, encoding="utf-8")


def set_frontmatter_field(note_path: Path, key: str, value: str) -> None:
    note_path = Path(note_path)
    text = note_path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        note_path.write_text(f"---\n{key}: {value}\n---\n{text}", encoding="utf-8")
        return
    head, sep, rest = text[3:].partition("\n---")
    lines = head.split("\n")
    for i, line in enumerate(lines):
        if line.startswith(f"{key}:"):
            lines[i] = f"{key}: {value}"
            break
    else:
        lines.append(f"{key}: {value}")
    note_path.write_text("---" + "\n".join(lines) + sep + rest, encoding="utf-8")


def obsidian_url(vault_name: str, vault_root: Path, note_path: Path) -> str:
    rel = Path(note_path).resolve().relative_to(Path(vault_root).resolve())
    rel_no_ext = str(rel.with_suffix("")) if rel.suffix == ".md" else str(rel)
    return f"obsidian://open?vault={quote(vault_name, safe='')}&file={quote(rel_no_ext, safe='')}"
```

- [ ] **Step 5: 통과 확인**

Run: `.venv/bin/python3 -m pytest tests/test_notes.py -q`
Expected: 9 passed

- [ ] **Step 6: process_meeting.py에서 sanitize_filename 제거**

`scripts/process_meeting.py`의 `def sanitize_filename(...)` 함수를 삭제하고 import에 추가:

```python
from meetingflow.notes import sanitize_filename  # noqa: E402
```

- [ ] **Step 7: 전체 테스트와 import 확인**

Run: `.venv/bin/python3 -m pytest -q && .venv/bin/python3 -c "import sys; sys.path.insert(0,'scripts'); import process_meeting; print('ok')"`
Expected: 모두 통과, `ok`

- [ ] **Step 8: 커밋**

```bash
git add scripts/meetingflow/notes.py tests/test_notes.py tests/fixtures scripts/process_meeting.py
git commit -m "회의록 파싱·기록 모듈 추가: 섹션 추출, 액션 아이템 파싱, 타임블록 섹션 멱등 기록"
```

---

### Task 5: 후보 상태 저장소 (`.pending`)

**Files:**
- Create: `scripts/meetingflow/pending.py`
- Create: `tests/test_pending.py`

**Interfaces:**
- Produces:
  - `pending.pending_dir(cfg) -> Path` (`meetings_dir/.pending`, 생성 보장)
  - `pending.new_pending(cfg, note_path: Path, title: str, meeting_date: date, items: list[dict], now: datetime) -> Path` (stem 충돌 시 `-2`, `-3` 접미)
  - `pending.load(path) -> dict`, `pending.save(path, data) -> None`
  - `pending.list_pending(cfg) -> list[Path]` (`.pending/*.json`, 하위 폴더·`.`으로 시작하는 파일 제외, 이름순)
  - `pending.needs_renotify(data: dict, now: datetime, remind_at: time) -> bool`
  - `pending.mark_renotified(path, day: date) -> None`
  - `pending.mark_applied(path, item_id: str, applied_at: datetime) -> None`
  - `pending.mark_skipped(path, item_id: str) -> None`
  - `pending.mark_error(path, item_id: str, message: str) -> None`
  - `pending.unresolved_items(data) -> list[dict]` (`applied_at`도 `skipped`도 없는 항목)
  - `pending.move_done(cfg, path) -> Path`
  - `pending.expire_old(cfg, now: datetime, days: int) -> list[Path]` (`created_at + days <= now` → `expired/`로 이동)
  - `pending.cleanup(cfg, now: datetime, days: int = 30) -> int` (`done/`, `expired/`에서 mtime 기준 삭제, 개수 반환)
  - 파일 스키마: `{"note_path","title","meeting_date","created_at","renotified_on","items":[...]}`; 항목에는 Task 6 스키마 + 선택적 `applied_at`, `skipped`, `error`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_pending.py`:

```python
from datetime import date, datetime, time, timedelta
import os

from meetingflow import pending

ITEMS = [
    {"id": "a1", "text": "A", "owner": "Claud", "is_mine": True, "due": "2026-10-14",
     "due_source": "explicit", "kind": "block", "estimate_min": 60},
    {"id": "b2", "text": "B", "owner": "Claud", "is_mine": True, "due": None,
     "due_source": "none", "kind": "reminder", "estimate_min": 0},
]
NOW = datetime(2026, 10, 7, 11, 40)


def _new(cfg, stem="2026-10-07_1005_STR Weekly"):
    note = pending.pending_dir(cfg).parent.parent / "vault" / "Meetings" / f"{stem}.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("x", encoding="utf-8")
    return pending.new_pending(cfg, note, "STR Weekly", date(2026, 10, 7), ITEMS, NOW)


def test_new_pending_writes_schema(cfg):
    p = _new(cfg)
    d = pending.load(p)
    assert p.parent == pending.pending_dir(cfg)
    assert d["title"] == "STR Weekly" and d["meeting_date"] == "2026-10-07"
    assert d["created_at"] == "2026-10-07T11:40:00" and d["renotified_on"] is None
    assert [i["id"] for i in d["items"]] == ["a1", "b2"]


def test_new_pending_does_not_overwrite(cfg):
    p1 = _new(cfg)
    p2 = _new(cfg)
    assert p1 != p2 and p2.name.endswith("-2.json")
    assert len(pending.list_pending(cfg)) == 2


def test_list_pending_ignores_subdirs_and_dotfiles(cfg):
    _new(cfg)
    (pending.pending_dir(cfg) / "done").mkdir()
    (pending.pending_dir(cfg) / "done" / "x.json").write_text("{}")
    (pending.pending_dir(cfg) / ".server.json").write_text("{}")
    assert len(pending.list_pending(cfg)) == 1


def test_needs_renotify_rules(cfg):
    p = _new(cfg)
    d = pending.load(p)
    remind = time(9, 0)
    assert not pending.needs_renotify(d, datetime(2026, 10, 7, 15, 0), remind)   # 당일
    assert not pending.needs_renotify(d, datetime(2026, 10, 8, 8, 59), remind)   # 다음날 09:00 전
    assert pending.needs_renotify(d, datetime(2026, 10, 8, 9, 0), remind)        # 다음날 09:00
    pending.mark_renotified(p, date(2026, 10, 8))
    d = pending.load(p)
    assert not pending.needs_renotify(d, datetime(2026, 10, 8, 10, 0), remind)   # 오늘 이미 보냄
    assert pending.needs_renotify(d, datetime(2026, 10, 9, 9, 0), remind)        # 다음날 다시


def test_mark_applied_skipped_and_resolution(cfg):
    p = _new(cfg)
    pending.mark_applied(p, "a1", datetime(2026, 10, 7, 12, 0))
    d = pending.load(p)
    assert d["items"][0]["applied_at"] == "2026-10-07T12:00:00"
    assert [i["id"] for i in pending.unresolved_items(d)] == ["b2"]
    pending.mark_skipped(p, "b2")
    assert pending.unresolved_items(pending.load(p)) == []
    done = pending.move_done(cfg, p)
    assert done.parent.name == "done" and not p.exists()


def test_expire_old_moves_files(cfg):
    p = _new(cfg)
    assert pending.expire_old(cfg, NOW + timedelta(days=6, hours=23), days=7) == []
    moved = pending.expire_old(cfg, NOW + timedelta(days=7), days=7)
    assert len(moved) == 1 and moved[0].parent.name == "expired" and not p.exists()


def test_cleanup_deletes_old_done(cfg):
    p = _new(cfg)
    done = pending.move_done(cfg, p)
    old = (NOW - timedelta(days=31)).timestamp()
    os.utime(done, (old, old))
    assert pending.cleanup(cfg, NOW, days=30) == 1
    assert not done.exists()
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python3 -m pytest tests/test_pending.py -q`
Expected: FAIL, ModuleNotFoundError

- [ ] **Step 3: 구현**

`scripts/meetingflow/pending.py`:

```python
"""타임블록 후보의 상태 저장소: ~/Meetings/.pending/*.json. 표준 라이브러리만 사용."""
import json
import time as _time
from datetime import date, datetime, time, timedelta
from pathlib import Path

from . import config

ISO = "%Y-%m-%dT%H:%M:%S"


def pending_dir(cfg: dict) -> Path:
    d = config.meetings_dir(cfg) / ".pending"
    d.mkdir(parents=True, exist_ok=True)
    return d


def load(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path: Path, data: dict) -> None:
    tmp = Path(path).with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def new_pending(cfg: dict, note_path: Path, title: str, meeting_date: date,
                items: list, now: datetime) -> Path:
    d = pending_dir(cfg)
    stem = Path(note_path).stem
    path = d / f"{stem}.json"
    n = 2
    while path.exists():
        path = d / f"{stem}-{n}.json"
        n += 1
    save(path, {
        "note_path": str(note_path),
        "title": title,
        "meeting_date": meeting_date.isoformat(),
        "created_at": now.strftime(ISO),
        "renotified_on": None,
        "items": items,
    })
    print(f"[pending] 후보 {len(items)}건 저장: {path.name}")
    return path


def list_pending(cfg: dict) -> list:
    return sorted(p for p in pending_dir(cfg).glob("*.json")
                  if p.is_file() and not p.name.startswith("."))


def needs_renotify(data: dict, now: datetime, remind_at: time) -> bool:
    created = datetime.strptime(data["created_at"], ISO)
    if created.date() >= now.date():
        return False
    if now.time() < remind_at:
        return False
    return data.get("renotified_on") != now.date().isoformat()


def mark_renotified(path: Path, day: date) -> None:
    d = load(path)
    d["renotified_on"] = day.isoformat()
    save(path, d)


def _update_item(path: Path, item_id: str, **fields) -> None:
    d = load(path)
    for it in d["items"]:
        if it["id"] == item_id:
            it.update(fields)
    save(path, d)


def mark_applied(path: Path, item_id: str, applied_at: datetime) -> None:
    _update_item(path, item_id, applied_at=applied_at.strftime(ISO), error=None)


def mark_skipped(path: Path, item_id: str) -> None:
    _update_item(path, item_id, skipped=True)


def mark_error(path: Path, item_id: str, message: str) -> None:
    _update_item(path, item_id, error=message)


def unresolved_items(data: dict) -> list:
    return [i for i in data["items"] if not i.get("applied_at") and not i.get("skipped")]


def _move(path: Path, sub: str) -> Path:
    dst_dir = Path(path).parent / sub
    dst_dir.mkdir(exist_ok=True)
    dst = dst_dir / Path(path).name
    Path(path).replace(dst)
    return dst


def move_done(cfg: dict, path: Path) -> Path:
    return _move(path, "done")


def expire_old(cfg: dict, now: datetime, days: int) -> list:
    moved = []
    for p in list_pending(cfg):
        created = datetime.strptime(load(p)["created_at"], ISO)
        if created + timedelta(days=days) <= now:
            moved.append(_move(p, "expired"))
            print(f"[pending] 만료: {p.name}")
    return moved


def cleanup(cfg: dict, now: datetime, days: int = 30) -> int:
    n = 0
    cutoff = now.timestamp() - days * 86400
    for sub in ("done", "expired"):
        d = pending_dir(cfg) / sub
        if not d.is_dir():
            continue
        for p in d.glob("*.json"):
            if p.stat().st_mtime < cutoff:
                p.unlink()
                n += 1
    return n
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python3 -m pytest tests/test_pending.py -q`
Expected: 7 passed

- [ ] **Step 5: 커밋**

```bash
git add scripts/meetingflow/pending.py tests/test_pending.py
git commit -m "타임블록 후보 상태 저장소(.pending) 모듈 추가"
```


---

### Task 6: 액션 아이템 추출 (Claude → JSON)

**Files:**
- Create: `scripts/meetingflow/actions.py`
- Create: `tests/test_actions.py`

**Interfaces:**
- Consumes: `notes.extract_section`, `notes.parse_action_items`, `config.my_names`
- Produces:
  - `actions.is_mine(owner: str, my_names: list[str]) -> bool` (대소문자 무시, `공통` 참)
  - `actions.build_prompt(action_section: str, attendees: list[str], meeting_date: date, next_meeting_date: date | None, today: date) -> str`
  - `actions.parse_items(text: str) -> list[dict]` (본문에서 첫 JSON 배열을 찾아 검증; 실패 시 `ValueError`)
  - `actions.call_claude(cfg, prompt: str) -> str` (`requests` 사용, 기존 `summarize()`와 같은 엔드포인트)
  - `actions.extract_action_items(cfg, summary: str, attendees: list[str], meeting_date: date, next_meeting_date: date | None, today: date | None = None, call=None) -> list[dict]` (내 항목만, `id` 부여, 재시도 1회, 두 번 실패 시 빈 리스트와 로그)
  - 항목 스키마 (스펙 4절): `id, text, owner, is_mine, due (YYYY-MM-DD|None), due_source ("explicit"|"next_meeting"|"none"), kind ("block"|"reminder"), estimate_min (int, 30 단위, reminder는 0)`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_actions.py`:

```python
import json
from datetime import date

from meetingflow import actions

SECTION = """- [ ] **Jennifer**: 티켓 등록
- [ ] **Claud**: CIS 발표 자료 재구성 (10/14 전까지)
- [ ] **Claud**: 다음 회의 전까지 RNR 초안 작성
- [ ] **공통**: DBA 담당자 확인
- [x] **Claud**: 이미 끝난 일"""

GOOD = json.dumps([
    {"text": "티켓 등록", "owner": "Jennifer", "due": None, "due_source": "none", "kind": "block", "estimate_min": 30},
    {"text": "CIS 발표 자료 재구성", "owner": "Claud", "due": "2026-10-14", "due_source": "explicit", "kind": "block", "estimate_min": 90},
    {"text": "RNR 초안 작성", "owner": "Claud", "due": "2026-10-14", "due_source": "next_meeting", "kind": "block", "estimate_min": 60},
    {"text": "DBA 담당자 확인", "owner": "공통", "due": None, "due_source": "none", "kind": "reminder", "estimate_min": 0},
], ensure_ascii=False)


def test_is_mine():
    names = ["Claud", "클로드"]
    assert actions.is_mine("claud", names)
    assert actions.is_mine("클로드", names)
    assert actions.is_mine("공통", names)
    assert not actions.is_mine("Jennifer", names)
    assert not actions.is_mine("", names)


def test_build_prompt_contains_dates_and_rules():
    p = actions.build_prompt(SECTION, ["Claud", "Jennifer"], date(2026, 10, 7), date(2026, 10, 14), date(2026, 10, 7))
    assert "2026-10-07" in p and "2026-10-14" in p
    assert "JSON" in p and "estimate_min" in p and "next_meeting" in p
    assert "티켓 등록" in p


def test_build_prompt_without_next_meeting():
    p = actions.build_prompt(SECTION, [], date(2026, 10, 7), None, date(2026, 10, 7))
    assert "다음 차수: 미정" in p


def test_parse_items_extracts_array_from_prose():
    items = actions.parse_items("설명입니다.\n```json\n" + GOOD + "\n```\n끝")
    assert len(items) == 4 and items[1]["due"] == "2026-10-14"


def test_parse_items_rejects_bad_schema():
    import pytest
    with pytest.raises(ValueError):
        actions.parse_items('[{"text": "x"}]')
    with pytest.raises(ValueError):
        actions.parse_items("JSON 없음")
    with pytest.raises(ValueError):
        actions.parse_items('[{"text":"x","owner":"a","due":"2026-13-40","due_source":"explicit","kind":"block","estimate_min":30}]')


def test_extract_filters_mine_and_assigns_ids(cfg):
    items = actions.extract_action_items(cfg, "## ✅ 액션 아이템\n\n" + SECTION, ["Claud"],
                                         date(2026, 10, 7), date(2026, 10, 14),
                                         today=date(2026, 10, 7), call=lambda c, p: GOOD)
    assert [i["owner"] for i in items] == ["Claud", "Claud", "공통"]
    assert all(i["is_mine"] for i in items)
    assert len({i["id"] for i in items}) == 3
    assert items[2]["estimate_min"] == 0


def test_extract_retries_once_then_gives_up(cfg):
    calls = []

    def flaky(c, p):
        calls.append(p)
        return "그냥 텍스트"
    items = actions.extract_action_items(cfg, SECTION, [], date(2026, 10, 7), None, call=flaky)
    assert items == [] and len(calls) == 2
    assert "JSON" in calls[1] and calls[1] != calls[0]


def test_extract_recovers_on_second_try(cfg):
    answers = iter(["엉뚱한 답", GOOD])
    items = actions.extract_action_items(cfg, SECTION, [], date(2026, 10, 7), None,
                                         call=lambda c, p: next(answers))
    assert len(items) == 3


def test_extract_skips_when_no_section_or_no_names(cfg):
    assert actions.extract_action_items(cfg, "## 🎯 요약\n\n없음", [], date(2026, 10, 7), None,
                                        call=lambda c, p: GOOD) == []
    cfg2 = dict(cfg, MY_NAMES="")
    assert actions.extract_action_items(cfg2, SECTION, [], date(2026, 10, 7), None,
                                        call=lambda c, p: GOOD) == []


def test_estimate_rounded_to_30(cfg):
    odd = json.dumps([{"text": "x", "owner": "Claud", "due": "2026-10-10", "due_source": "explicit",
                       "kind": "block", "estimate_min": 45}])
    items = actions.extract_action_items(cfg, SECTION, [], date(2026, 10, 7), None, call=lambda c, p: odd)
    assert items[0]["estimate_min"] == 60
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python3 -m pytest tests/test_actions.py -q`
Expected: FAIL, ModuleNotFoundError

- [ ] **Step 3: 구현**

`scripts/meetingflow/actions.py`:

```python
"""회의록 액션 아이템에서 내 할 일을 구조화 JSON으로 추출한다 (Claude 호출)."""
import json
import re
import uuid
from datetime import date, datetime

from . import config, notes

MODEL = "claude-sonnet-4-6"
REQUIRED = {"text", "owner", "due", "due_source", "kind", "estimate_min"}
DUE_SOURCES = {"explicit", "next_meeting", "none"}
KINDS = {"block", "reminder"}


def is_mine(owner: str, my_names: list) -> bool:
    o = (owner or "").strip().lower()
    if not o:
        return False
    if o == "공통":
        return True
    return any(o == n.lower() for n in my_names)


def build_prompt(action_section: str, attendees: list, meeting_date: date,
                 next_meeting_date: date | None, today: date) -> str:
    nxt = next_meeting_date.isoformat() if next_meeting_date else "미정"
    return f"""다음은 {meeting_date.isoformat()}에 열린 회의의 액션 아이템 목록입니다.
오늘 날짜: {today.isoformat()}
참석자: {", ".join(attendees) if attendees else "미상"}
같은 회의의 다음 차수: {nxt}

각 항목을 아래 스키마의 JSON 배열로만 출력하세요. 설명이나 코드 펜스 없이 배열만 출력합니다.
완료된 항목(- [x])은 제외합니다.

[
  {{
    "text": "할 일 (담당자 이름과 기한 표현을 뺀 한 줄)",
    "owner": "담당자 이름 (원문 표기 그대로, 공통이면 \\"공통\\")",
    "due": "YYYY-MM-DD 또는 null",
    "due_source": "explicit | next_meeting | none",
    "kind": "block | reminder",
    "estimate_min": 30
  }}
]

규칙:
- due: 날짜·요일·"오늘"·"내일"·"이번 주" 등 기한 표현이 있으면 오늘 날짜를 기준으로 YYYY-MM-DD로 환산하고 due_source는 "explicit".
  "다음 회의 전까지"·"다음 주 공유"처럼 차수를 기준으로 하면 다음 차수 날짜를 쓰고 due_source는 "next_meeting". 다음 차수가 미정이면 due는 null, due_source는 "none".
  기한 단서가 전혀 없으면 due는 null, due_source는 "none".
- kind: 자료 작성·분석·개발·정리처럼 앉아서 작업할 시간이 필요하면 "block", 확인·회신·참석·공유처럼 몇 분이면 끝나면 "reminder".
- estimate_min: block이면 필요한 작업 시간을 30분 단위(30, 60, 90, 120, 180)로 추정, reminder면 0.

액션 아이템:
{action_section}"""


def parse_items(text: str) -> list:
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        raise ValueError("JSON 배열을 찾을 수 없음")
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON 파싱 실패: {e}") from e
    if not isinstance(data, list):
        raise ValueError("배열이 아님")
    for it in data:
        if not isinstance(it, dict) or not REQUIRED.issubset(it):
            raise ValueError(f"필드 누락: {it}")
        if it["due_source"] not in DUE_SOURCES or it["kind"] not in KINDS:
            raise ValueError(f"enum 값 오류: {it}")
        if it["due"] is not None:
            datetime.strptime(it["due"], "%Y-%m-%d")  # 형식 검증, 실패 시 ValueError
    return data


def call_claude(cfg: dict, prompt: str) -> str:
    import requests  # tick 경로에서 import되지 않도록 지연 import
    res = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": cfg["ANTHROPIC_API_KEY"],
                 "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json={"model": MODEL, "max_tokens": 2000,
              "messages": [{"role": "user", "content": prompt}]},
        timeout=120,
    )
    res.raise_for_status()
    return "".join(b.get("text", "") for b in res.json()["content"] if b.get("type") == "text")


def _round30(n) -> int:
    try:
        n = int(n)
    except (TypeError, ValueError):
        return 30
    return max(30, ((n + 29) // 30) * 30)


def extract_action_items(cfg: dict, summary: str, attendees: list, meeting_date: date,
                         next_meeting_date: date | None, today: date | None = None,
                         call=None) -> list:
    """요약의 액션 아이템 섹션에서 내 항목만 구조화해 반환. 실패하면 빈 리스트."""
    call = call or call_claude
    today = today or date.today()
    names = config.my_names(cfg)
    if not names:
        print("[actions] MY_NAMES가 비어 있어 추출을 건너뜀")
        return []
    section = notes.extract_section(summary, "액션 아이템") if "## " in summary else summary
    if not section or not notes.parse_action_items(section):
        print("[actions] 액션 아이템 섹션 없음")
        return []
    prompt = build_prompt(section, attendees, meeting_date, next_meeting_date, today)
    raw_items = None
    for attempt in range(2):
        try:
            raw_items = parse_items(call(cfg, prompt))
            break
        except Exception as e:  # noqa: BLE001
            print(f"[actions] 추출 실패 ({attempt + 1}/2): {e}")
            prompt = prompt + "\n\n중요: 다른 말 없이 JSON 배열만 출력하세요."
    if raw_items is None:
        return []
    out = []
    for it in raw_items:
        if not is_mine(it["owner"], names):
            continue
        kind = it["kind"]
        out.append({
            "id": uuid.uuid4().hex,
            "text": str(it["text"]).strip(),
            "owner": str(it["owner"]).strip(),
            "is_mine": True,
            "due": it["due"],
            "due_source": it["due_source"] if it["due"] else "none",
            "kind": kind,
            "estimate_min": 0 if kind == "reminder" else _round30(it["estimate_min"]),
        })
    print(f"[actions] 내 액션 아이템 {len(out)}건 추출")
    return out
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python3 -m pytest tests/test_actions.py -q`
Expected: 10 passed

- [ ] **Step 5: 커밋**

```bash
git add scripts/meetingflow/actions.py tests/test_actions.py
git commit -m "액션 아이템 추출 모듈 추가: Claude JSON 응답 검증, 내 항목 필터, 1회 재시도"
```

---

### Task 7: 후처리 파이프라인에 추출 단계 연결

**Files:**
- Modify: `scripts/process_meeting.py` (`main()`의 Obsidian 저장 직후)
- Create: `scripts/review-open.sh` (빈 자리 표시가 아니라 동작하는 1차 버전. 서버는 Task 9에서 생기므로, 그때까지는 "서버 없음" 메시지만 출력)
- Create: `tests/test_process_hooks.py`

**Interfaces:**
- Consumes: `actions.extract_action_items`, `calendar_io.find_next_event`, `notes.normalize_title`, `pending.new_pending`, `notify.notify`
- Produces:
  - `process_meeting.queue_timeblock_candidates(cfg, note_path: Path, title: str, summary: str, attendees: list, start_dt: datetime, now: datetime | None = None, call=None, run=None) -> Path | None` (후보가 없으면 None, 어떤 예외도 밖으로 내지 않음)
  - `process_meeting.REVIEW_OPEN = SCRIPT_DIR / "review-open.sh"`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_process_hooks.py`:

```python
import json
from datetime import datetime
from pathlib import Path

import process_meeting as pm
from meetingflow import pending

GOOD = json.dumps([{"text": "RNR 초안", "owner": "Claud", "due": "2026-10-14",
                    "due_source": "next_meeting", "kind": "block", "estimate_min": 60}])
SUMMARY = "## ✅ 액션 아이템\n\n- [ ] **Claud**: 다음 회의 전까지 RNR 초안\n"


def _fake_ical(cmd, **kw):
    class R: stdout = "STR Weekly\n    2026-10-14 at 10:00 - 11:00\n"
    return R()


def test_queue_creates_pending_and_notifies(cfg, monkeypatch, tmp_path):
    sent = []
    monkeypatch.setattr(pm, "notify", lambda *a, **k: sent.append((a, k)))
    note = Path(cfg["OBSIDIAN_DIR"]) / "2026-10-07_1005_STR Weekly.md"
    note.write_text("x", encoding="utf-8")
    p = pm.queue_timeblock_candidates(cfg, note, "STR Weekly", SUMMARY, ["Claud"],
                                      datetime(2026, 10, 7, 10, 5), now=datetime(2026, 10, 7, 11, 40),
                                      call=lambda c, pr: GOOD, run=_fake_ical)
    assert p is not None and p.parent == pending.pending_dir(cfg)
    data = pending.load(p)
    assert data["items"][0]["due"] == "2026-10-14"
    assert sent and "타임블록 후보 1건" in sent[0][0][1]
    assert sent[0][1]["execute"].endswith("review-open.sh")


def test_queue_returns_none_without_items(cfg, monkeypatch):
    monkeypatch.setattr(pm, "notify", lambda *a, **k: None)
    note = Path(cfg["OBSIDIAN_DIR"]) / "n.md"; note.write_text("x")
    assert pm.queue_timeblock_candidates(cfg, note, "t", "## 🎯 요약\n없음", [], datetime(2026, 10, 7),
                                         call=lambda c, pr: "[]", run=_fake_ical) is None
    assert pending.list_pending(cfg) == []


def test_queue_swallows_exceptions(cfg, monkeypatch):
    warned = []
    monkeypatch.setattr(pm, "notify", lambda *a, **k: warned.append(a))

    def boom(c, pr):
        raise RuntimeError("network down")
    note = Path(cfg["OBSIDIAN_DIR"]) / "n.md"; note.write_text("x")
    # actions 내부에서 두 번 실패 → 빈 리스트 → None. 그 밖의 예외도 밖으로 나오지 않아야 함
    assert pm.queue_timeblock_candidates(cfg, note, "t", SUMMARY, [], datetime(2026, 10, 7),
                                         call=boom, run=_fake_ical) is None

    def ical_boom(cmd, **kw):
        raise OSError("icalBuddy missing")
    assert pm.queue_timeblock_candidates(cfg, note, "t", SUMMARY, [], datetime(2026, 10, 7),
                                         call=lambda c, pr: GOOD, run=ical_boom) is not None
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python3 -m pytest tests/test_process_hooks.py -q`
Expected: FAIL, `AttributeError: module 'process_meeting' has no attribute 'queue_timeblock_candidates'`

- [ ] **Step 3: 구현**

`scripts/process_meeting.py` import 구역(Task 2~4에서 추가한 줄 아래)에 추가:

```python
from meetingflow import actions, calendar_io, notes as mf_notes, pending  # noqa: E402

REVIEW_OPEN = Path(__file__).resolve().parent / "review-open.sh"
```

`# ---------- main ----------` 바로 위에 함수 추가:

```python
# ---------- 6. 내 액션 아이템 → 타임블록 후보 ----------

def queue_timeblock_candidates(cfg: dict, note_path: Path, title: str, summary: str,
                               attendees: list, start_dt: datetime, now: datetime = None,
                               call=None, run=None) -> Path:
    """내 액션 아이템을 추출해 .pending 후보로 저장하고 알림을 보낸다.
    실패해도 예외를 내지 않는다 (회의록은 이미 저장된 상태)."""
    now = now or datetime.now()
    try:
        next_ev = None
        try:
            kw = {"run": run} if run else {}
            next_ev = calendar_io.find_next_event(cfg, title, mf_notes.normalize_title, now, **kw)
        except Exception as e:  # noqa: BLE001
            print(f"[actions] 다음 차수 조회 실패, 미정으로 진행: {e}")
        next_date = datetime.fromtimestamp(next_ev["start_ts"]).date() if next_ev else None
        items = actions.extract_action_items(cfg, summary, attendees, start_dt.date(), next_date,
                                             today=now.date(), call=call)
        if not items:
            return None
        path = pending.new_pending(cfg, note_path, title, start_dt.date(), items, now)
        notify("타임블록 후보 📅", f"{title}: 타임블록 후보 {len(items)}건 (클릭하면 검토)",
               execute=str(REVIEW_OPEN), group="meetingflow-review")
        return path
    except Exception as e:  # noqa: BLE001
        print(f"[actions] 후보 생성 실패: {e}")
        notify("액션 아이템 추출 실패 ⚠️", str(e)[:100])
        return None
```

`main()`에서 `note = write_obsidian_note(...)` 호출 직후, `state_file.unlink(...)` 앞에 추가:

```python
        # 6. 내 액션 아이템 → 타임블록 후보 (실패해도 회의록은 유지)
        queue_timeblock_candidates(cfg, note, title, summary, attendees, start_dt)
```

`scripts/review-open.sh` (1차 버전, Task 9에서 완성):

```bash
#!/bin/bash
# 타임블록 검토 팝업을 연다. 알림 클릭과 Raycast/Quick Action 트리거가 공용으로 사용.
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYBIN="$SCRIPT_DIR/../.venv/bin/python3"
[[ -x "$PYBIN" ]] || PYBIN="python3"
if [[ ! -f "$SCRIPT_DIR/meetingflow/review_server.py" ]]; then
  echo "review_server.py가 아직 없습니다 (Task 9에서 추가)."
  exit 1
fi
exec "$PYBIN" "$SCRIPT_DIR/review-open.py"
```

```bash
chmod +x scripts/review-open.sh
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python3 -m pytest -q`
Expected: 모두 통과

- [ ] **Step 5: 커밋**

```bash
git add scripts/process_meeting.py scripts/review-open.sh tests/test_process_hooks.py
git commit -m "회의록 저장 후 내 액션 아이템을 타임블록 후보로 큐에 넣고 알림"
```

---

### Task 8: 빈 시간 제안 (`slots.py`)

**Files:**
- Create: `scripts/meetingflow/slots.py`
- Create: `tests/test_slots.py`

**Interfaces:**
- Consumes: `config.work_hours`, `config.parse_hhmm`
- Produces:
  - `slots.Busy = tuple[datetime, datetime]`
  - `slots.busy_from_events(events: list[dict]) -> list[Busy]` (icalBuddy dict → datetime 구간)
  - `slots.free_slots_for_day(day: date, busy: list[Busy], work: tuple[time, time], duration_min: int, not_before: datetime | None = None) -> list[Busy]` (근무 시간 안의 빈 구간 중 duration 이상인 것들, 시작 시각은 30분 격자)
  - `slots.propose(items: list[dict], events: list[dict], cfg: dict, now: datetime) -> list[dict]` (각 항목 복사본에 `proposed_start`, `proposed_end` (ISO 또는 None), `conflict: bool`, `overdue: bool`, `default_checked: bool` 추가)
  - 규칙 (스펙 5절): 탐색 범위는 내일부터 due 전날까지의 평일, 뒤에서부터 가장 늦은 빈 구간. due가 내일 이하면 due 당일. due 없음 → 제안 없음. 빈 구간 없음 → due 전날(또는 due 당일) 근무 종료에서 duration만큼 앞, `conflict=True`. `reminder` → due 당일 `MORNING_REMIND_AT`. 같은 세션 안에서 이미 배치한 후보는 busy에 추가. `default_checked = due is not None and not overdue and owner != "공통"`.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_slots.py`:

```python
from datetime import date, datetime, time

from meetingflow import slots

WORK = (time(10, 0), time(18, 0))
NOW = datetime(2026, 10, 7, 11, 40)  # 수요일


def _ev(d, h1, m1, h2, m2):
    return {"title": "x", "attendees": [],
            "start_ts": int(datetime(d.year, d.month, d.day, h1, m1).timestamp()),
            "end_ts": int(datetime(d.year, d.month, d.day, h2, m2).timestamp())}


def _item(**kw):
    base = {"id": "i", "text": "t", "owner": "Claud", "is_mine": True, "due": "2026-10-14",
            "due_source": "explicit", "kind": "block", "estimate_min": 60}
    base.update(kw)
    return base


def test_free_slots_respects_busy_and_grid():
    day = date(2026, 10, 9)
    busy = slots.busy_from_events([_ev(day, 10, 0, 12, 0), _ev(day, 14, 0, 15, 0)])
    free = slots.free_slots_for_day(day, busy, WORK, 60)
    starts = [(s.hour, s.minute) for s, _ in free]
    assert (12, 0) in starts and (15, 0) in starts and (17, 0) in starts
    assert (11, 0) not in starts and (14, 0) not in starts
    assert all(m in (0, 30) for _, m in starts)


def test_propose_picks_latest_free_slot_before_due():
    items = [_item(due="2026-10-14")]  # 수요일. 전날 10/13(화) 17:00-18:00이 가장 늦은 빈 구간
    out = slots.propose(items, [], {"WORK_HOURS": "10:00-18:00", "MORNING_REMIND_AT": "09:00"}, NOW)
    assert out[0]["proposed_start"] == "2026-10-13T17:00:00"
    assert out[0]["proposed_end"] == "2026-10-13T18:00:00"
    assert out[0]["conflict"] is False and out[0]["default_checked"] is True


def test_propose_skips_weekend():
    items = [_item(due="2026-10-12")]  # 월요일 → 전날이 주말이므로 10/9(금)
    out = slots.propose(items, [], {"WORK_HOURS": "10:00-18:00", "MORNING_REMIND_AT": "09:00"}, NOW)
    assert out[0]["proposed_start"].startswith("2026-10-09T")


def test_propose_avoids_same_session_overlap():
    items = [_item(id="a", due="2026-10-14"), _item(id="b", due="2026-10-14")]
    out = slots.propose(items, [], {"WORK_HOURS": "10:00-18:00", "MORNING_REMIND_AT": "09:00"}, NOW)
    assert out[0]["proposed_start"] == "2026-10-13T17:00:00"
    assert out[1]["proposed_start"] == "2026-10-13T16:00:00"


def test_propose_conflict_when_day_full():
    day = date(2026, 10, 13)
    evs = [_ev(day, 10, 0, 18, 0)]
    items = [_item(due="2026-10-14")]
    # 전날이 꽉 차면 그 전 평일로 올라감. 범위(10/8~10/13)의 평일이 모두 꽉 찼을 때만 conflict
    full = [_ev(date(2026, 10, d), 10, 0, 18, 0) for d in (8, 9, 12, 13)]
    out = slots.propose(items, full, {"WORK_HOURS": "10:00-18:00", "MORNING_REMIND_AT": "09:00"}, NOW)
    assert out[0]["conflict"] is True
    assert out[0]["proposed_start"] == "2026-10-13T17:00:00"
    out2 = slots.propose(items, evs, {"WORK_HOURS": "10:00-18:00", "MORNING_REMIND_AT": "09:00"}, NOW)
    assert out2[0]["conflict"] is False and out2[0]["proposed_start"] == "2026-10-12T17:00:00"


def test_due_today_uses_today_remaining_hours():
    items = [_item(due="2026-10-07", estimate_min=30)]
    out = slots.propose(items, [], {"WORK_HOURS": "10:00-18:00", "MORNING_REMIND_AT": "09:00"}, NOW)
    assert out[0]["proposed_start"] == "2026-10-07T17:30:00"
    assert out[0]["overdue"] is False
    s = datetime.fromisoformat(out[0]["proposed_start"])
    assert s > NOW


def test_due_past_marks_overdue():
    items = [_item(due="2026-10-06")]
    out = slots.propose(items, [], {"WORK_HOURS": "10:00-18:00", "MORNING_REMIND_AT": "09:00"}, NOW)
    assert out[0]["overdue"] is True and out[0]["default_checked"] is False
    assert out[0]["proposed_start"] is None


def test_no_due_no_proposal_and_unchecked():
    items = [_item(due=None, due_source="none")]
    out = slots.propose(items, [], {"WORK_HOURS": "10:00-18:00", "MORNING_REMIND_AT": "09:00"}, NOW)
    assert out[0]["proposed_start"] is None and out[0]["default_checked"] is False


def test_reminder_uses_morning_time_on_due():
    items = [_item(kind="reminder", estimate_min=0, due="2026-10-14")]
    out = slots.propose(items, [], {"WORK_HOURS": "10:00-18:00", "MORNING_REMIND_AT": "09:00"}, NOW)
    assert out[0]["proposed_start"] == "2026-10-14T09:00:00" and out[0]["proposed_end"] is None


def test_common_owner_unchecked_by_default():
    items = [_item(owner="공통")]
    out = slots.propose(items, [], {"WORK_HOURS": "10:00-18:00", "MORNING_REMIND_AT": "09:00"}, NOW)
    assert out[0]["default_checked"] is False and out[0]["proposed_start"] is not None
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python3 -m pytest tests/test_slots.py -q`
Expected: FAIL, ModuleNotFoundError

- [ ] **Step 3: 구현**

`scripts/meetingflow/slots.py`:

```python
"""타임블록 제안 시간 계산. 표준 라이브러리만 사용."""
from datetime import date, datetime, time, timedelta

from . import config

GRID_MIN = 30


def busy_from_events(events: list) -> list:
    out = []
    for e in events:
        if e.get("start_ts") and e.get("end_ts"):
            out.append((datetime.fromtimestamp(e["start_ts"]), datetime.fromtimestamp(e["end_ts"])))
    return out


def _overlaps(a: tuple, b: tuple) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def free_slots_for_day(day: date, busy: list, work: tuple, duration_min: int,
                       not_before: datetime | None = None) -> list:
    """근무 시간 안에서 duration_min 길이로 들어갈 수 있는 시작 구간들 (30분 격자, 시간순)."""
    start = datetime.combine(day, work[0])
    end = datetime.combine(day, work[1])
    dur = timedelta(minutes=duration_min)
    day_busy = [b for b in busy if b[0].date() == day or b[1].date() == day]
    out = []
    t = start
    if not_before and not_before > t:
        # 격자에 맞춰 올림
        minutes = (not_before.minute // GRID_MIN + 1) * GRID_MIN
        t = not_before.replace(second=0, microsecond=0, minute=0) + timedelta(minutes=minutes)
    while t + dur <= end:
        cand = (t, t + dur)
        if not any(_overlaps(cand, b) for b in day_busy):
            out.append(cand)
        t += timedelta(minutes=GRID_MIN)
    return out


def _weekdays_desc(first: date, last: date) -> list:
    days = []
    d = last
    while d >= first:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    return days


def _propose_block(due: date, duration_min: int, busy: list, work: tuple, now: datetime) -> tuple:
    """(start, end, conflict). 범위: 내일~due 전날의 평일, 늦은 날부터. due가 내일 이하면 due 당일."""
    today = now.date()
    if due <= today + timedelta(days=1):
        days = [due]
        not_before = now if due == today else None
    else:
        days = _weekdays_desc(today + timedelta(days=1), due - timedelta(days=1))
        not_before = None
        if not days:  # 내일~전날 사이에 평일이 없음 (주말) → due 당일
            days = [due]
    for d in days:
        free = free_slots_for_day(d, busy, work, duration_min, not_before if d == today else None)
        if free:
            return free[-1][0], free[-1][1], False
    fallback_day = days[0]
    end = datetime.combine(fallback_day, work[1])
    return end - timedelta(minutes=duration_min), end, True


def propose(items: list, events: list, cfg: dict, now: datetime) -> list:
    work = config.work_hours(cfg)
    remind_at = config.parse_hhmm(cfg.get("MORNING_REMIND_AT") or config.DEFAULTS["MORNING_REMIND_AT"])
    busy = busy_from_events(events)
    out = []
    for raw in items:
        it = dict(raw)
        due = date.fromisoformat(it["due"]) if it.get("due") else None
        overdue = bool(due and due < now.date())
        it.update({"proposed_start": None, "proposed_end": None, "conflict": False, "overdue": overdue})
        if due and not overdue:
            if it["kind"] == "reminder":
                it["proposed_start"] = datetime.combine(due, remind_at).isoformat()
            else:
                s, e, conflict = _propose_block(due, it["estimate_min"] or GRID_MIN, busy, work, now)
                it["proposed_start"], it["proposed_end"], it["conflict"] = s.isoformat(), e.isoformat(), conflict
                busy.append((s, e))
        it["default_checked"] = bool(due) and not overdue and it.get("owner") != "공통"
        out.append(it)
    return out
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python3 -m pytest tests/test_slots.py -q`
Expected: 11 passed. `test_due_today_uses_today_remaining_hours`에서 NOW가 11:40이므로 `not_before` 격자 올림은 12:00이고, 30분 블록의 가장 늦은 시작은 17:30이다.

- [ ] **Step 5: 커밋**

```bash
git add scripts/meetingflow/slots.py tests/test_slots.py
git commit -m "타임블록 제안 시간 계산 모듈 추가"
```

---

### Task 9: 검토 팝업 서버와 반영

**Files:**
- Create: `scripts/meetingflow/review_server.py`
- Create: `scripts/meetingflow/review_page.html`
- Create: `scripts/review-open.py`
- Modify: `scripts/review-open.sh` (Task 7의 1차 버전을 최종 버전으로 교체)
- Create: `tests/test_review_server.py`
- Create: `tests/fixtures/pending_demo.json`

**Interfaces:**
- Consumes: `pending.*`, `slots.propose`, `calendar_io.events_between/create_calendar_event/create_reminder/CalendarError`, `notes.append_timeblock_section/obsidian_url`, `notify.notify`, `config.*`
- Produces:
  - `review_server.build_state(cfg, now: datetime, run=None) -> dict` → `{"meetings": [{"pending_path", "title", "meeting_date", "note_url", "items": [제안 포함 항목]}], "events": [{"start","end","title"}], "work_hours": "10:00-18:00"}` (오늘부터 7일 일정; 미해결 항목만)
  - `review_server.format_timeblock_line(item: dict, start: datetime | None, end: datetime | None, applied: bool) -> str` (스펙 줄 형식; 요일은 한글 월~일)
  - `review_server.apply(cfg, approvals: list[dict], now: datetime, create_event=None, create_reminder=None) -> dict` → `{"applied": n, "skipped": n, "failed": [{"id","error"}]}`. 각 approval: `{"pending_path","id","approve":bool,"kind","title","start":"ISO","end":"ISO|null"}`
  - HTTP: `GET /health` → `{"app":"meetingflow"}`; `GET /` → HTML; `GET /api/state` → build_state JSON; `POST /api/apply` (JSON 배열) → apply 결과 JSON; `POST /api/shutdown`
  - `review_server.serve(cfg, port: int, idle_seconds: int = 600, demo_state: dict | None = None) -> None`
  - CLI: `python3 -m meetingflow.review_server [--port N] [--demo]`
  - `scripts/review-open.py`: 서버 확인·기동·브라우저 열기 (아래)

- [ ] **Step 1: fixture와 실패하는 테스트 작성**

`tests/fixtures/pending_demo.json`:

```json
{
  "note_path": "/tmp/demo/Meetings/2026-10-07_1005_[11층 몰디브] STR Weekly.md",
  "title": "[11층 몰디브] STR Weekly",
  "meeting_date": "2026-10-07",
  "created_at": "2026-10-07T11:40:00",
  "renotified_on": null,
  "items": [
    {"id": "a1", "text": "CIS 발표 자료 에반젤리스트 형식으로 재구성", "owner": "Claud", "is_mine": true,
     "due": "2026-10-14", "due_source": "explicit", "kind": "block", "estimate_min": 90},
    {"id": "b2", "text": "법무 RNR 초안 작성", "owner": "Claud", "is_mine": true,
     "due": "2026-10-14", "due_source": "next_meeting", "kind": "block", "estimate_min": 60},
    {"id": "c3", "text": "Sentry 초대 수락 확인", "owner": "Claud", "is_mine": true,
     "due": "2026-10-09", "due_source": "explicit", "kind": "reminder", "estimate_min": 0},
    {"id": "d4", "text": "DBA 역할 담당자 확인", "owner": "공통", "is_mine": true,
     "due": null, "due_source": "none", "kind": "reminder", "estimate_min": 0}
  ]
}
```

`tests/test_review_server.py`:

```python
import json
import shutil
import threading
import urllib.request
from datetime import date, datetime
from pathlib import Path

from meetingflow import pending, review_server as rs

FIX = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 7, 11, 40)


def _setup(cfg):
    note = Path(cfg["OBSIDIAN_DIR"]) / "2026-10-07_1005_[11층 몰디브] STR Weekly.md"
    shutil.copy(FIX / "str_weekly_2026-10-07.md", note)
    data = json.loads((FIX / "pending_demo.json").read_text(encoding="utf-8"))
    data["note_path"] = str(note)
    p = pending.pending_dir(cfg) / note.with_suffix(".json").name
    pending.save(p, data)
    return note, p


def _no_events(cmd, **kw):
    class R: stdout = ""
    return R()


def test_build_state_lists_unresolved_with_proposals(cfg):
    note, p = _setup(cfg)
    pending.mark_skipped(p, "d4")
    st = rs.build_state(cfg, NOW, run=_no_events)
    m = st["meetings"][0]
    assert m["title"] == "[11층 몰디브] STR Weekly" and m["pending_path"] == str(p)
    assert [i["id"] for i in m["items"]] == ["a1", "b2", "c3"]
    assert m["items"][0]["proposed_start"] == "2026-10-13T16:30:00"
    assert m["items"][2]["proposed_start"] == "2026-10-09T09:00:00"
    assert m["note_url"].startswith("obsidian://open?vault=_obsidian&file=Meetings%2F")
    assert st["work_hours"] == "10:00-18:00" and st["events"] == []


def test_format_timeblock_line():
    it = {"text": "RNR 초안", "kind": "block"}
    assert rs.format_timeblock_line(it, datetime(2026, 10, 9, 14, 0), datetime(2026, 10, 9, 15, 0), True) \
        == "- [x] 10/9(금) 14:00-15:00 · RNR 초안 · 📅"
    r = {"text": "확인", "kind": "reminder"}
    assert rs.format_timeblock_line(r, datetime(2026, 10, 14, 9, 0), None, True) \
        == "- [x] 10/14(수) 09:00 · 확인 · ⏰"
    assert rs.format_timeblock_line(it, None, None, False) == "- [ ] RNR 초안 (건너뜀)"


def test_apply_creates_records_and_moves_done(cfg):
    note, p = _setup(cfg)
    created = []
    approvals = [
        {"pending_path": str(p), "id": "a1", "approve": True, "kind": "block", "title": "CIS 발표 자료",
         "start": "2026-10-13T16:30:00", "end": "2026-10-13T18:00:00"},
        {"pending_path": str(p), "id": "b2", "approve": False},
        {"pending_path": str(p), "id": "c3", "approve": True, "kind": "reminder", "title": "Sentry 확인",
         "start": "2026-10-09T09:00:00", "end": None},
        {"pending_path": str(p), "id": "d4", "approve": False},
    ]
    res = rs.apply(cfg, approvals, NOW,
                   create_event=lambda c, s, st, en, d: created.append(("ev", s, st, en, d)),
                   create_reminder=lambda c, n, due, b: created.append(("rem", n, due, b)))
    assert res == {"applied": 2, "skipped": 2, "failed": []}
    assert created[0][0] == "ev" and created[0][1] == "CIS 발표 자료"
    assert "obsidian://" in created[0][4] and "[11층 몰디브] STR Weekly" in created[0][4]
    assert created[1][0] == "rem"
    text = note.read_text(encoding="utf-8")
    assert "- [x] 10/13(화) 16:30-18:00 · CIS 발표 자료 · 📅" in text
    assert "- [x] 10/9(금) 09:00 · Sentry 확인 · ⏰" in text
    assert "- [ ] 법무 RNR 초안 작성 (건너뜀)" in text
    assert not p.exists() and (p.parent / "done" / p.name).exists()


def test_apply_isolates_failures_and_keeps_pending(cfg):
    from meetingflow.calendar_io import CalendarError
    note, p = _setup(cfg)

    def failing(c, s, st, en, d):
        raise CalendarError("execution error: -1743")
    res = rs.apply(cfg, [
        {"pending_path": str(p), "id": "a1", "approve": True, "kind": "block", "title": "x",
         "start": "2026-10-13T16:30:00", "end": "2026-10-13T18:00:00"},
        {"pending_path": str(p), "id": "c3", "approve": True, "kind": "reminder", "title": "y",
         "start": "2026-10-09T09:00:00", "end": None},
    ], NOW, create_event=failing, create_reminder=lambda *a: None)
    assert res["applied"] == 1 and res["failed"] == [{"id": "a1", "error": "execution error: -1743"}]
    assert p.exists()  # 미해결 항목이 남아 done으로 가지 않음
    d = pending.load(p)
    assert d["items"][0].get("error") and d["items"][2].get("applied_at")


def test_http_endpoints(cfg):
    note, p = _setup(cfg)
    srv = rs.make_server(cfg, port=0, now_fn=lambda: NOW, run=_no_events,
                         create_event=lambda *a: None, create_reminder=lambda *a: None,
                         send=lambda *a, **k: None)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True); t.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health") as r:
            assert json.loads(r.read())["app"] == "meetingflow"
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/") as r:
            html = r.read().decode()
            assert "<html" in html and "/api/state" in html
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state") as r:
            st = json.loads(r.read())
            assert st["meetings"][0]["items"]
        body = json.dumps([{"pending_path": str(p), "id": "a1", "approve": True, "kind": "block",
                            "title": "t", "start": "2026-10-13T16:30:00", "end": "2026-10-13T18:00:00"}]).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/apply", data=body,
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req) as r:
            assert json.loads(r.read())["applied"] == 1
    finally:
        srv.shutdown()
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python3 -m pytest tests/test_review_server.py -q`
Expected: FAIL, ModuleNotFoundError

- [ ] **Step 3: 서버 구현**

`scripts/meetingflow/review_server.py`:

```python
"""타임블록 검토 팝업: 127.0.0.1 전용 HTTP 서버. 표준 라이브러리만 사용."""
import json
import os
import sys
import threading
import time as _time
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import calendar_io, config, notes, notify, pending, slots

PAGE = Path(__file__).with_name("review_page.html")
WEEKDAY_KO = "월화수목금토일"


# ---------- 상태 ----------

def build_state(cfg: dict, now: datetime, run=None) -> dict:
    kw = {"run": run} if run else {}
    try:
        events = calendar_io.events_between(cfg, now.date(), now.date() + timedelta(days=7), **kw)
    except Exception as e:  # noqa: BLE001
        print(f"[review] 일정 조회 실패: {e}")
        events = []
    vault_root = config.obsidian_dir(cfg).parent
    meetings = []
    for p in pending.list_pending(cfg):
        data = pending.load(p)
        items = pending.unresolved_items(data)
        if not items:
            continue
        note_path = Path(data["note_path"])
        try:
            note_url = notes.obsidian_url(cfg["OBSIDIAN_VAULT_NAME"], vault_root, note_path)
        except ValueError:
            note_url = ""
        meetings.append({
            "pending_path": str(p),
            "title": data["title"],
            "meeting_date": data["meeting_date"],
            "note_url": note_url,
            "items": slots.propose(items, events, cfg, now),
        })
    return {
        "meetings": meetings,
        "events": [{"start": datetime.fromtimestamp(e["start_ts"]).isoformat(),
                    "end": datetime.fromtimestamp(e["end_ts"]).isoformat(),
                    "title": e["title"]} for e in events if e.get("start_ts")],
        "work_hours": cfg.get("WORK_HOURS") or config.DEFAULTS["WORK_HOURS"],
        "now": now.isoformat(),
    }


# ---------- 반영 ----------

def format_timeblock_line(item: dict, start, end, applied: bool) -> str:
    if not applied:
        return f"- [ ] {item['text']} (건너뜀)"
    day = f"{start.month}/{start.day}({WEEKDAY_KO[start.weekday()]})"
    if item.get("kind") == "reminder" or end is None:
        return f"- [x] {day} {start:%H:%M} · {item['text']} · ⏰"
    return f"- [x] {day} {start:%H:%M}-{end:%H:%M} · {item['text']} · 📅"


def apply(cfg: dict, approvals: list, now: datetime, create_event=None, create_reminder=None) -> dict:
    create_event = create_event or calendar_io.create_calendar_event
    create_reminder = create_reminder or calendar_io.create_reminder
    vault_root = config.obsidian_dir(cfg).parent
    result = {"applied": 0, "skipped": 0, "failed": []}
    by_pending = {}
    for a in approvals:
        by_pending.setdefault(a["pending_path"], []).append(a)

    for ppath, group in by_pending.items():
        ppath = Path(ppath)
        data = pending.load(ppath)
        items = {i["id"]: i for i in data["items"]}
        note_path = Path(data["note_path"])
        try:
            url = notes.obsidian_url(cfg["OBSIDIAN_VAULT_NAME"], vault_root, note_path)
        except ValueError:
            url = str(note_path)
        description = f"회의: {data['title']}\n{url}"
        lines = []
        for a in group:
            item = items.get(a["id"])
            if item is None:
                continue
            if not a.get("approve"):
                pending.mark_skipped(ppath, a["id"])
                result["skipped"] += 1
                lines.append(format_timeblock_line(item, None, None, False))
                continue
            title = (a.get("title") or item["text"]).strip()
            start = datetime.fromisoformat(a["start"])
            end = datetime.fromisoformat(a["end"]) if a.get("end") else None
            kind = a.get("kind") or item["kind"]
            try:
                if kind == "reminder":
                    create_reminder(cfg, title, start, description)
                else:
                    if end is None:
                        end = start + timedelta(minutes=item.get("estimate_min") or 30)
                    create_event(cfg, title, start, end, description)
                pending.mark_applied(ppath, a["id"], now)
                result["applied"] += 1
                lines.append(format_timeblock_line({"text": title, "kind": kind}, start, end, True))
            except Exception as e:  # noqa: BLE001
                msg = str(e)
                pending.mark_error(ppath, a["id"], msg)
                result["failed"].append({"id": a["id"], "error": msg})
                print(f"[review] 반영 실패 {a['id']}: {msg}")
        if lines and note_path.exists():
            try:
                notes.append_timeblock_section(note_path, lines)
            except Exception as e:  # noqa: BLE001
                print(f"[review] 회의록 기록 실패: {e}")
        if not pending.unresolved_items(pending.load(ppath)):
            pending.move_done(cfg, ppath)
    return result


# ---------- HTTP ----------

def make_server(cfg: dict, port: int, now_fn=datetime.now, run=None,
                create_event=None, create_reminder=None, demo_state=None,
                send=notify.notify):
    last_hit = {"t": _time.time()}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # 조용히
            pass

        def _json(self, code, obj):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            last_hit["t"] = _time.time()
            if self.path == "/health":
                return self._json(200, {"app": "meetingflow"})
            if self.path.startswith("/api/state"):
                return self._json(200, demo_state or build_state(cfg, now_fn(), run=run))
            if self.path == "/":
                body = PAGE.read_text(encoding="utf-8").encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                return self.wfile.write(body)
            self._json(404, {"error": "not found"})

        def do_POST(self):
            last_hit["t"] = _time.time()
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n) if n else b"[]"
            if self.path == "/api/apply":
                try:
                    approvals = json.loads(raw.decode("utf-8"))
                    if demo_state is not None:
                        res = {"applied": sum(1 for a in approvals if a.get("approve")),
                               "skipped": sum(1 for a in approvals if not a.get("approve")), "failed": []}
                    else:
                        res = apply(cfg, approvals, now_fn(), create_event, create_reminder)
                    if res["applied"] or res["failed"]:
                        send("타임블록 반영", f"{res['applied']}건 반영, {len(res['failed'])}건 실패")
                    return self._json(200, res)
                except Exception as e:  # noqa: BLE001
                    return self._json(500, {"error": str(e)})
            if self.path == "/api/shutdown":
                self._json(200, {"ok": True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            self._json(404, {"error": "not found"})

    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    srv.last_hit = last_hit
    return srv


def serve(cfg: dict, port: int, idle_seconds: int = 600, demo_state: dict | None = None) -> None:
    srv = make_server(cfg, port, demo_state=demo_state)
    actual = srv.server_address[1]
    server_file = pending.pending_dir(cfg) / ".server.json"
    server_file.write_text(json.dumps({"port": actual, "pid": os.getpid()}), encoding="utf-8")
    print(f"[review] http://127.0.0.1:{actual}/  (유휴 {idle_seconds}s 후 종료)")

    def watchdog():
        while True:
            _time.sleep(15)
            if _time.time() - srv.last_hit["t"] > idle_seconds:
                print("[review] 유휴 종료")
                srv.shutdown()
                return
    threading.Thread(target=watchdog, daemon=True).start()
    try:
        srv.serve_forever()
    finally:
        srv.server_close()
        try:
            server_file.unlink()
        except OSError:
            pass


def main(argv=None) -> int:
    argv = argv or sys.argv[1:]
    cfg = config.load_config()
    port = config.int_cfg(cfg, "REVIEW_PORT")
    if "--port" in argv:
        port = int(argv[argv.index("--port") + 1])
    demo = None
    if "--demo" in argv:
        fix = config.REPO_DIR / "tests" / "fixtures" / "pending_demo.json"
        data = json.loads(fix.read_text(encoding="utf-8"))
        demo = {"meetings": [{"pending_path": "demo", "title": data["title"],
                              "meeting_date": data["meeting_date"], "note_url": "",
                              "items": slots.propose(data["items"], [], cfg, datetime.now())}],
                "events": [], "work_hours": cfg["WORK_HOURS"], "now": datetime.now().isoformat()}
    serve(cfg, port, demo_state=demo)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: HTML 페이지 작성**

`scripts/meetingflow/review_page.html` (외부 자원 없음, 한 파일):

```html
<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>타임블록 검토</title>
<style>
  :root { --bg:#f6f7f9; --card:#fff; --line:#e3e6ea; --text:#1d2229; --muted:#6b7480; --accent:#2f6fed; --warn:#c2410c; }
  body { margin:0; font:14px/1.5 -apple-system, "Apple SD Gothic Neo", sans-serif; background:var(--bg); color:var(--text); }
  header { padding:14px 20px; background:var(--card); border-bottom:1px solid var(--line); display:flex; justify-content:space-between; align-items:center; }
  main { display:grid; grid-template-columns: 1fr 360px; gap:16px; padding:16px 20px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:14px 16px; margin-bottom:14px; }
  h2 { margin:0 0 8px; font-size:15px; } h2 a { color:var(--muted); font-weight:normal; font-size:12px; margin-left:8px; }
  .item { display:grid; grid-template-columns: 24px 1fr; gap:8px; padding:10px 0; border-top:1px solid var(--line); }
  .item:first-of-type { border-top:none; }
  .row { display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin-top:6px; }
  input[type=text] { width:100%; padding:6px 8px; border:1px solid var(--line); border-radius:6px; font:inherit; }
  input[type=date], input[type=time], select { padding:5px 6px; border:1px solid var(--line); border-radius:6px; font:inherit; }
  .meta { color:var(--muted); font-size:12px; } .badge { font-size:11px; padding:1px 6px; border-radius:10px; background:#eef2ff; color:var(--accent); }
  .badge.warn { background:#fff1e8; color:var(--warn); }
  .day { margin-bottom:10px; } .day b { display:block; font-size:12px; color:var(--muted); margin-bottom:4px; }
  .ev { font-size:12px; padding:2px 6px; border-left:3px solid #c7ccd3; margin:2px 0; background:#fafbfc; }
  .ev.mine { border-left-color:var(--accent); background:#eef2ff; }
  .ev.conf { border-left-color:var(--warn); }
  button { padding:8px 16px; border:none; border-radius:8px; background:var(--accent); color:#fff; font:inherit; cursor:pointer; }
  button[disabled] { opacity:.5; cursor:default; } #result { margin-left:12px; color:var(--muted); }
  .empty { padding:40px; text-align:center; color:var(--muted); }
</style>
</head>
<body>
<header>
  <div><strong>타임블록 검토</strong> <span class="meta" id="count"></span></div>
  <div><button id="apply">반영</button><span id="result"></span></div>
</header>
<main>
  <section id="list"></section>
  <aside id="agenda" class="card"></aside>
</main>
<script>
const WD = "일월화수목금토";
let state = null;
const $ = (s, el=document) => el.querySelector(s);
const fmtDay = d => `${d.getMonth()+1}/${d.getDate()}(${WD[d.getDay()]})`;
const pad = n => String(n).padStart(2, "0");
const toDate = iso => iso ? new Date(iso) : null;
const dateVal = d => d ? `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}` : "";
const timeVal = d => d ? `${pad(d.getHours())}:${pad(d.getMinutes())}` : "";

async function load() {
  state = await (await fetch("/api/state")).json();
  render();
}

function itemRow(m, it) {
  const s = toDate(it.proposed_start), e = toDate(it.proposed_end);
  const dur = s && e ? (e - s) / 60000 : (it.estimate_min || 30);
  const div = document.createElement("div"); div.className = "item"; div.dataset.id = it.id; div.dataset.pending = m.pending_path;
  const badges = [];
  if (it.due_source === "next_meeting") badges.push('<span class="badge">다음 차수 기준</span>');
  if (it.due_source === "none") badges.push('<span class="badge warn">기한 없음</span>');
  if (it.overdue) badges.push('<span class="badge warn">기한 지남</span>');
  if (it.conflict) badges.push('<span class="badge warn">겹침</span>');
  if (it.owner === "공통") badges.push('<span class="badge">공통</span>');
  div.innerHTML = `
    <input type="checkbox" class="ok" ${it.default_checked ? "checked" : ""}>
    <div>
      <input type="text" class="title" value="${it.text.replace(/"/g, "&quot;")}">
      <div class="row">
        <select class="kind"><option value="block" ${it.kind==="block"?"selected":""}>📅 타임블록</option><option value="reminder" ${it.kind==="reminder"?"selected":""}>⏰ 미리알림</option></select>
        <input type="date" class="date" value="${dateVal(s)}">
        <input type="time" class="time" step="1800" value="${timeVal(s)}">
        <select class="dur">${[30,60,90,120,180].map(v=>`<option value="${v}" ${v===dur?"selected":""}>${v}분</option>`).join("")}</select>
        <span class="meta">기한 ${it.due || "없음"} ${badges.join(" ")}</span>
      </div>
    </div>`;
  div.addEventListener("input", renderAgenda);
  return div;
}

function render() {
  const list = $("#list"); list.innerHTML = "";
  let n = 0;
  for (const m of state.meetings) {
    const card = document.createElement("div"); card.className = "card";
    card.innerHTML = `<h2>${m.title} <a href="${m.note_url}">${m.meeting_date} 회의록 열기</a></h2>`;
    for (const it of m.items) { card.appendChild(itemRow(m, it)); n++; }
    list.appendChild(card);
  }
  if (!n) { list.innerHTML = '<div class="empty">검토할 후보가 없습니다.</div>'; $("#apply").disabled = true; }
  $("#count").textContent = n ? `후보 ${n}건` : "";
  renderAgenda();
}

function proposals() {
  return [...document.querySelectorAll(".item")].map(div => {
    const kind = $(".kind", div).value, date = $(".date", div).value, time = $(".time", div).value;
    const start = date && time ? new Date(`${date}T${time}:00`) : null;
    const end = start && kind === "block" ? new Date(start.getTime() + Number($(".dur", div).value) * 60000) : null;
    return { pending_path: div.dataset.pending, id: div.dataset.id, approve: $(".ok", div).checked,
             kind, title: $(".title", div).value, start, end };
  });
}

function renderAgenda() {
  const ag = $("#agenda"); ag.innerHTML = `<h2>앞으로 7일 일정 <span class="meta">(${state.work_hours})</span></h2>`;
  const props = proposals().filter(p => p.approve && p.start);
  const days = {};
  const add = (d, html) => { const k = dateVal(d); (days[k] ||= []).push([d, html]); };
  for (const ev of state.events) add(new Date(ev.start), `<div class="ev">${timeVal(new Date(ev.start))}-${timeVal(new Date(ev.end))} ${ev.title}</div>`);
  for (const p of props) {
    const clash = state.events.some(ev => p.end && new Date(ev.start) < p.end && p.start < new Date(ev.end));
    const t = p.end ? `${timeVal(p.start)}-${timeVal(p.end)}` : `${timeVal(p.start)} ⏰`;
    add(p.start, `<div class="ev mine ${clash ? "conf" : ""}">${t} ${p.title}</div>`);
  }
  const base = new Date(state.now); base.setHours(0,0,0,0);
  for (let i = 0; i < 8; i++) {
    const d = new Date(base.getTime() + i * 86400000); const k = dateVal(d);
    const rows = (days[k] || []).sort((a, b) => a[0] - b[0]).map(r => r[1]).join("") || '<div class="ev meta">일정 없음</div>';
    ag.insertAdjacentHTML("beforeend", `<div class="day"><b>${fmtDay(d)}</b>${rows}</div>`);
  }
}

$("#apply").addEventListener("click", async () => {
  const body = proposals().map(p => ({ ...p, start: p.start ? localIso(p.start) : null, end: p.end ? localIso(p.end) : null }));
  if (body.some(p => p.approve && !p.start)) { $("#result").textContent = "승인한 항목에 날짜·시간을 채워 주세요."; return; }
  $("#apply").disabled = true; $("#result").textContent = "반영 중…";
  const res = await (await fetch("/api/apply", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })).json();
  $("#result").textContent = res.error ? `오류: ${res.error}` : `${res.applied}건 반영, ${res.skipped}건 건너뜀${res.failed.length ? `, ${res.failed.length}건 실패` : ""}`;
  await load(); $("#apply").disabled = false;
  if (!state.meetings.length && !res.failed.length) setTimeout(() => fetch("/api/shutdown", { method: "POST" }).then(() => window.close()), 1500);
});

function localIso(d) { return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:00`; }
load();
</script>
</body>
</html>
```

- [ ] **Step 5: 통과 확인**

Run: `.venv/bin/python3 -m pytest tests/test_review_server.py -q`
Expected: 5 passed. `test_build_state_lists_unresolved_with_proposals`에서 a1(90분)이 10/13 16:30-18:00에 먼저 배치되고, b2(60분)는 그 앞 15:30-16:30에 배치된다.

- [ ] **Step 6: 런처 작성**

`scripts/review-open.py`:

```python
#!/usr/bin/env python3
"""검토 팝업 열기: 서버가 없으면 띄우고, 브라우저를 앱 모드로 연다. 표준 라이브러리만 사용."""
import json
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from meetingflow import config, pending  # noqa: E402


def _healthy(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as r:
            return json.loads(r.read()).get("app") == "meetingflow"
    except Exception:  # noqa: BLE001
        return False


def _port_in_use(port: int) -> bool:
    import socket
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def main() -> int:
    cfg = config.load_config()
    server_file = pending.pending_dir(cfg) / ".server.json"
    port = config.int_cfg(cfg, "REVIEW_PORT")
    if server_file.exists():
        try:
            port = int(json.loads(server_file.read_text())["port"])
        except Exception:  # noqa: BLE001
            pass
    if not _healthy(port):
        port = config.int_cfg(cfg, "REVIEW_PORT")
        while _port_in_use(port):  # 다른 프로세스가 잡고 있으면 다음 포트
            port += 1
        pybin = sys.executable
        subprocess.Popen([pybin, "-m", "meetingflow.review_server", "--port", str(port)],
                         cwd=str(Path(__file__).resolve().parent),
                         stdout=open(config.meetings_dir(cfg) / ".review.log", "a"),
                         stderr=subprocess.STDOUT, start_new_session=True)
        for _ in range(40):
            if _healthy(port):
                break
            time.sleep(0.25)
    url = f"http://127.0.0.1:{port}/"
    chrome = "/Applications/Google Chrome.app"
    if Path(chrome).exists():
        subprocess.run(["open", "-na", "Google Chrome", "--args", f"--app={url}", "--window-size=1100,760"], check=False)
    else:
        subprocess.run(["open", url], check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

`scripts/review-open.sh` 전체를 아래로 교체:

```bash
#!/bin/bash
# 타임블록 검토 팝업을 연다. 알림 클릭(terminal-notifier -execute)과
# Raycast/Quick Action 트리거가 공용으로 사용한다.
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYBIN="$SCRIPT_DIR/../.venv/bin/python3"
[[ -x "$PYBIN" ]] || PYBIN="python3"
exec "$PYBIN" "$SCRIPT_DIR/review-open.py"
```

- [ ] **Step 7: 데모 화면 수동 확인**

Run: `cd scripts && ../.venv/bin/python3 -m meetingflow.review_server --demo --port 47399 &` 후 브라우저에서 `http://127.0.0.1:47399/` 열기. 후보 4건과 7일 일정 패널이 보이고, 시간을 바꾸면 오른쪽 패널의 파란 블록이 움직이는지 확인한다. 확인 후 `curl -X POST http://127.0.0.1:47399/api/shutdown`.
Expected: 화면 정상, 콘솔 오류 없음

- [ ] **Step 8: 전체 테스트와 커밋**

Run: `.venv/bin/python3 -m pytest -q`
Expected: 모두 통과

```bash
chmod +x scripts/review-open.sh scripts/review-open.py
git add scripts/meetingflow/review_server.py scripts/meetingflow/review_page.html scripts/review-open.py scripts/review-open.sh tests/test_review_server.py tests/fixtures/pending_demo.json
git commit -m "타임블록 검토 팝업 서버 추가: 후보 편집·7일 일정·캘린더 반영·회의록 기록"
```

---

### Task 10: 수동 트리거 (Raycast / Quick Action)

**Files:**
- Create: `scripts/review-timeblocks.sh`
- Modify: `scripts/install-quick-actions.sh` (항목 추가, 안내 문구 갱신)

**Interfaces:**
- Consumes: `scripts/review-open.sh`
- Produces: Raycast 스크립트 커맨드 `타임블록 검토`, Quick Action `타임블록 검토`

- [ ] **Step 1: Raycast 래퍼 작성**

`scripts/review-timeblocks.sh`:

```bash
#!/bin/bash

# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title 타임블록 검토
# @raycast.mode silent
# @raycast.packageName Meeting Flow

# Optional parameters:
# @raycast.icon 📅

set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/review-open.sh"
```

```bash
chmod +x scripts/review-timeblocks.sh
```

- [ ] **Step 2: Quick Action 설치기에 항목 추가**

`scripts/install-quick-actions.sh`에서 `install_quick_action "미팅 끝" ...` 줄 아래에 추가:

```bash
install_quick_action "타임블록 검토" "\"$REPO_DIR/scripts/review-open.sh\"" "review"
```

같은 파일의 실행 권한 검사 조건에 `review-open.sh`를 추가:

```bash
if [[ ! -x "$SCRIPT_DIR/meeting-start.sh" || ! -x "$SCRIPT_DIR/meeting-end.sh" || ! -x "$SCRIPT_DIR/review-open.sh" ]]; then
```

안내 heredoc의 `Quick Action 3개를` → `Quick Action 4개를`, 목록에 `  - 타임블록 검토` 한 줄 추가, `위 3개 항목을` → `위 4개 항목을`.

- [ ] **Step 3: 설치 실행으로 확인**

Run: `./scripts/install-quick-actions.sh && ls ~/Library/Services | grep 타임블록`
Expected: `설치: 타임블록 검토` 출력, `타임블록 검토.workflow` 존재

- [ ] **Step 4: 커밋**

```bash
git add scripts/review-timeblocks.sh scripts/install-quick-actions.sh
git commit -m "타임블록 검토 수동 트리거 추가 (Raycast 커맨드, Quick Action)"
```

---

### Task 11: 브리핑 생성 (`brief.py`)

**Files:**
- Create: `scripts/meetingflow/brief.py`
- Create: `templates/brief.md`
- Create: `tests/test_brief.py`
- Create: `tests/fixtures/str_weekly_2026-09-30.md` (결정 사항·액션 아이템이 다른 지난 회차)

**Interfaces:**
- Consumes: `notes.find_notes_by_title/split_frontmatter/frontmatter_list/body_before_transcript/extract_section/parse_action_items/normalize_title`, `config.*`, `actions.call_claude`
- Produces:
  - `brief.brief_path(cfg, day: date, title: str) -> Path` (`briefs_dir / f"{day:%Y-%m-%d}_{normalize_title(title)}.md"`)
  - `brief.collect(cfg, title: str, attendees: list[str], now: datetime) -> dict` → `{"sources": [Path], "decisions": [{"date","note","lines":[str]}], "open_items": [{"date","note","owner","text"}], "timeblocks": [{"date","note","lines"}], "projects": [{"name","excerpt"}], "fallback": "same_title"|"attendees"|"none"}`
  - `brief.render_fact_sections(collected: dict, my_names: list[str]) -> tuple[str, str]` (결정 사항 md, 미완료 액션 아이템 md; 내 것 먼저)
  - `brief.build_prompt(title: str, event_start: datetime, attendees: list[str], collected: dict, decisions_md: str, open_md: str) -> str`
  - `brief.parse_sections(text: str) -> dict` (`{"context": str, "projects": str, "questions": str}`; `### CONTEXT`, `### PROJECTS`, `### QUESTIONS` 구분자)
  - `brief.generate_brief(cfg, title: str, event_start: datetime, attendees: list[str], now: datetime, call=None) -> Path`
  - 템플릿 `templates/brief.md`의 자리표시: `{{title}}`, `{{date}}`, `{{event_time}}`, `{{sources}}`, `{{context}}`, `{{decisions}}`, `{{open_items}}`, `{{projects}}`, `{{questions}}`

- [ ] **Step 1: fixture 작성**

`tests/fixtures/str_weekly_2026-09-30.md`:

```markdown
---
title: "[11층 몰디브] STR Weekly"
date: 2026-09-30
time: 10:00 - 11:00
duration: 60분
participants: [Jennifer, Claud, Alex]
projects: ["[[ax-view360]]"]
tags: [meeting]
---

# [11층 몰디브] STR Weekly

## 📢 결정 사항

- 데이터 요건은 티나가 정리한다.

## ✅ 액션 아이템

- [ ] **Claud**: 보안 테스트 TC 초안 공유
- [x] **Alex**: 챔피언 명단 1차 전달
- [ ] **Jennifer**: 요건 정의서 초안

## 📅 타임블록

- [x] 10/2(목) 14:00-15:00 · 보안 테스트 TC 초안 공유 · 📅

---

## 전체 전사록 (화자분리)

**화자1**: 지난 주 이야기.
```

- [ ] **Step 2: 실패하는 테스트 작성**

`tests/test_brief.py`:

```python
import shutil
from datetime import date, datetime
from pathlib import Path

from meetingflow import brief, notes

FIX = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 14, 9, 45)
START = datetime(2026, 10, 14, 10, 0)
TITLE = "[11층 몰디브] STR Weekly"

CLAUDE = """### CONTEXT
STR 주간 회의로, CIS 발표 준비와 BI 요건 정리가 이어지는 자리입니다.
### PROJECTS
- [[ax-view360]]: BI 요건 정의서가 진행 중이며 데이터 요건 싱크가 남아 있습니다.
### QUESTIONS
1. CIS 발표 자료 재구성은 끝났는가?
2. DBA 담당자는 확정되었는가?
"""


def _seed(cfg):
    md = Path(cfg["OBSIDIAN_DIR"])
    shutil.copy(FIX / "str_weekly_2026-10-07.md", md / "2026-10-07_1005_[11층 몰디브] STR Weekly.md")
    shutil.copy(FIX / "str_weekly_2026-09-30.md", md / "2026-09-30_1000_[11층 몰디브] STR Weekly.md")
    shutil.copy(FIX / "str_weekly_2026-10-07.md", md / "2026-10-07_1500_법무 RNR.md")
    proj = Path(cfg["PROJECTS_DIR"]) / "ax-view360.md"
    proj.write_text("# ax-view360\n\nBI 대시보드 프로젝트.\n" + "내용 " * 1000, encoding="utf-8")


def test_brief_path(cfg):
    p = brief.brief_path(cfg, date(2026, 10, 14), "[11층 몰디브]  STR Weekly")
    assert p == Path(cfg["OBSIDIAN_DIR"]) / "_briefs" / "2026-10-14_[11층 몰디브] STR Weekly.md"


def test_collect_same_title_newest_first(cfg):
    _seed(cfg)
    c = brief.collect(cfg, TITLE, ["Claud", "Jennifer"], NOW)
    assert c["fallback"] == "same_title"
    assert [p.name[:10] for p in c["sources"]] == ["2026-10-07", "2026-09-30"]
    assert c["decisions"][0]["date"] == "2026-10-07" and "에반젤리스트" in c["decisions"][0]["lines"][0]
    owners = [(i["date"], i["owner"]) for i in c["open_items"]]
    assert ("2026-10-07", "Jennifer") in owners and ("2026-09-30", "Claud") in owners
    assert all(not i.get("done") for i in c["open_items"])  # 완료 항목 제외
    assert c["timeblocks"][0]["date"] == "2026-09-30"
    assert c["projects"][0]["name"] == "ax-view360" and len(c["projects"][0]["excerpt"]) <= 1500


def test_collect_respects_history_count(cfg):
    _seed(cfg)
    cfg["BRIEF_HISTORY_COUNT"] = "1"
    c = brief.collect(cfg, TITLE, [], NOW)
    assert len(c["sources"]) == 1


def test_collect_attendee_fallback(cfg):
    _seed(cfg)
    c = brief.collect(cfg, "처음 하는 회의", ["Claud", "Alex"], NOW)
    assert c["fallback"] == "attendees"
    assert c["sources"]  # 참석자 둘 이상 겹치는 회의록
    c2 = brief.collect(cfg, "처음 하는 회의", ["Nobody"], NOW)
    assert c2["fallback"] == "none" and c2["sources"] == []


def test_render_fact_sections_mine_first(cfg):
    _seed(cfg)
    c = brief.collect(cfg, TITLE, [], NOW)
    decisions_md, open_md = brief.render_fact_sections(c, ["Claud"])
    assert decisions_md.index("2026-10-07") < decisions_md.index("2026-09-30")
    assert "[[2026-10-07_1005_[11층 몰디브] STR Weekly]]" in decisions_md
    first_owner_line = [l for l in open_md.splitlines() if l.startswith("**")][0]
    assert first_owner_line.startswith("**Claud")
    assert "공통" in open_md and "Jennifer" in open_md


def test_build_prompt_and_parse_sections(cfg):
    _seed(cfg)
    c = brief.collect(cfg, TITLE, ["Claud"], NOW)
    d, o = brief.render_fact_sections(c, ["Claud"])
    p = brief.build_prompt(TITLE, START, ["Claud"], c, d, o)
    assert "### CONTEXT" in p and "### PROJECTS" in p and "### QUESTIONS" in p
    assert "ax-view360" in p and "에반젤리스트" in p
    sec = brief.parse_sections(CLAUDE)
    assert sec["context"].startswith("STR 주간 회의")
    assert "[[ax-view360]]" in sec["projects"] and sec["questions"].startswith("1.")


def test_generate_brief_writes_note(cfg):
    _seed(cfg)
    path = brief.generate_brief(cfg, TITLE, START, ["Claud", "Jennifer"], NOW, call=lambda c, p: CLAUDE)
    assert path == brief.brief_path(cfg, date(2026, 10, 14), TITLE)
    text = path.read_text(encoding="utf-8")
    fm, body = notes.split_frontmatter(text)
    assert fm["tags"] == "[brief]"
    assert fm["event_time"] == "10:00 - 11:00"
    assert "[[2026-10-07_1005_[11층 몰디브] STR Weekly]]" in fm["sources"]
    for h in ("## 🧭 한 줄 맥락", "## 📌 지난 결정 사항", "## ⏳ 미완료 액션 아이템",
              "## 🔗 관련 프로젝트 근황", "## ❓ 이번 회의에서 확인할 것"):
        assert h in body
    assert "에반젤리스트" in body and "DBA 담당자는 확정되었는가" in body


def test_generate_brief_without_history_uses_short_form(cfg):
    _seed(cfg)
    path = brief.generate_brief(cfg, "완전히 새 회의", START, ["Nobody"], NOW,
                                call=lambda c, p: "### CONTEXT\n새 회의\n### PROJECTS\n없음\n### QUESTIONS\n없음\n")
    body = path.read_text(encoding="utf-8")
    assert "지난 회의록 없음" in body
```

- [ ] **Step 3: 실패 확인**

Run: `.venv/bin/python3 -m pytest tests/test_brief.py -q`
Expected: FAIL, ModuleNotFoundError

- [ ] **Step 4: 템플릿 작성**

`templates/brief.md`:

```markdown
---
title: "{{title}}"
date: {{date}}
event_time: {{event_time}}
sources: [{{sources}}]
tags: [brief]
---

# 브리핑: {{title}}

## 🧭 한 줄 맥락

{{context}}

## 📌 지난 결정 사항

{{decisions}}

## ⏳ 미완료 액션 아이템

{{open_items}}

## 🔗 관련 프로젝트 근황

{{projects}}

## ❓ 이번 회의에서 확인할 것

{{questions}}
```

- [ ] **Step 5: 구현**

`scripts/meetingflow/brief.py`:

```python
"""회의 전 브리핑. 사실(결정·미완료 항목)은 코드가 모으고, 서술은 Claude가 쓴다."""
import re
from datetime import date, datetime, timedelta
from pathlib import Path

from . import config, notes

PROJECT_EXCERPT_CHARS = 1500
ATTENDEE_FALLBACK_DAYS = 30


def brief_path(cfg: dict, day: date, title: str) -> Path:
    return config.briefs_dir(cfg) / f"{day:%Y-%m-%d}_{notes.normalize_title(title)}.md"


def _note_date(path: Path) -> str:
    return path.name[:10]


def _notes_by_attendees(meetings_dir: Path, attendees: list, now: datetime, limit: int) -> list:
    want = {a.lower() for a in attendees}
    since = (now - timedelta(days=ATTENDEE_FALLBACK_DAYS)).strftime("%Y-%m-%d")
    hits = []
    for p in sorted(meetings_dir.glob("*.md"), key=lambda p: p.name, reverse=True):
        if _note_date(p) < since:
            continue
        fm, _ = notes.split_frontmatter(p.read_text(encoding="utf-8"))
        have = {a.lower() for a in notes.frontmatter_list(fm.get("participants", ""))}
        if len(want & have) >= 2:
            hits.append(p)
        if len(hits) >= limit:
            break
    return hits


def collect(cfg: dict, title: str, attendees: list, now: datetime) -> dict:
    meetings_dir = config.obsidian_dir(cfg)
    limit = config.int_cfg(cfg, "BRIEF_HISTORY_COUNT")
    sources = notes.find_notes_by_title(meetings_dir, title)[:limit]
    fallback = "same_title"
    if not sources:
        sources = _notes_by_attendees(meetings_dir, attendees, now, 3)
        fallback = "attendees" if sources else "none"

    decisions, open_items, timeblocks, project_names = [], [], [], []
    for p in sources:
        text = p.read_text(encoding="utf-8")
        fm, _ = notes.split_frontmatter(text)
        body = notes.body_before_transcript(text)
        d = _note_date(p)
        dec = [l.strip() for l in notes.extract_section(body, "결정 사항").splitlines()
               if l.strip() and l.strip() != "없음"]
        if dec:
            decisions.append({"date": d, "note": p.stem, "lines": dec})
        for it in notes.parse_action_items(notes.extract_section(body, "액션 아이템")):
            if not it["done"]:
                open_items.append({"date": d, "note": p.stem, "owner": it["owner"], "text": it["text"]})
        tb = [l.strip() for l in notes.extract_section(body, "타임블록").splitlines() if l.strip()]
        if tb:
            timeblocks.append({"date": d, "note": p.stem, "lines": tb})
        for name in notes.frontmatter_list(fm.get("projects", "")):
            name = name.strip("[]")
            if name and name not in project_names:
                project_names.append(name)

    projects = []
    proj_dir = Path(cfg.get("PROJECTS_DIR") or "")
    if cfg.get("PROJECTS_DIR") and proj_dir.is_dir():
        for name in project_names:
            hits = list(proj_dir.rglob(f"{name}.md"))
            if hits:
                projects.append({"name": name,
                                 "excerpt": hits[0].read_text(encoding="utf-8")[:PROJECT_EXCERPT_CHARS]})
    return {"sources": sources, "decisions": decisions, "open_items": open_items,
            "timeblocks": timeblocks, "projects": projects, "fallback": fallback}


def render_fact_sections(collected: dict, my_names: list) -> tuple:
    if not collected["sources"]:
        return "지난 회의록 없음", "지난 회의록 없음"
    dec_parts = []
    for d in collected["decisions"]:
        dec_parts.append(f"**{d['date']}** ([[{d['note']}]])\n" + "\n".join(d["lines"]))
    decisions_md = "\n\n".join(dec_parts) or "없음"

    mine = {n.lower() for n in my_names}
    def rank(owner: str) -> int:
        o = owner.lower()
        return 0 if o in mine else (1 if o == "공통" else 2)
    groups = {}
    for it in collected["open_items"]:
        groups.setdefault(it["owner"] or "담당자 미상", []).append(it)
    open_parts = []
    for owner in sorted(groups, key=lambda o: (rank(o), o)):
        lines = "\n".join(f"- [ ] {i['text']} ({i['date']}, [[{i['note']}]])" for i in groups[owner])
        open_parts.append(f"**{owner}**\n{lines}")
    open_md = "\n\n".join(open_parts) or "없음"
    if collected["timeblocks"]:
        tb = "\n".join(f"- {t['date']}: " + " / ".join(t["lines"]) for t in collected["timeblocks"])
        open_md += f"\n\n내가 캘린더에 올렸던 항목:\n{tb}"
    return decisions_md, open_md


def build_prompt(title: str, event_start: datetime, attendees: list, collected: dict,
                 decisions_md: str, open_md: str) -> str:
    proj = "\n\n".join(f"[[{p['name']}]]\n{p['excerpt']}" for p in collected["projects"]) or "없음"
    return f"""곧 시작하는 회의를 위한 브리핑의 서술 부분을 작성해주세요.

회의: {title}
시작: {event_start:%Y-%m-%d %H:%M}
참석자: {", ".join(attendees) or "미상"}
참고한 지난 회의록 수: {len(collected["sources"])} ({collected["fallback"]})

[지난 결정 사항]
{decisions_md}

[미완료 액션 아이템]
{open_md}

[관련 프로젝트 노트 발췌]
{proj}

아래 세 구분자를 정확히 사용해 한국어로 출력하세요. 다른 섹션이나 머리말은 쓰지 마세요.
위 자료에 없는 사실을 만들어 내지 마세요.

### CONTEXT
(이 회의가 무엇을 이어 가는 자리인지 한두 문장)
### PROJECTS
(프로젝트별로 "- [[노트명]]: 두세 줄 근황". 자료가 없으면 "없음")
### QUESTIONS
(미완료 항목과 결정 사항에서 도출한, 이번 회의에서 확인할 질문 3개 이내. 번호 목록)"""


def parse_sections(text: str) -> dict:
    out = {"context": "", "projects": "", "questions": ""}
    pattern = re.compile(r"###\s*(CONTEXT|PROJECTS|QUESTIONS)\s*\n(.*?)(?=###\s*(?:CONTEXT|PROJECTS|QUESTIONS)|\Z)", re.S)
    for m in pattern.finditer(text):
        out[m.group(1).lower()] = m.group(2).strip()
    return out


def generate_brief(cfg: dict, title: str, event_start: datetime, attendees: list,
                   now: datetime, call=None) -> Path:
    from .actions import call_claude  # requests 지연 import
    call = call or call_claude
    collected = collect(cfg, title, attendees, now)
    decisions_md, open_md = render_fact_sections(collected, config.my_names(cfg))
    sections = parse_sections(call(cfg, build_prompt(title, event_start, attendees, collected,
                                                     decisions_md, open_md)))
    tmpl = (config.TEMPLATES_DIR / "brief.md").read_text(encoding="utf-8")
    end = event_start + timedelta(hours=1)
    filled = (tmpl
              .replace("{{title}}", title.replace('"', "'"))
              .replace("{{date}}", f"{event_start:%Y-%m-%d}")
              .replace("{{event_time}}", f"{event_start:%H:%M} - {end:%H:%M}")
              .replace("{{sources}}", ", ".join(f'"[[{p.stem}]]"' for p in collected["sources"]))
              .replace("{{context}}", sections["context"] or "(생성 실패)")
              .replace("{{decisions}}", decisions_md)
              .replace("{{open_items}}", open_md)
              .replace("{{projects}}", sections["projects"] or "없음")
              .replace("{{questions}}", sections["questions"] or "없음"))
    path = brief_path(cfg, event_start.date(), title)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(filled, encoding="utf-8")
    print(f"[brief] {path}")
    return path
```

- [ ] **Step 6: 통과 확인**

Run: `.venv/bin/python3 -m pytest tests/test_brief.py -q`
Expected: 8 passed. 이벤트 종료 시각은 icalBuddy 이벤트의 실제 종료를 Task 12에서 넘기지 않으므로 여기서는 시작 + 1시간으로 둔다.

- [ ] **Step 7: 커밋**

```bash
git add scripts/meetingflow/brief.py templates/brief.md tests/test_brief.py tests/fixtures/str_weekly_2026-09-30.md
git commit -m "회의 전 브리핑 생성 모듈 추가: 지난 결정·미완료 항목 수집, Claude 서술 조립"
```

---

### Task 12: 틱 스케줄러와 launchd 설치

**Files:**
- Create: `scripts/tick.py`
- Create: `scripts/install-launchd.sh`
- Create: `tests/test_tick.py`

**Interfaces:**
- Consumes: `pending.list_pending/load/needs_renotify/mark_renotified/expire_old/cleanup`, `calendar_io.events_today`, `notes.find_notes_by_title/normalize_title`, `brief.brief_path/generate_brief` (지연 import), `notify.notify`, `config.*`
- Produces:
  - `tick.acquire_lock(lock_path: Path, pid: int, alive=os.kill 기반) -> bool`
  - `tick.step_renotify(cfg, now: datetime, dry_run: bool, send=notify.notify) -> int` (보낸 알림 수)
  - `tick.brief_candidates(cfg, events: list[dict], now: datetime) -> list[dict]` (조건을 만족하고 아직 파일이 없는 이벤트)
  - `tick.step_briefs(cfg, now: datetime, dry_run: bool, events=None, generate=None, send=notify.notify) -> int` (생성 수)
  - `tick.step_cleanup(cfg, now: datetime, dry_run: bool) -> int`
  - `tick.main(argv) -> int` (`--dry-run` 지원)
  - `.pending/.brief_attempts.json`: `{"<YYYY-MM-DD>_<정규화 제목>": 시도 횟수}`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_tick.py`:

```python
import json
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path

import tick
from meetingflow import brief, pending

FIX = Path(__file__).parent / "fixtures"
TITLE = "[11층 몰디브] STR Weekly"


def _ev(title, start: datetime, minutes=60, attendees=("a.kim",)):
    return {"title": title, "attendees": list(attendees),
            "start_ts": int(start.timestamp()), "end_ts": int((start + timedelta(minutes=minutes)).timestamp())}


def _seed_history(cfg):
    shutil.copy(FIX / "str_weekly_2026-10-07.md",
                Path(cfg["OBSIDIAN_DIR"]) / "2026-10-07_1005_[11층 몰디브] STR Weekly.md")


def test_acquire_lock_rejects_live_pid(tmp_path):
    lock = tmp_path / "t.lock"
    assert tick.acquire_lock(lock, 111, alive=lambda pid: False)
    assert lock.read_text() == "111"
    assert not tick.acquire_lock(lock, 222, alive=lambda pid: pid == 111)
    assert tick.acquire_lock(lock, 333, alive=lambda pid: False)  # 죽은 pid는 덮어씀


def test_step_renotify_sends_once_per_day_and_expires(cfg):
    note = Path(cfg["OBSIDIAN_DIR"]) / "2026-10-07_1005_x.md"; note.write_text("x")
    items = [{"id": "a", "text": "t", "owner": "Claud", "is_mine": True, "due": None,
              "due_source": "none", "kind": "block", "estimate_min": 30}]
    pending.new_pending(cfg, note, "x", date(2026, 10, 7), items, datetime(2026, 10, 7, 11, 40))
    sent = []
    send = lambda *a, **k: sent.append((a, k))
    assert tick.step_renotify(cfg, datetime(2026, 10, 8, 9, 5), False, send=send) == 1
    assert "미처리 타임블록 후보 1건" in sent[0][0][1] and sent[0][1]["execute"].endswith("review-open.sh")
    assert tick.step_renotify(cfg, datetime(2026, 10, 8, 9, 10), False, send=send) == 0
    assert tick.step_renotify(cfg, datetime(2026, 10, 15, 9, 0), False, send=send) == 0  # 7일 경과 → 만료
    assert pending.list_pending(cfg) == [] and (pending.pending_dir(cfg) / "expired").exists()


def test_step_renotify_dry_run_changes_nothing(cfg):
    note = Path(cfg["OBSIDIAN_DIR"]) / "n.md"; note.write_text("x")
    items = [{"id": "a", "text": "t", "owner": "Claud", "is_mine": True, "due": None,
              "due_source": "none", "kind": "block", "estimate_min": 30}]
    p = pending.new_pending(cfg, note, "x", date(2026, 10, 7), items, datetime(2026, 10, 7))
    sent = []
    assert tick.step_renotify(cfg, datetime(2026, 10, 8, 9, 5), True, send=lambda *a, **k: sent.append(1)) == 1
    assert sent == [] and pending.load(p)["renotified_on"] is None


def test_brief_candidates_rules(cfg):
    _seed_history(cfg)
    now = datetime(2026, 10, 14, 9, 50)
    evs = [
        _ev(TITLE, datetime(2026, 10, 14, 10, 0)),            # 10분 전, 지난 회의록 있음 → 대상
        _ev("새 회의 [brief]", datetime(2026, 10, 14, 10, 0)),  # 강제 표식 → 대상
        _ev("새 회의", datetime(2026, 10, 14, 10, 0)),          # 둘 다 아님 → 제외
        _ev(TITLE, datetime(2026, 10, 14, 11, 0)),            # 70분 전 → 제외
        _ev(TITLE, datetime(2026, 10, 14, 9, 30)),            # 20분 지남 → 제외
    ]
    got = [e["title"] for e in tick.brief_candidates(cfg, evs, now)]
    assert got == [TITLE, "새 회의 [brief]"]


def test_brief_window_allows_5min_late(cfg):
    _seed_history(cfg)
    ev = _ev(TITLE, datetime(2026, 10, 14, 10, 0))
    assert tick.brief_candidates(cfg, [ev], datetime(2026, 10, 14, 10, 4)) == [ev]
    assert tick.brief_candidates(cfg, [ev], datetime(2026, 10, 14, 10, 6)) == []


def test_brief_not_regenerated_if_exists(cfg):
    _seed_history(cfg)
    ev = _ev(TITLE, datetime(2026, 10, 14, 10, 0))
    now = datetime(2026, 10, 14, 9, 50)
    p = brief.brief_path(cfg, date(2026, 10, 14), TITLE)
    p.parent.mkdir(parents=True); p.write_text("이미 있음")
    assert tick.brief_candidates(cfg, [ev], now) == []


def test_step_briefs_generates_and_notifies(cfg):
    _seed_history(cfg)
    now = datetime(2026, 10, 14, 9, 50)
    ev = _ev(TITLE, datetime(2026, 10, 14, 10, 0), attendees=("a.kim", "b.lee"))
    sent, gen = [], []

    def fake_generate(c, title, start, attendees, n):
        gen.append((title, attendees))
        p = brief.brief_path(c, start.date(), title); p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("b"); return p
    assert tick.step_briefs(cfg, now, False, events=[ev], generate=fake_generate,
                            send=lambda *a, **k: sent.append((a, k))) == 1
    assert gen == [(TITLE, ["a.kim", "b.lee"])]
    assert sent[0][1]["open_url"].startswith("obsidian://open?vault=_obsidian&file=Meetings%2F_briefs%2F")


def test_step_briefs_retries_at_most_twice(cfg):
    _seed_history(cfg)
    now = datetime(2026, 10, 14, 9, 50)
    ev = _ev(TITLE, datetime(2026, 10, 14, 10, 0))
    calls = []

    def boom(*a):
        calls.append(1); raise RuntimeError("api down")
    for _ in range(4):
        tick.step_briefs(cfg, now, False, events=[ev], generate=boom, send=lambda *a, **k: None)
    assert len(calls) == 2
    attempts = json.loads((pending.pending_dir(cfg) / ".brief_attempts.json").read_text())
    assert attempts == {f"2026-10-14_{TITLE}": 2}


def test_step_briefs_dry_run_does_not_generate(cfg):
    _seed_history(cfg)
    ev = _ev(TITLE, datetime(2026, 10, 14, 10, 0))
    called = []
    assert tick.step_briefs(cfg, datetime(2026, 10, 14, 9, 50), True, events=[ev],
                            generate=lambda *a: called.append(1), send=lambda *a, **k: None) == 1
    assert called == []
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python3 -m pytest tests/test_tick.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'tick'`

- [ ] **Step 3: 구현**

`scripts/tick.py`:

```python
#!/usr/bin/env python3
"""launchd가 5분마다 실행하는 가벼운 틱.
  1) 미처리 타임블록 후보 아침 재알림 / 만료
  2) 곧 시작하는 회의의 브리핑 생성
  3) done/, expired/ 정리
표준 라이브러리만 import한다. 브리핑 생성(requests)은 필요할 때만 지연 import."""
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from meetingflow import calendar_io, config, notes, notify, pending  # noqa: E402

REVIEW_OPEN = Path(__file__).resolve().parent / "review-open.sh"
LATE_GRACE_MIN = 5
MAX_BRIEF_ATTEMPTS = 2
LOG_MAX_BYTES = 1_000_000


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def acquire_lock(lock_path: Path, pid: int, alive=_pid_alive) -> bool:
    if lock_path.exists():
        try:
            other = int(lock_path.read_text().strip() or 0)
        except ValueError:
            other = 0
        if other and other != pid and alive(other):
            return False
    lock_path.write_text(str(pid))
    return True


# ---------- 1. 재알림 ----------

def step_renotify(cfg: dict, now: datetime, dry_run: bool, send=notify.notify) -> int:
    expire_days = config.int_cfg(cfg, "PENDING_EXPIRE_DAYS")
    if not dry_run:
        pending.expire_old(cfg, now, expire_days)
    remind_at = config.parse_hhmm(cfg.get("MORNING_REMIND_AT") or config.DEFAULTS["MORNING_REMIND_AT"])
    due = []
    for p in pending.list_pending(cfg):
        data = pending.load(p)
        if dry_run and datetime.strptime(data["created_at"], pending.ISO) + timedelta(days=expire_days) <= now:
            continue
        if pending.unresolved_items(data) and pending.needs_renotify(data, now, remind_at):
            due.append((p, data))
    if not due:
        return 0
    n = sum(len(pending.unresolved_items(d)) for _, d in due)
    print(f"[tick] 미처리 후보 {n}건 ({len(due)}개 회의) 재알림{' (dry-run)' if dry_run else ''}")
    if not dry_run:
        send("타임블록 후보 📅", f"미처리 타임블록 후보 {n}건 (클릭하면 검토)",
             execute=str(REVIEW_OPEN), group="meetingflow-review")
        for p, _ in due:
            pending.mark_renotified(p, now.date())
    return 1


# ---------- 2. 브리핑 ----------

def _attempts_path(cfg: dict) -> Path:
    return pending.pending_dir(cfg) / ".brief_attempts.json"


def _load_attempts(cfg: dict) -> dict:
    p = _attempts_path(cfg)
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except json.JSONDecodeError:
        return {}


def brief_candidates(cfg: dict, events: list, now: datetime) -> list:
    from meetingflow import brief  # 표준 라이브러리만 쓰는 모듈이지만 tick 상단을 가볍게 유지
    lead = timedelta(minutes=config.int_cfg(cfg, "BRIEF_LEAD_MIN"))
    grace = timedelta(minutes=LATE_GRACE_MIN)
    tag = (cfg.get("BRIEF_FORCE_TAG") or config.DEFAULTS["BRIEF_FORCE_TAG"]).lower()
    meetings_dir = config.obsidian_dir(cfg)
    out = []
    for ev in events:
        if not ev.get("start_ts"):
            continue
        start = datetime.fromtimestamp(ev["start_ts"])
        if not (now - grace <= start <= now + lead):
            continue
        forced = tag in ev["title"].lower()
        has_history = bool(notes.find_notes_by_title(meetings_dir, ev["title"]))
        if not (forced or has_history):
            continue
        if brief.brief_path(cfg, start.date(), ev["title"]).exists():
            continue
        out.append(ev)
    return out


def step_briefs(cfg: dict, now: datetime, dry_run: bool, events=None,
                generate=None, send=notify.notify) -> int:
    if not cfg.get("OBSIDIAN_DIR"):
        return 0
    if events is None:
        events = calendar_io.events_today(cfg)
    cands = brief_candidates(cfg, events, now)
    if not cands:
        return 0
    attempts = _load_attempts(cfg)
    vault_root = config.obsidian_dir(cfg).parent
    made = 0
    for ev in cands:
        start = datetime.fromtimestamp(ev["start_ts"])
        key = f"{start:%Y-%m-%d}_{notes.normalize_title(ev['title'])}"
        if attempts.get(key, 0) >= MAX_BRIEF_ATTEMPTS:
            continue
        print(f"[tick] 브리핑 대상: {ev['title']} ({start:%H:%M}){' (dry-run)' if dry_run else ''}")
        made += 1
        if dry_run:
            continue
        attempts[key] = attempts.get(key, 0) + 1
        _attempts_path(cfg).write_text(json.dumps(attempts, ensure_ascii=False), encoding="utf-8")
        try:
            if generate is None:
                from meetingflow.brief import generate_brief as generate  # requests 지연 import
            path = generate(cfg, ev["title"], start, ev.get("attendees", []), now)
            url = notes.obsidian_url(cfg["OBSIDIAN_VAULT_NAME"], vault_root, path)
            send("회의 브리핑 🧭", f"{ev['title']} {start:%H:%M} 시작 전 브리핑 (클릭하면 열기)",
                 open_url=url, group="meetingflow-brief")
        except Exception as e:  # noqa: BLE001
            print(f"[tick] 브리핑 생성 실패 ({attempts[key]}/{MAX_BRIEF_ATTEMPTS}): {e}")
            made -= 1
    return made


# ---------- 3. 정리 ----------

def step_cleanup(cfg: dict, now: datetime, dry_run: bool) -> int:
    if dry_run:
        return 0
    return pending.cleanup(cfg, now, days=30)


# ---------- main ----------

def _rotate_log(cfg: dict) -> None:
    log = config.meetings_dir(cfg) / ".tick.log"
    try:
        if log.exists() and log.stat().st_size > LOG_MAX_BYTES:
            log.write_text("")
    except OSError:
        pass


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    dry_run = "--dry-run" in argv
    cfg = config.load_config()
    _rotate_log(cfg)
    now = datetime.now()
    lock = pending.pending_dir(cfg) / ".tick.lock"
    if not dry_run and not acquire_lock(lock, os.getpid()):
        print("[tick] 이전 틱이 아직 실행 중, 종료")
        return 0
    try:
        for name, step in (("renotify", step_renotify), ("briefs", step_briefs), ("cleanup", step_cleanup)):
            try:
                step(cfg, now, dry_run)
            except Exception as e:  # noqa: BLE001
                print(f"[tick] {name} 단계 실패: {e}")
    finally:
        if not dry_run:
            try:
                lock.unlink()
            except OSError:
                pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python3 -m pytest tests/test_tick.py -q`
Expected: 9 passed

- [ ] **Step 5: launchd 설치 스크립트**

`scripts/install-launchd.sh`:

```bash
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
```

```bash
chmod +x scripts/install-launchd.sh scripts/tick.py
```

- [ ] **Step 6: dry-run과 설치 확인**

Run: `.venv/bin/python3 scripts/tick.py --dry-run; echo "exit=$?"`
Expected: 오류 없이 종료, `exit=0`. 재알림·브리핑 대상이 있으면 `[tick] ...` 줄 출력.

Run: `./scripts/install-launchd.sh && sleep 3 && tail -5 ~/Meetings/.tick.log`
Expected: `설치: ...` 출력, 로그에 python 오류 없음 (RunAtLoad로 첫 실행이 바로 돈다)

- [ ] **Step 7: 커밋**

```bash
git add scripts/tick.py scripts/install-launchd.sh tests/test_tick.py
git commit -m "launchd 틱 추가: 미처리 후보 재알림·만료, 회의 전 브리핑 생성, 정리"
```

---

### Task 13: 회의록 요약에 브리핑 반영

**Files:**
- Modify: `scripts/process_meeting.py` (`summarize` 시그니처에 `brief_text` 추가, `main`에서 브리핑 탐색, frontmatter `brief` 기록)
- Modify: `tests/test_process_hooks.py` (테스트 추가)

**Interfaces:**
- Consumes: `brief.brief_path`, `notes.set_frontmatter_field`
- Produces:
  - `process_meeting.find_brief(cfg, title: str, start_dt: datetime) -> Path | None`
  - `process_meeting.summarize(cfg, title, transcript, attendees=None, brief_text: str = "") -> str`
  - `process_meeting.build_brief_block(brief_text: str) -> str`

- [ ] **Step 1: 실패하는 테스트 추가**

`tests/test_process_hooks.py` 끝에 추가:

```python
def test_find_brief_and_block(cfg):
    from meetingflow import brief
    start = datetime(2026, 10, 14, 10, 5)
    assert pm.find_brief(cfg, "[11층 몰디브] STR Weekly", start) is None
    p = brief.brief_path(cfg, start.date(), "[11층 몰디브] STR Weekly")
    p.parent.mkdir(parents=True); p.write_text("---\ntitle: x\n---\n\n# 브리핑\n\n## 📌 지난 결정 사항\n\n- A\n", encoding="utf-8")
    assert pm.find_brief(cfg, "[11층 몰디브]  STR Weekly", start) == p
    block = pm.build_brief_block(p.read_text(encoding="utf-8"))
    assert "지난 회의" in block and "- A" in block and "title: x" not in block
    assert pm.build_brief_block("") == ""


def test_summarize_includes_brief_block(cfg, monkeypatch):
    captured = {}

    class R:
        def raise_for_status(self): pass
        def json(self): return {"content": [{"type": "text", "text": "## 요약\n\nok"}]}
    monkeypatch.setattr(pm.requests, "post", lambda url, **kw: captured.update(kw) or R())
    pm.summarize(cfg, "t", "전사", None, brief_text="# 브리핑\n\n- A")
    assert "- A" in captured["json"]["messages"][0]["content"]
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python3 -m pytest tests/test_process_hooks.py -q`
Expected: FAIL, `AttributeError: ... 'find_brief'`

- [ ] **Step 3: 구현**

`scripts/process_meeting.py` import에 `brief` 추가:

```python
from meetingflow import actions, brief, calendar_io, notes as mf_notes, pending  # noqa: E402
```

`summarize` 바로 위에 두 함수 추가:

```python
def find_brief(cfg: dict, title: str, start_dt: datetime) -> Path:
    """같은 날짜·정규화 제목의 브리핑 노트가 있으면 경로 반환"""
    if not cfg.get("OBSIDIAN_DIR"):
        return None
    p = brief.brief_path(cfg, start_dt.date(), title)
    return p if p.exists() else None


def build_brief_block(brief_text: str) -> str:
    if not brief_text.strip():
        return ""
    _, body = mf_notes.split_frontmatter(brief_text)
    return f"""
아래는 이 회의 직전에 만든 브리핑입니다. 지난 회의의 결정 사항과 미완료 액션 아이템이
이번 회의에서 어떻게 진행되었는지(완료, 진행 중, 보류, 언급 없음)를 요약과 액션 아이템에 반영하세요.
브리핑에만 있고 이번 전사록에 언급되지 않은 내용은 새 결정으로 만들지 마세요.

{body.strip()}
"""
```

`summarize` 시그니처와 프롬프트를 수정:

```python
def summarize(cfg: dict, title: str, transcript: str, attendees: list = None,
              brief_text: str = "") -> str:
    ...
    template = load_template(cfg, title)
    project_block = build_project_block(cfg)
    brief_block = build_brief_block(brief_text)
    prompt = f"""다음은 "{title}" 회의의 화자분리 전사록입니다. 아래 형식의 한국어 회의록으로 정리해주세요.
{attendee_block}{project_block}{brief_block}
{template}

전사록:
{transcript}"""
```

`main()`의 4단계를 수정:

```python
        # 4. 요약 (참석자 실명 매핑 + 관련 프로젝트 선정 + 사전 브리핑 반영)
        brief_path = find_brief(cfg, title, start_dt)
        brief_text = brief_path.read_text(encoding="utf-8") if brief_path else ""
        if brief_path:
            print(f"[brief] 사전 브리핑 반영: {brief_path.name}")
        summary = summarize(cfg, title, transcript, attendees, brief_text)
```

5단계 `note = write_obsidian_note(...)` 직후, `queue_timeblock_candidates(...)` 앞에 추가:

```python
        if brief_path:
            mf_notes.set_frontmatter_field(note, "brief", f'"[[{brief_path.stem}]]"')
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python3 -m pytest -q`
Expected: 모두 통과

- [ ] **Step 5: 커밋**

```bash
git add scripts/process_meeting.py tests/test_process_hooks.py
git commit -m "요약 시 당일 브리핑을 프롬프트에 반영하고 회의록 frontmatter에 링크"
```

---

### Task 14: 설치·진단·문서

**Files:**
- Modify: `setup.sh` (terminal-notifier, pytest, install-launchd)
- Create: `scripts/doctor.py` (현재 `doctor.sh`가 가리키지만 존재하지 않는 파일)
- Modify: `README.md`

**Interfaces:**
- Produces: `python3 scripts/doctor.py` 가 점검 결과를 출력하고, 실패 항목이 있으면 종료 코드 1

- [ ] **Step 1: setup.sh 수정**

`for pkg in ffmpeg ical-buddy switchaudio-osx; do` → `for pkg in ffmpeg ical-buddy switchaudio-osx terminal-notifier; do`

`.venv/bin/pip install --quiet boto3 requests` → `.venv/bin/pip install --quiet boto3 requests truststore pytest`
그 아래 `ok "venv + boto3, requests"` → `ok "venv + boto3, requests, truststore, pytest"`

`chmod +x scripts/*.sh` 아래에 추가:

```bash
# ---------- 3.5 launchd 틱 (브리핑·재알림) ----------
if ./scripts/install-launchd.sh; then
  ok "launchd 틱 (com.meetingflow.tick)"
else
  warn "launchd 설치 실패 — 나중에 ./scripts/install-launchd.sh 를 다시 실행하세요"
fi
```

GUIDE heredoc의 `② 트리거 등록:` 항목 끝에 한 줄 추가:

```
     - 어느 쪽이든 '타임블록 검토' 트리거도 함께 등록됩니다 (Quick Action은 자동, Raycast는 scripts/ 폴더에 포함)
```

`④ 첫 테스트:` 아래에 추가:

```
  ⑤ 캘린더·미리알림 자동화 권한 (1회):
     .venv/bin/python3 -m meetingflow.calendar_io --smoke   ← scripts/ 폴더에서 실행
     (권한 팝업이 뜨면 허용. 테스트 이벤트를 만들고 바로 지웁니다)
```

- [ ] **Step 2: doctor.py 작성**

`scripts/doctor.py`:

```python
#!/usr/bin/env python3
"""설치 상태 점검. 실패 항목이 있으면 종료 코드 1."""
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from meetingflow import config  # noqa: E402

OK, WARN, FAIL = "✅", "⚠️ ", "❌"


def check(label: str, cond: bool, hint: str = "", warn_only: bool = False) -> bool:
    mark = OK if cond else (WARN if warn_only else FAIL)
    print(f"  {mark} {label}" + ("" if cond or not hint else f"  → {hint}"))
    return cond or warn_only


def main() -> int:
    results = []
    print("═══ Meeting Flow 진단 ═══")
    print("[의존성]")
    for tool, hint in (("ffmpeg", "brew install ffmpeg"), ("icalBuddy", "brew install ical-buddy"),
                       ("SwitchAudioSource", "brew install switchaudio-osx")):
        results.append(check(tool, shutil.which(tool) is not None, hint))
    results.append(check("terminal-notifier (알림 클릭 동작)", shutil.which("terminal-notifier") is not None,
                         "brew install terminal-notifier — 없으면 알림을 클릭해도 팝업이 열리지 않음", warn_only=True))

    print("[설정]")
    results.append(check("config.env 존재", config.CONFIG_PATH.exists(), "cp config.env.example config.env"))
    cfg = config.load_config()
    for key in ("CALENDAR_NAME", "OBSIDIAN_DIR", "ANTHROPIC_API_KEY", "CLOVA_INVOKE_URL", "NCP_BUCKET"):
        results.append(check(f"{key} 설정됨", bool(cfg.get(key)) and not cfg[key].startswith("xoxp-...")))
    results.append(check("MY_NAMES 설정됨 (타임블록 추출용)", bool(config.my_names(cfg))))
    if cfg.get("OBSIDIAN_DIR"):
        results.append(check("OBSIDIAN_DIR 폴더 존재", config.obsidian_dir(cfg).is_dir()))

    print("[캘린더]")
    try:
        out = subprocess.run(["icalBuddy", "calendars"], capture_output=True, text=True, timeout=15).stdout
        results.append(check(f"캘린더 '{cfg.get('CALENDAR_NAME')}' 보임", cfg.get("CALENDAR_NAME", "") in out,
                             "시스템 설정 > 개인정보 보호 > 캘린더 에서 터미널 허용, 이름은 icalBuddy calendars 로 확인"))
    except Exception as e:  # noqa: BLE001
        results.append(check("icalBuddy 실행", False, str(e)))

    print("[자동화]")
    uid = subprocess.run(["id", "-u"], capture_output=True, text=True).stdout.strip()
    loaded = subprocess.run(["launchctl", "print", f"gui/{uid}/com.meetingflow.tick"],
                            capture_output=True, text=True).returncode == 0
    results.append(check("launchd 틱 로드됨 (com.meetingflow.tick)", loaded, "./scripts/install-launchd.sh", warn_only=True))
    services = Path.home() / "Library" / "Services"
    results.append(check("Quick Action '타임블록 검토' 설치됨", (services / "타임블록 검토.workflow").exists(),
                         "./scripts/install-quick-actions.sh (Raycast만 쓰면 무시)", warn_only=True))
    print("  ℹ️  캘린더·미리알림 자동화 권한은 첫 반영 때 macOS가 묻습니다."
          " 미리 확인: cd scripts && ../.venv/bin/python3 -m meetingflow.calendar_io --smoke")

    bad = results.count(False)
    print(f"\n{'모든 필수 항목 통과' if not bad else f'실패 {bad}건'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: 진단 실행**

Run: `./doctor.sh; echo "exit=$?"`
Expected: 항목별 ✅/⚠️/❌ 출력. 이 환경에서는 `terminal-notifier`가 ⚠️로 표시되고 나머지 필수 항목은 ✅여야 한다. `exit=0`.

- [ ] **Step 4: README 갱신**

`README.md` 상단 파이프라인 다이어그램을 교체:

```
미팅 시작 ─→ Slack DND + 상태 "🎙 회의 중" + macOS 집중 모드 ─→ ffmpeg 녹음 시작
미팅 끝  ─→ 녹음 종료 ─→ 캘린더 이벤트명 바인딩 ─→ NCP 업로드
         ─→ CLOVA Speech 화자분리 ─→ Claude 요약 (회의 유형별 템플릿
         + 관련 프로젝트 링크 + 당일 브리핑 반영) ─→ Obsidian 저장 ─→ 완료 알림
         ─→ 내 액션 아이템 추출 ─→ "타임블록 후보 N건" 알림
              클릭 ─→ 검토 팝업 (시간 조정·승인) ─→ 캘린더 타임블록 / 미리알림 생성
                                                ─→ 회의록에 ## 📅 타임블록 기록

launchd 5분 틱 ─→ 반복 회의 15분 전 브리핑 노트 생성 (_briefs/) + 알림
               ─→ 미처리 후보 아침 재알림, 7일 지나면 만료
```

`## 1. 의존성 설치`의 brew 줄에 `terminal-notifier` 추가.

`## 7. 트리거 등록` 7-A 목록에 추가: `- \`타임블록 검토\` — 미처리 타임블록 후보 검토 팝업 열기`. 7-B 목록에 `**타임블록 검토**` 항목 추가, "3개 항목" → "4개 항목".

`## 트러블슈팅` 앞에 새 절 추가:

```markdown
## 8. 액션 아이템 → 타임블록 (자동)

회의록이 완성되면 `## ✅ 액션 아이템`에서 **내 항목**(`MY_NAMES`에 적은 이름, 그리고 `공통`)을
추출해 기한을 추정한다. 날짜가 명시된 항목은 그 날짜, "다음 회의 전까지"는 캘린더에서 찾은
다음 차수 날짜, 단서가 없으면 기한 없음으로 분류한다. 결과는 `~/Meetings/.pending/`에
후보로 저장되고 "타임블록 후보 N건" 알림이 뜬다.

알림을 클릭하면(또는 `타임블록 검토` 트리거를 실행하면) 로컬 팝업이 열린다.
항목마다 체크, 종류(📅 타임블록 / ⏰ 미리알림), 제목, 날짜, 시간, 길이를 고칠 수 있고,
오른쪽에는 앞으로 7일 일정이 보인다. 제안 시간은 `WORK_HOURS` 안에서 기한 전날부터
거꾸로 가장 늦은 빈 구간이다. **반영**을 누르면 승인한 항목만 macOS 캘린더
앱(`TIMEBLOCK_CALENDAR`, 비우면 `CALENDAR_NAME`)과 미리알림 앱(`REMINDER_LIST`)에 들어가고,
회의록 끝에 `## 📅 타임블록` 섹션으로 기록이 남는다.

미처리 후보는 다음 날 `MORNING_REMIND_AT`에 한 번 더 알림이 오고, `PENDING_EXPIRE_DAYS`가
지나면 `.pending/expired/`로 옮겨진다. 첫 반영 때 macOS가 캘린더·미리알림 자동화 권한을 묻는다.

## 9. 회의 전 브리핑 (자동)

launchd가 5분마다 `scripts/tick.py`를 실행한다 (`./scripts/install-launchd.sh`로 설치).
오늘 일정 중 시작 `BRIEF_LEAD_MIN`분 이내인 회의가 아래 조건을 만족하면
`<OBSIDIAN_DIR>/_briefs/YYYY-MM-DD_<제목>.md`를 만들고 알림을 보낸다. 클릭하면 Obsidian에서 열린다.

- `Meetings/`에 같은 제목의 회의록이 하나 이상 있다 (반복 회의), 또는
- 캘린더 제목에 `BRIEF_FORCE_TAG`(기본 `[brief]`)가 들어 있다

브리핑은 지난 `BRIEF_HISTORY_COUNT`회의 결정 사항과 미완료 액션 아이템(내 것 먼저)을 그대로 옮기고,
관련 프로젝트 근황과 확인할 질문은 Claude가 쓴다. 같은 날 `미팅 끝`으로 회의록을 만들 때
이 브리핑이 요약 프롬프트에 함께 들어가 지난 항목의 진행 상황이 반영되며, 회의록 frontmatter에
`brief: "[[...]]"`로 연결된다.

점검: `python3 scripts/tick.py --dry-run` (지금 틱이 할 일 출력), `tail -f ~/Meetings/.tick.log`.
```

트러블슈팅에 추가:

```markdown
- **알림을 클릭해도 팝업이 안 열림**: `terminal-notifier`가 없으면 클릭 동작이 없다.
  `brew install terminal-notifier` 후 `타임블록 검토` 트리거로 직접 열 수도 있다.
- **반영 시 "-1743" 오류**: 캘린더/미리알림 자동화 권한 거부. `시스템 설정 > 개인정보 보호 >
  자동화`에서 터미널(또는 python)의 캘린더·미리알림을 허용.
- **브리핑이 안 만들어짐**: `launchctl print gui/$(id -u)/com.meetingflow.tick`으로 로드 여부 확인,
  `~/Meetings/.tick.log` 확인. 제목이 정확히 같은 회의록이 있어야 하며, `_briefs/`에 이미 있으면 다시 만들지 않는다.
```

파일 구조 절을 갱신해 `scripts/meetingflow/`, `tick.py`, `review-open.sh`, `review-open.py`, `review-timeblocks.sh`, `install-launchd.sh`, `doctor.py`, `templates/brief.md`, `tests/`를 추가한다.

- [ ] **Step 5: 전체 테스트와 커밋**

Run: `.venv/bin/python3 -m pytest -q && ./doctor.sh`
Expected: 모두 통과, 진단 종료 코드 0

```bash
git add setup.sh scripts/doctor.py README.md
git commit -m "설치·진단·README에 타임블록 검토와 브리핑 기능 반영"
```
