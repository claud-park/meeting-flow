"""타임블록 제안 시간 계산. 표준 라이브러리만 사용."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from . import config

GRID_MIN = 30

Busy = tuple[datetime, datetime]


def busy_from_events(events: list[dict]) -> list[Busy]:
    out = []
    for e in events:
        if e.get("start_ts") and e.get("end_ts"):
            out.append((datetime.fromtimestamp(e["start_ts"]), datetime.fromtimestamp(e["end_ts"])))
    return out


def _overlaps(a: Busy, b: Busy) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def free_slots_for_day(day: date, busy: list[Busy], work: tuple[time, time], duration_min: int,
                       not_before: datetime | None = None) -> list[Busy]:
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


def _weekdays_desc(first: date, last: date) -> list[date]:
    days = []
    d = last
    while d >= first:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    return days


def _propose_block(due: date, duration_min: int, busy: list[Busy], work: tuple[time, time],
                   now: datetime) -> tuple[datetime, datetime, bool]:
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


def propose(items: list[dict], events: list[dict], cfg: dict, now: datetime) -> list[dict]:
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
