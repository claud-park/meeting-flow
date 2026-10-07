import shutil
from datetime import date, datetime
from pathlib import Path

from meetingflow import brief, notes

FIX = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 14, 9, 45)
START = datetime(2026, 10, 14, 10, 0)
TITLE = "[11층 몰디브] STR Weekly"

CLAUDE = """### CONTEXT
STR 주간 회의로, CIS 발표 준비와 BI 요건 정리가 이어지는 자리입니다.
### PROJECTS
- [[ax-view360]]: BI 요건 정의서가 진행 중이며 데이터 요건 싱크가 남아 있습니다.
### QUESTIONS
1. CIS 발표 자료 재구성은 끝났는가?
2. DBA 담당자는 확정되었는가?
"""


def _seed(cfg):
    md = Path(cfg["OBSIDIAN_DIR"])
    shutil.copy(FIX / "str_weekly_2026-10-07.md", md / "2026-10-07_1005_[11층 몰디브] STR Weekly.md")
    shutil.copy(FIX / "str_weekly_2026-09-30.md", md / "2026-09-30_1000_[11층 몰디브] STR Weekly.md")
    shutil.copy(FIX / "str_weekly_2026-10-07.md", md / "2026-10-07_1500_법무 RNR.md")
    proj = Path(cfg["PROJECTS_DIR"]) / "ax-view360.md"
    proj.write_text("# ax-view360\n\nBI 대시보드 프로젝트.\n" + "내용 " * 1000, encoding="utf-8")


def test_brief_path(cfg):
    p = brief.brief_path(cfg, date(2026, 10, 14), "[11층 몰디브]  STR Weekly")
    assert p == Path(cfg["OBSIDIAN_DIR"]) / "_briefs" / "2026-10-14_[11층 몰디브] STR Weekly.md"


def test_collect_same_title_newest_first(cfg):
    _seed(cfg)
    c = brief.collect(cfg, TITLE, ["Claud", "Jennifer"], NOW)
    assert c["fallback"] == "same_title"
    assert [p.name[:10] for p in c["sources"]] == ["2026-10-07", "2026-09-30"]
    assert c["decisions"][0]["date"] == "2026-10-07" and "에반젤리스트" in c["decisions"][0]["lines"][0]
    owners = [(i["date"], i["owner"]) for i in c["open_items"]]
    assert ("2026-10-07", "Jennifer") in owners and ("2026-09-30", "Claud") in owners
    assert all(not i.get("done") for i in c["open_items"])  # 완료 항목 제외
    assert c["timeblocks"][0]["date"] == "2026-09-30"
    assert c["projects"][0]["name"] == "ax-view360" and len(c["projects"][0]["excerpt"]) <= 1500


def test_collect_respects_history_count(cfg):
    _seed(cfg)
    cfg["BRIEF_HISTORY_COUNT"] = "1"
    c = brief.collect(cfg, TITLE, [], NOW)
    assert len(c["sources"]) == 1


def test_collect_attendee_fallback(cfg):
    _seed(cfg)
    c = brief.collect(cfg, "처음 하는 회의", ["Claud", "Alex"], NOW)
    assert c["fallback"] == "attendees"
    assert c["sources"]  # 참석자 둘 이상 겹치는 회의록
    c2 = brief.collect(cfg, "처음 하는 회의", ["Nobody"], NOW)
    assert c2["fallback"] == "none" and c2["sources"] == []


def test_render_fact_sections_mine_first(cfg):
    _seed(cfg)
    c = brief.collect(cfg, TITLE, [], NOW)
    decisions_md, open_md = brief.render_fact_sections(c, ["Claud"])
    assert decisions_md.index("2026-10-07") < decisions_md.index("2026-09-30")
    assert "[[2026-10-07_1005_[11층 몰디브] STR Weekly]]" in decisions_md
    first_owner_line = [l for l in open_md.splitlines() if l.startswith("**")][0]
    assert first_owner_line.startswith("**Claud")
    assert "공통" in open_md and "Jennifer" in open_md


def test_build_prompt_and_parse_sections(cfg):
    _seed(cfg)
    c = brief.collect(cfg, TITLE, ["Claud"], NOW)
    d, o = brief.render_fact_sections(c, ["Claud"])
    p = brief.build_prompt(TITLE, START, ["Claud"], c, d, o)
    assert "### CONTEXT" in p and "### PROJECTS" in p and "### QUESTIONS" in p
    assert "ax-view360" in p and "에반젤리스트" in p
    sec = brief.parse_sections(CLAUDE)
    assert sec["context"].startswith("STR 주간 회의")
    assert "[[ax-view360]]" in sec["projects"] and sec["questions"].startswith("1.")


def test_generate_brief_writes_note(cfg):
    _seed(cfg)
    path = brief.generate_brief(cfg, TITLE, START, ["Claud", "Jennifer"], NOW, call=lambda c, p: CLAUDE)
    assert path == brief.brief_path(cfg, date(2026, 10, 14), TITLE)
    text = path.read_text(encoding="utf-8")
    fm, body = notes.split_frontmatter(text)
    assert fm["tags"] == "[brief]"
    assert fm["event_time"] == "10:00 - 11:00"
    assert "[[2026-10-07_1005_[11층 몰디브] STR Weekly]]" in fm["sources"]
    for h in ("## 🧭 한 줄 맥락", "## 📌 지난 결정 사항", "## ⏳ 미완료 액션 아이템",
              "## 🔗 관련 프로젝트 근황", "## ❓ 이번 회의에서 확인할 것"):
        assert h in body
    assert "에반젤리스트" in body and "DBA 담당자는 확정되었는가" in body


def test_generate_brief_without_history_uses_short_form(cfg):
    _seed(cfg)
    path = brief.generate_brief(cfg, "완전히 새 회의", START, ["Nobody"], NOW,
                                call=lambda c, p: "### CONTEXT\n새 회의\n### PROJECTS\n없음\n### QUESTIONS\n없음\n")
    body = path.read_text(encoding="utf-8")
    assert "지난 회의록 없음" in body
