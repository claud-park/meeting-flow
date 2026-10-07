"""회의 전 브리핑. 사실(결정·미완료 항목)은 코드가 모으고, 서술은 Claude가 쓴다."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from pathlib import Path

from . import config, notes

PROJECT_EXCERPT_CHARS = 1500
ATTENDEE_FALLBACK_DAYS = 30


def brief_path(cfg: dict, day: date, title: str) -> Path:
    return config.briefs_dir(cfg) / f"{day:%Y-%m-%d}_{notes.normalize_title(title)}.md"


def _note_date(path: Path) -> str:
    return path.name[:10]


def _notes_by_attendees(meetings_dir: Path, attendees: list, now: datetime, limit: int) -> list:
    want = {a.lower() for a in attendees}
    since = (now - timedelta(days=ATTENDEE_FALLBACK_DAYS)).strftime("%Y-%m-%d")
    hits = []
    for p in sorted(meetings_dir.glob("*.md"), key=lambda p: p.name, reverse=True):
        if _note_date(p) < since:
            continue
        fm, _ = notes.split_frontmatter(p.read_text(encoding="utf-8"))
        have = {a.lower() for a in notes.frontmatter_list(fm.get("participants", ""))}
        if len(want & have) >= 2:
            hits.append(p)
        if len(hits) >= limit:
            break
    return hits


def collect(cfg: dict, title: str, attendees: list, now: datetime) -> dict:
    meetings_dir = config.obsidian_dir(cfg)
    limit = config.int_cfg(cfg, "BRIEF_HISTORY_COUNT")
    sources = notes.find_notes_by_title(meetings_dir, title)[:limit]
    fallback = "same_title"
    if not sources:
        sources = _notes_by_attendees(meetings_dir, attendees, now, 3)
        fallback = "attendees" if sources else "none"

    decisions, open_items, timeblocks, project_names = [], [], [], []
    for p in sources:
        text = p.read_text(encoding="utf-8")
        fm, _ = notes.split_frontmatter(text)
        body = notes.body_before_transcript(text)
        d = _note_date(p)
        dec = [l.strip() for l in notes.extract_section(body, "결정 사항").splitlines()
               if l.strip() and l.strip() != "없음"]
        if dec:
            decisions.append({"date": d, "note": p.stem, "lines": dec})
        for it in notes.parse_action_items(notes.extract_section(body, "액션 아이템")):
            if not it["done"]:
                open_items.append({"date": d, "note": p.stem, "owner": it["owner"], "text": it["text"]})
        tb = [l.strip() for l in notes.extract_section(body, "타임블록").splitlines() if l.strip()]
        if tb:
            timeblocks.append({"date": d, "note": p.stem, "lines": tb})
        for name in notes.frontmatter_list(fm.get("projects", "")):
            name = name.strip("[]")
            if name and name not in project_names:
                project_names.append(name)

    projects = []
    proj_dir = Path(cfg.get("PROJECTS_DIR") or "")
    if cfg.get("PROJECTS_DIR") and proj_dir.is_dir():
        for name in project_names:
            hits = list(proj_dir.rglob(f"{name}.md"))
            if hits:
                projects.append({"name": name,
                                 "excerpt": hits[0].read_text(encoding="utf-8")[:PROJECT_EXCERPT_CHARS]})
    return {"sources": sources, "decisions": decisions, "open_items": open_items,
            "timeblocks": timeblocks, "projects": projects, "fallback": fallback}


def render_fact_sections(collected: dict, my_names: list) -> tuple:
    if not collected["sources"]:
        return "지난 회의록 없음", "지난 회의록 없음"
    dec_parts = []
    for d in collected["decisions"]:
        dec_parts.append(f"**{d['date']}** ([[{d['note']}]])\n" + "\n".join(d["lines"]))
    decisions_md = "\n\n".join(dec_parts) or "없음"

    mine = {n.lower() for n in my_names}
    def rank(owner: str) -> int:
        o = owner.lower()
        return 0 if o in mine else (1 if o == "공통" else 2)
    groups = {}
    for it in collected["open_items"]:
        groups.setdefault(it["owner"] or "담당자 미상", []).append(it)
    open_parts = []
    for owner in sorted(groups, key=lambda o: (rank(o), o)):
        lines = "\n".join(f"- [ ] {i['text']} ({i['date']}, [[{i['note']}]])" for i in groups[owner])
        open_parts.append(f"**{owner}**\n{lines}")
    open_md = "\n\n".join(open_parts) or "없음"
    if collected["timeblocks"]:
        tb = "\n".join(f"- {t['date']}: " + " / ".join(t["lines"]) for t in collected["timeblocks"])
        open_md += f"\n\n내가 캘린더에 올렸던 항목:\n{tb}"
    return decisions_md, open_md


def build_prompt(title: str, event_start: datetime, attendees: list, collected: dict,
                 decisions_md: str, open_md: str) -> str:
    proj = "\n\n".join(f"[[{p['name']}]]\n{p['excerpt']}" for p in collected["projects"]) or "없음"
    return f"""곧 시작하는 회의를 위한 브리핑의 서술 부분을 작성해주세요.

회의: {title}
시작: {event_start:%Y-%m-%d %H:%M}
참석자: {", ".join(attendees) or "미상"}
참고한 지난 회의록 수: {len(collected["sources"])} ({collected["fallback"]})

[지난 결정 사항]
{decisions_md}

[미완료 액션 아이템]
{open_md}

[관련 프로젝트 노트 발췌]
{proj}

아래 세 구분자를 정확히 사용해 한국어로 출력하세요. 다른 섹션이나 머리말은 쓰지 마세요.
위 자료에 없는 사실을 만들어 내지 마세요.

### CONTEXT
(이 회의가 무엇을 이어 가는 자리인지 한두 문장)
### PROJECTS
(프로젝트별로 "- [[노트명]]: 두세 줄 근황". 자료가 없으면 "없음")
### QUESTIONS
(미완료 항목과 결정 사항에서 도출한, 이번 회의에서 확인할 질문 3개 이내. 번호 목록)"""


def parse_sections(text: str) -> dict:
    out = {"context": "", "projects": "", "questions": ""}
    pattern = re.compile(r"###\s*(CONTEXT|PROJECTS|QUESTIONS)\s*\n(.*?)(?=###\s*(?:CONTEXT|PROJECTS|QUESTIONS)|\Z)", re.S)
    for m in pattern.finditer(text):
        out[m.group(1).lower()] = m.group(2).strip()
    return out


def generate_brief(cfg: dict, title: str, event_start: datetime, attendees: list,
                   now: datetime, call=None) -> Path:
    from .actions import call_claude  # requests 지연 import
    call = call or call_claude
    collected = collect(cfg, title, attendees, now)
    decisions_md, open_md = render_fact_sections(collected, config.my_names(cfg))
    sections = parse_sections(call(cfg, build_prompt(title, event_start, attendees, collected,
                                                     decisions_md, open_md)))
    tmpl = (config.TEMPLATES_DIR / "brief.md").read_text(encoding="utf-8")
    end = event_start + timedelta(hours=1)
    filled = (tmpl
              .replace("{{title}}", title.replace('"', "'"))
              .replace("{{date}}", f"{event_start:%Y-%m-%d}")
              .replace("{{event_time}}", f"{event_start:%H:%M} - {end:%H:%M}")
              .replace("{{sources}}", ", ".join(f'"[[{p.stem}]]"' for p in collected["sources"]))
              .replace("{{context}}", sections["context"] or "(생성 실패)")
              .replace("{{decisions}}", decisions_md)
              .replace("{{open_items}}", open_md)
              .replace("{{projects}}", sections["projects"] or "없음")
              .replace("{{questions}}", sections["questions"] or "없음"))
    path = brief_path(cfg, event_start.date(), title)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(filled, encoding="utf-8")
    print(f"[brief] {path}")
    return path
