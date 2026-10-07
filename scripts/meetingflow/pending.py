"""타임블록 후보의 상태 저장소: ~/Meetings/.pending/*.json. 표준 라이브러리만 사용."""
from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from pathlib import Path

from . import config

ISO = "%Y-%m-%dT%H:%M:%S"


def pending_dir(cfg: dict) -> Path:
    d = config.meetings_dir(cfg) / ".pending"
    d.mkdir(parents=True, exist_ok=True)
    return d


def load(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path: Path, data: dict) -> None:
    tmp = Path(path).with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def new_pending(cfg: dict, note_path: Path, title: str, meeting_date: date,
                items: list, now: datetime) -> Path:
    d = pending_dir(cfg)
    stem = Path(note_path).stem
    path = d / f"{stem}.json"
    n = 2
    while path.exists():
        path = d / f"{stem}-{n}.json"
        n += 1
    save(path, {
        "note_path": str(note_path),
        "title": title,
        "meeting_date": meeting_date.isoformat(),
        "created_at": now.strftime(ISO),
        "renotified_on": None,
        "items": items,
    })
    print(f"[pending] 후보 {len(items)}건 저장: {path.name}")
    return path


def list_pending(cfg: dict) -> list:
    return sorted(p for p in pending_dir(cfg).glob("*.json")
                  if p.is_file() and not p.name.startswith("."))


def needs_renotify(data: dict, now: datetime, remind_at: time) -> bool:
    created = datetime.strptime(data["created_at"], ISO)
    if created.date() >= now.date():
        return False
    if now.time() < remind_at:
        return False
    return data.get("renotified_on") != now.date().isoformat()


def mark_renotified(path: Path, day: date) -> None:
    d = load(path)
    d["renotified_on"] = day.isoformat()
    save(path, d)


def _update_item(path: Path, item_id: str, **fields) -> None:
    d = load(path)
    for it in d["items"]:
        if it["id"] == item_id:
            it.update(fields)
    save(path, d)


def mark_applied(path: Path, item_id: str, applied_at: datetime) -> None:
    _update_item(path, item_id, applied_at=applied_at.strftime(ISO), error=None)


def mark_skipped(path: Path, item_id: str) -> None:
    _update_item(path, item_id, skipped=True)


def mark_error(path: Path, item_id: str, message: str) -> None:
    _update_item(path, item_id, error=message)


def unresolved_items(data: dict) -> list:
    return [i for i in data["items"] if not i.get("applied_at") and not i.get("skipped")]


def _move(path: Path, sub: str) -> Path:
    dst_dir = Path(path).parent / sub
    dst_dir.mkdir(exist_ok=True)
    dst = dst_dir / Path(path).name
    Path(path).replace(dst)
    return dst


def move_done(cfg: dict, path: Path) -> Path:
    return _move(path, "done")


def expire_old(cfg: dict, now: datetime, days: int) -> list:
    moved = []
    for p in list_pending(cfg):
        created = datetime.strptime(load(p)["created_at"], ISO)
        if created + timedelta(days=days) <= now:
            moved.append(_move(p, "expired"))
            print(f"[pending] 만료: {p.name}")
    return moved


def cleanup(cfg: dict, now: datetime, days: int = 30) -> int:
    n = 0
    cutoff = now.timestamp() - days * 86400
    for sub in ("done", "expired"):
        d = pending_dir(cfg) / sub
        if not d.is_dir():
            continue
        for p in d.glob("*.json"):
            if p.stat().st_mtime < cutoff:
                p.unlink()
                n += 1
    return n
