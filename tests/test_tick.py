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


def test_step_renotify_skips_corrupt_pending(cfg):
    note = Path(cfg["OBSIDIAN_DIR"]) / "n.md"; note.write_text("x")
    items = [{"id": "a", "text": "t", "owner": "Claud", "is_mine": True, "due": None,
              "due_source": "none", "kind": "block", "estimate_min": 30}]
    pending.new_pending(cfg, note, "x", date(2026, 10, 7), items, datetime(2026, 10, 7))
    (pending.pending_dir(cfg) / "broken.json").write_text("{not json", encoding="utf-8")
    sent = []
    assert tick.step_renotify(cfg, datetime(2026, 10, 8, 9, 5), False, send=lambda *a, **k: sent.append(1)) == 1
    assert sent == [1]
