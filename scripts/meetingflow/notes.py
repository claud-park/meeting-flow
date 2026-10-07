"""Obsidian 회의록 읽기·쓰기. 표준 라이브러리만 사용."""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import quote

TIMEBLOCK_HEADING = "## 📅 타임블록"
TRANSCRIPT_HEADING_PREFIX = "## 전체 전사록"
_NOTE_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{4}_")
_ACTION_RE = re.compile(r"^- \[( |x|X)\]\s*(?:\*\*(.+?)\*\*\s*:|([^:*]{1,30}):)?\s*(.+?)\s*$")


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\n\r]+', "_", name).strip()
    return name[:80] or "회의"


def normalize_title(title: str) -> str:
    return sanitize_filename(" ".join(title.split()))


def title_from_note_path(path: Path) -> str:
    return _NOTE_PREFIX.sub("", Path(path).stem)


def find_notes_by_title(meetings_dir: Path, title: str) -> list:
    target = normalize_title(title)
    hits = [p for p in Path(meetings_dir).glob("*.md")
            if normalize_title(title_from_note_path(p)) == target]
    return sorted(hits, key=lambda p: p.name, reverse=True)


def split_frontmatter(text: str) -> tuple:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("\n---", 1)
    if len(parts) < 2:
        return {}, text
    head = parts[0][3:]
    body = parts[1][1:] if parts[1].startswith("\n") else parts[1]
    fm = {}
    for line in head.splitlines():
        if ":" in line and not line.startswith(" "):
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip()
    return fm, body


def frontmatter_list(value: str) -> list:
    v = value.strip()
    if v.startswith("[") and v.endswith("]"):
        v = v[1:-1]
    out = []
    for part in re.split(r",\s*(?![^\[]*\]\])", v):  # [[a]], [[b]] 안의 쉼표는 보호
        part = part.strip().strip('"').strip("'").strip()
        if part:
            out.append(part)
    return out


def body_before_transcript(text: str) -> str:
    idx = text.find(TRANSCRIPT_HEADING_PREFIX)
    if idx == -1:
        return text
    cut = text[:idx].rstrip()
    if cut.endswith("---"):
        cut = cut[:-3].rstrip()
    return cut


def extract_section(body: str, keyword: str) -> str:
    lines = body.splitlines()
    out, inside = [], False
    for line in lines:
        if line.startswith("## "):
            if inside:
                break
            inside = keyword in line
            continue
        if inside:
            out.append(line)
    return "\n".join(out).strip()


def parse_action_items(section: str) -> list:
    items = []
    for line in section.splitlines():
        m = _ACTION_RE.match(line.strip())
        if not m:
            continue
        done = m.group(1).lower() == "x"
        owner = (m.group(2) or m.group(3) or "").strip()
        items.append({"owner": owner, "text": m.group(4).strip(), "done": done})
    return items


def append_timeblock_section(note_path: Path, lines: list) -> None:
    """타임블록 섹션을 전사록 구분선 앞에 만들거나, 있으면 새 줄만 합친다."""
    note_path = Path(note_path)
    text = note_path.read_text(encoding="utf-8")
    if TIMEBLOCK_HEADING in text:
        head, _, rest = text.partition(TIMEBLOCK_HEADING)
        sec_lines, tail = [], []
        after = rest.split("\n")
        i = 0
        while i < len(after) and not (after[i].startswith("## ") or after[i].strip() == "---"):
            sec_lines.append(after[i]); i += 1
        tail = after[i:]
        existing = [l for l in sec_lines if l.strip()]
        new = [l for l in lines if l not in existing]
        section = "\n".join([TIMEBLOCK_HEADING, ""] + existing + new) + "\n\n"
        note_path.write_text(head + section + "\n".join(tail), encoding="utf-8")
        return
    section = "\n".join([TIMEBLOCK_HEADING, ""] + list(lines))
    idx = text.find(TRANSCRIPT_HEADING_PREFIX)
    if idx == -1:
        new_text = text.rstrip() + "\n\n" + section + "\n"
    else:
        before = text[:idx].rstrip()
        sep = ""
        if before.endswith("---"):
            before = before[:-3].rstrip()
            sep = "\n\n---\n"
        new_text = before + "\n\n" + section + "\n" + sep + "\n" + text[idx:]
    note_path.write_text(new_text, encoding="utf-8")


def set_frontmatter_field(note_path: Path, key: str, value: str) -> None:
    note_path = Path(note_path)
    text = note_path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        note_path.write_text(f"---\n{key}: {value}\n---\n{text}", encoding="utf-8")
        return
    head, sep, rest = text[3:].partition("\n---")
    lines = head.split("\n")
    for i, line in enumerate(lines):
        if line.startswith(f"{key}:"):
            lines[i] = f"{key}: {value}"
            break
    else:
        lines.append(f"{key}: {value}")
    note_path.write_text("---" + "\n".join(lines) + sep + rest, encoding="utf-8")


def obsidian_url(vault_name: str, vault_root: Path, note_path: Path) -> str:
    rel = Path(note_path).resolve().relative_to(Path(vault_root).resolve())
    rel_no_ext = str(rel.with_suffix("")) if rel.suffix == ".md" else str(rel)
    return f"obsidian://open?vault={quote(vault_name, safe='')}&file={quote(rel_no_ext, safe='')}"
