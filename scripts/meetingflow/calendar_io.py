"""icalBuddy로 캘린더를 읽고, AppleScript로 캘린더·미리알림에 쓴다. 표준 라이브러리만 사용."""
from __future__ import annotations

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


def parse_icalbuddy_events(out: str, today: date | None = None) -> list[dict]:
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


def run_icalbuddy(cfg: dict, args: list[str], run=subprocess.run) -> str:
    cmd = ICALBUDDY_BASE + ["-ic", cfg["CALENDAR_NAME"]] + args
    try:
        return run(cmd, capture_output=True, text=True, timeout=30).stdout
    except Exception as e:  # noqa: BLE001
        print(f"[calendar] icalBuddy 실패: {e}")
        return ""


def events_today(cfg: dict, run=subprocess.run) -> list[dict]:
    return parse_icalbuddy_events(run_icalbuddy(cfg, ["eventsToday"], run=run))


def events_between(cfg: dict, start: date, end_inclusive: date, run=subprocess.run) -> list[dict]:
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
