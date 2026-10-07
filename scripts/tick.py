#!/usr/bin/env python3
"""launchd가 5분마다 실행하는 가벼운 틱.
  1) 미처리 타임블록 후보 아침 재알림 / 만료
  2) 곧 시작하는 회의의 브리핑 생성
  3) done/, expired/ 정리
표준 라이브러리만 import한다. 브리핑 생성(requests)은 필요할 때만 지연 import."""
from __future__ import annotations

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
