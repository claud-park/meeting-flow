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
