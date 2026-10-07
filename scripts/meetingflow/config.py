"""설정 로드와 기본값. 표준 라이브러리만 사용한다 (tick.py가 import)."""
from __future__ import annotations

import re
from datetime import time
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = SCRIPTS_DIR.parent
TEMPLATES_DIR = REPO_DIR / "templates"
CONFIG_PATH = REPO_DIR / "config.env"

DEFAULTS = {
    "MEETINGS_DIR": str(Path.home() / "Meetings"),
    "OBSIDIAN_DIR": "",
    "PROJECTS_DIR": "",
    "CALENDAR_NAME": "",
    # 액션 아이템 → 타임블록
    "MY_NAMES": "Claud,클로드",
    "TIMEBLOCK_CALENDAR": "",
    "REMINDER_LIST": "미리알림",
    "WORK_HOURS": "10:00-18:00",
    "MORNING_REMIND_AT": "09:00",
    "PENDING_EXPIRE_DAYS": "7",
    "REVIEW_PORT": "47321",
    "OBSIDIAN_VAULT_NAME": "_obsidian",
    # 브리핑
    "BRIEF_LEAD_MIN": "15",
    "BRIEF_HISTORY_COUNT": "3",
    "BRIEF_FORCE_TAG": "[brief]",
}


def _parse_line(line: str):
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        return None
    key, _, val = line.partition("=")
    val = val.strip()
    m = re.match(r'^"([^"]*)"|^\'([^\']*)\'', val)
    if m:
        val = m.group(1) if m.group(1) is not None else m.group(2)
    else:
        val = val.split("#", 1)[0].strip()
    val = val.replace("$HOME", str(Path.home()))
    return key.strip(), val


def load_config(path: Path | None = None) -> dict:
    """config.env를 읽어 DEFAULTS 위에 덮는다. 파일이 없으면 DEFAULTS만 반환."""
    cfg = dict(DEFAULTS)
    path = Path(path) if path else CONFIG_PATH
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            parsed = _parse_line(line)
            if parsed:
                cfg[parsed[0]] = parsed[1]
    return cfg


def meetings_dir(cfg: dict) -> Path:
    return Path(cfg.get("MEETINGS_DIR") or DEFAULTS["MEETINGS_DIR"])


def obsidian_dir(cfg: dict) -> Path:
    return Path(cfg["OBSIDIAN_DIR"])


def briefs_dir(cfg: dict) -> Path:
    return obsidian_dir(cfg) / "_briefs"


def my_names(cfg: dict) -> list:
    return [n.strip() for n in cfg.get("MY_NAMES", "").split(",") if n.strip()]


def timeblock_calendar(cfg: dict) -> str:
    return cfg.get("TIMEBLOCK_CALENDAR") or cfg.get("CALENDAR_NAME", "")


def parse_hhmm(s: str) -> time:
    h, m = s.strip().split(":")
    return time(int(h), int(m))


def work_hours(cfg: dict) -> tuple:
    a, _, b = (cfg.get("WORK_HOURS") or DEFAULTS["WORK_HOURS"]).partition("-")
    return parse_hhmm(a), parse_hhmm(b)


def int_cfg(cfg: dict, key: str) -> int:
    return int(cfg.get(key) or DEFAULTS[key])
