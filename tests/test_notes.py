import shutil
from pathlib import Path

from meetingflow import notes

FIX = Path(__file__).parent / "fixtures" / "str_weekly_2026-10-07.md"


def _copy_fixture(dst_dir: Path, name="2026-10-07_1005_[11층 몰디브] STR Weekly.md") -> Path:
    dst = dst_dir / name
    shutil.copy(FIX, dst)
    return dst


def test_normalize_title_matches_filename_stem():
    t = "[11층 몰디브]  STR Weekly"
    assert notes.normalize_title(t) == "[11층 몰디브] STR Weekly"
    p = Path("2026-10-07_1005_[11층 몰디브] STR Weekly.md")
    assert notes.title_from_note_path(p) == "[11층 몰디브] STR Weekly"
    assert notes.normalize_title("CoE 논의 (정기미팅)") == "CoE 논의 (정기미팅)"
    assert notes.normalize_title("A/B: 테스트") == "A_B_ 테스트"


def test_find_notes_by_title_newest_first_excludes_briefs(tmp_path):
    md = tmp_path / "Meetings"; md.mkdir()
    _copy_fixture(md, "2026-09-30_1000_[11층 몰디브] STR Weekly.md")
    _copy_fixture(md, "2026-10-07_1005_[11층 몰디브] STR Weekly.md")
    _copy_fixture(md, "2026-10-07_1500_다른 회의.md")
    (md / "_briefs").mkdir()
    _copy_fixture(md / "_briefs", "2026-10-07_[11층 몰디브] STR Weekly.md")
    found = notes.find_notes_by_title(md, "[11층 몰디브] STR Weekly")
    assert [p.name for p in found] == [
        "2026-10-07_1005_[11층 몰디브] STR Weekly.md",
        "2026-09-30_1000_[11층 몰디브] STR Weekly.md",
    ]


def test_split_frontmatter_and_lists():
    fm, body = notes.split_frontmatter(FIX.read_text(encoding="utf-8"))
    assert fm["title"] == '"[11층 몰디브] STR Weekly"'
    assert notes.frontmatter_list(fm["participants"]) == ["Jennifer", "Claud", "Alex"]
    assert notes.frontmatter_list(fm["projects"]) == ["[[ax-view360]]", "[[ax-legal-management-system]]"]
    assert body.lstrip().startswith("# [11층 몰디브] STR Weekly")


def test_body_before_transcript_and_sections():
    text = FIX.read_text(encoding="utf-8")
    body = notes.body_before_transcript(text)
    assert "화자1" not in body
    decisions = notes.extract_section(body, "결정 사항")
    assert "에반젤리스트" in decisions
    assert "액션 아이템" not in decisions


def test_parse_action_items():
    text = FIX.read_text(encoding="utf-8")
    items = notes.parse_action_items(notes.extract_section(text, "액션 아이템"))
    assert items[0] == {"owner": "Jennifer", "text": "레드시프트-트리노 연결 정보 보호 검토 티켓 등록", "done": False}
    assert items[1]["done"] is True and items[1]["owner"] == "Claud"
    assert items[3]["owner"] == "공통"
    assert items[4] == {"owner": "Alex", "text": "챔피언 리스트 조정안 수령 후 협의", "done": False}


def test_append_timeblock_section_is_idempotent(tmp_path):
    p = _copy_fixture(tmp_path)
    lines = ["- [x] 10/9(목) 14:00-15:00 · CIS 발표 자료 재구성 · 📅",
             "- [ ] DBA 역할 담당자 확인 (건너뜀)"]
    notes.append_timeblock_section(p, lines)
    notes.append_timeblock_section(p, lines + ["- [x] 10/14(화) 09:00 · 확인 · ⏰"])
    text = p.read_text(encoding="utf-8")
    assert text.count(notes.TIMEBLOCK_HEADING) == 1
    assert text.count("CIS 발표 자료 재구성") == 2  # 액션 아이템 1 + 타임블록 1
    assert text.count("10/14(화) 09:00") == 1
    # 전사록 앞, 구분선 앞에 있어야 함
    assert text.index(notes.TIMEBLOCK_HEADING) < text.index("## 전체 전사록")
    assert text.index(notes.TIMEBLOCK_HEADING) > text.index("## 🔗 관련 프로젝트")


def test_append_timeblock_when_no_transcript(tmp_path):
    p = tmp_path / "n.md"
    p.write_text("---\ntitle: x\n---\n\n# x\n\n## ✅ 액션 아이템\n\n- [ ] a\n", encoding="utf-8")
    notes.append_timeblock_section(p, ["- [x] 10/9(목) 14:00-15:00 · a · 📅"])
    assert p.read_text(encoding="utf-8").rstrip().endswith("· a · 📅")


def test_set_frontmatter_field_adds_and_replaces(tmp_path):
    p = _copy_fixture(tmp_path)
    notes.set_frontmatter_field(p, "brief", '"[[2026-10-07_[11층 몰디브] STR Weekly]]"')
    notes.set_frontmatter_field(p, "brief", '"[[other]]"')
    fm, _ = notes.split_frontmatter(p.read_text(encoding="utf-8"))
    assert fm["brief"] == '"[[other]]"'
    assert p.read_text(encoding="utf-8").count("brief:") == 1


def test_obsidian_url_encodes_brackets(tmp_path):
    root = tmp_path / "_obsidian"
    note = root / "Meetings" / "2026-10-07_1005_[11층 몰디브] STR Weekly.md"
    url = notes.obsidian_url("_obsidian", root, note)
    assert url.startswith("obsidian://open?vault=_obsidian&file=")
    assert "%5B11%EC%B8%B5" in url  # '[' 와 한글이 인코딩됨
    assert "Meetings%2F2026" in url  # 경로 구분자도 인코딩 (Obsidian이 해석함)
    assert url.endswith("STR%20Weekly")  # .md 제거, 공백 인코딩
