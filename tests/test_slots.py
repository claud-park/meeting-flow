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


def test_due_today_after_hours_has_no_proposal():
    late = datetime(2026, 10, 7, 18, 30)
    out = slots.propose([_item(due="2026-10-07")], [], {"WORK_HOURS": "10:00-18:00", "MORNING_REMIND_AT": "09:00"}, late)
    assert out[0]["proposed_start"] is None and out[0]["default_checked"] is False
    assert out[0]["overdue"] is False and out[0]["conflict"] is False


def test_reminder_due_today_moves_to_next_grid():
    out = slots.propose([_item(kind="reminder", estimate_min=0, due="2026-10-07")], [],
                        {"WORK_HOURS": "10:00-18:00", "MORNING_REMIND_AT": "09:00"}, NOW)  # NOW = 11:40
    assert out[0]["proposed_start"] == "2026-10-07T12:00:00" and out[0]["default_checked"] is True


def test_not_before_on_grid_is_not_pushed():
    day = date(2026, 10, 7)
    free = slots.free_slots_for_day(day, [], WORK, 30, not_before=datetime(2026, 10, 7, 12, 0))
    assert free[0][0] == datetime(2026, 10, 7, 12, 0)
    free2 = slots.free_slots_for_day(day, [], WORK, 30, not_before=datetime(2026, 10, 7, 12, 10))
    assert free2[0][0] == datetime(2026, 10, 7, 12, 30)


def test_multiday_busy_blocks_whole_day():
    day = date(2026, 10, 9)
    busy = [(datetime(2026, 10, 8, 9, 0), datetime(2026, 10, 10, 9, 0))]
    assert slots.free_slots_for_day(day, busy, WORK, 30) == []


def test_propose_shares_busy_across_calls():
    """회의 두 개가 같은 busy 목록을 이어 쓰면 제안이 서로 겹치지 않는다."""
    busy = []
    a = slots.propose([_item(id="a")], [], {}, NOW, busy=busy)[0]
    b = slots.propose([_item(id="b")], [], {}, NOW, busy=busy)[0]
    assert a["proposed_start"] and b["proposed_start"]
    assert (a["proposed_start"], a["proposed_end"]) != (b["proposed_start"], b["proposed_end"])
    assert b["proposed_end"] <= a["proposed_start"] or b["proposed_start"] >= a["proposed_end"]
    assert not b["conflict"]
