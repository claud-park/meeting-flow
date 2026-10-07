import json
import shutil
import threading
import urllib.error
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
    assert res == {"applied": 2, "skipped": 2, "ignored": 0, "failed": []}
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


def test_apply_ignores_already_applied(cfg):
    note, p = _setup(cfg)
    created = []
    approval = [{"pending_path": str(p), "id": "a1", "approve": True, "kind": "block", "title": "t",
                 "start": "2026-10-13T16:30:00", "end": "2026-10-13T18:00:00"}]
    ev = lambda c, s, st, en, d: created.append(s)
    rs.apply(cfg, approval, NOW, create_event=ev, create_reminder=lambda *a: None)
    res = rs.apply(cfg, approval, NOW, create_event=ev, create_reminder=lambda *a: None)
    assert created == ["t"] and res["applied"] == 0 and res["ignored"] == 1


def test_apply_rejects_foreign_pending_path(cfg, tmp_path):
    note, p = _setup(cfg)
    outside = tmp_path / "evil.json"
    outside.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
    created = []
    res = rs.apply(cfg, [{"pending_path": str(outside), "id": "a1", "approve": True, "kind": "block",
                          "title": "t", "start": "2026-10-13T16:30:00", "end": "2026-10-13T18:00:00"}],
                   NOW, create_event=lambda *a: created.append(1), create_reminder=lambda *a: None)
    assert created == [] and res["failed"] and "pending_path" in res["failed"][0]["error"]


def test_apply_bad_start_is_isolated(cfg):
    note, p = _setup(cfg)
    created = []
    res = rs.apply(cfg, [
        {"pending_path": str(p), "id": "a1", "approve": True, "kind": "block", "title": "bad", "start": "garbage", "end": None},
        {"pending_path": str(p), "id": "c3", "approve": True, "kind": "reminder", "title": "ok",
         "start": "2026-10-09T09:00:00", "end": None},
    ], NOW, create_event=lambda *a: created.append("ev"), create_reminder=lambda *a: created.append("rem"))
    assert created == ["rem"] and res["applied"] == 1 and [f["id"] for f in res["failed"]] == ["a1"]
    assert "- [x] 10/9(금) 09:00 · ok · ⏰" in note.read_text(encoding="utf-8")


def test_http_rejects_bad_host_and_non_json(cfg):
    note, p = _setup(cfg)
    srv = rs.make_server(cfg, port=0, now_fn=lambda: NOW, run=_no_events,
                         create_event=lambda *a: None, create_reminder=lambda *a: None,
                         send=lambda *a, **k: None)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True); t.start()
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/state", headers={"Host": "evil.example"})
        try:
            urllib.request.urlopen(req)
        except urllib.error.HTTPError as e:
            assert e.code == 403
        else:
            raise AssertionError("403 expected")
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/apply", data=b"[]",
                                     headers={"Content-Type": "text/plain"}, method="POST")
        try:
            urllib.request.urlopen(req)
        except urllib.error.HTTPError as e:
            assert e.code == 415
        else:
            raise AssertionError("415 expected")
    finally:
        srv.shutdown()
