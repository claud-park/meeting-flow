"""타임블록 검토 팝업: 127.0.0.1 전용 HTTP 서버. 표준 라이브러리만 사용."""
from __future__ import annotations

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
    pdir = pending.pending_dir(cfg).resolve()
    result = {"applied": 0, "skipped": 0, "ignored": 0, "failed": []}
    by_pending = {}
    for a in approvals:
        by_pending.setdefault(a["pending_path"], []).append(a)

    def fail_all(group, msg):
        for a in group:
            result["failed"].append({"id": a["id"], "error": msg})

    for ppath_str, group in by_pending.items():
        # pending_path는 요청 본문에서 오므로 pending 디렉터리 안의 .json만 허용
        ppath = Path(ppath_str).resolve()
        if ppath.parent != pdir or ppath.suffix != ".json":
            fail_all(group, "잘못된 pending_path")
            continue
        try:
            data = pending.load(ppath)
        except (OSError, ValueError):
            fail_all(group, "후보 파일을 읽을 수 없음")
            continue
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
                result["failed"].append({"id": a["id"], "error": "알 수 없는 항목"})
                continue
            if item.get("applied_at") or item.get("skipped"):  # 이미 처리됨: 중복 반영 방지
                result["ignored"] += 1
                continue
            if not a.get("approve"):
                pending.mark_skipped(ppath, a["id"])
                result["skipped"] += 1
                lines.append(format_timeblock_line(item, None, None, False))
                continue
            try:
                title = (a.get("title") or item["text"]).strip()
                start = datetime.fromisoformat(a["start"])
                end = datetime.fromisoformat(a["end"]) if a.get("end") else None
                kind = a.get("kind") or item["kind"]
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

        def _allowed_host(self):
            port = self.server.server_address[1]
            return self.headers.get("Host", "") in {f"127.0.0.1:{port}", f"localhost:{port}"}

        def do_GET(self):
            if not self._allowed_host():
                return self._json(403, {"error": "forbidden host"})
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
            if not self._allowed_host():
                return self._json(403, {"error": "forbidden host"})
            last_hit["t"] = _time.time()
            if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                return self._json(415, {"error": "application/json required"})
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n) if n else b"[]"
            if self.path == "/api/apply":
                try:
                    approvals = json.loads(raw.decode("utf-8"))
                    if demo_state is not None:
                        res = {"applied": sum(1 for a in approvals if a.get("approve")),
                               "skipped": sum(1 for a in approvals if not a.get("approve")), "ignored": 0, "failed": []}
                    else:
                        res = apply(cfg, approvals, now_fn(), create_event, create_reminder)
                    if demo_state is None and (res["applied"] or res["failed"]):
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
