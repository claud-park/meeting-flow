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
    lines = expr.splitlines()
    i_day1 = lines.index("set day of theDate to 1")
    i_month = lines.index("set month of theDate to 10")
    i_day = lines.index("set day of theDate to 9")
    assert i_day1 < i_month < i_day


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
