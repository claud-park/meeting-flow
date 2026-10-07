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


def test_queue_warns_on_extraction_failure(cfg, monkeypatch):
    warned = []
    monkeypatch.setattr(pm, "notify", lambda *a, **k: warned.append(a))

    def boom(c, pr):
        raise RuntimeError("network down")
    note = Path(cfg["OBSIDIAN_DIR"]) / "n.md"
    note.write_text("x")
    # Claude 호출이 두 번 다 실패 → ExtractionError → 경고 알림, 후보 없음, 예외 전파 없음
    assert pm.queue_timeblock_candidates(cfg, note, "t", SUMMARY, [], datetime(2026, 10, 7),
                                         call=boom, run=_fake_ical) is None
    assert warned and warned[0][0].startswith("액션 아이템 추출 실패")
    assert pending.list_pending(cfg) == []


def test_queue_swallows_unexpected_exceptions(cfg, monkeypatch):
    warned = []
    monkeypatch.setattr(pm, "notify", lambda *a, **k: warned.append(a))

    def explode(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(pm.pending, "new_pending", explode)
    note = Path(cfg["OBSIDIAN_DIR"]) / "n.md"
    note.write_text("x")
    assert pm.queue_timeblock_candidates(cfg, note, "t", SUMMARY, [], datetime(2026, 10, 7),
                                         call=lambda c, pr: GOOD, run=_fake_ical) is None
    assert warned and warned[0][0].startswith("액션 아이템 추출 실패")


def test_queue_continues_when_calendar_lookup_fails(cfg, monkeypatch):
    monkeypatch.setattr(pm, "notify", lambda *a, **k: None)

    def ical_boom(cmd, **kw):
        raise OSError("icalBuddy missing")
    note = Path(cfg["OBSIDIAN_DIR"]) / "n.md"
    note.write_text("x")
    p = pm.queue_timeblock_candidates(cfg, note, "t", SUMMARY, [], datetime(2026, 10, 7),
                                      call=lambda c, pr: GOOD, run=ical_boom)
    assert p is not None and pending.load(p)["items"][0]["due"] == "2026-10-14"
