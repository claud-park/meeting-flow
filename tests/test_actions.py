import json
from datetime import date

from meetingflow import actions

SECTION = """- [ ] **Jennifer**: 티켓 등록
- [ ] **Claud**: CIS 발표 자료 재구성 (10/14 전까지)
- [ ] **Claud**: 다음 회의 전까지 RNR 초안 작성
- [ ] **공통**: DBA 담당자 확인
- [x] **Claud**: 이미 끝난 일"""

GOOD = json.dumps([
    {"text": "티켓 등록", "owner": "Jennifer", "due": None, "due_source": "none", "kind": "block", "estimate_min": 30},
    {"text": "CIS 발표 자료 재구성", "owner": "Claud", "due": "2026-10-14", "due_source": "explicit", "kind": "block", "estimate_min": 90},
    {"text": "RNR 초안 작성", "owner": "Claud", "due": "2026-10-14", "due_source": "next_meeting", "kind": "block", "estimate_min": 60},
    {"text": "DBA 담당자 확인", "owner": "공통", "due": None, "due_source": "none", "kind": "reminder", "estimate_min": 0},
], ensure_ascii=False)


def test_is_mine():
    names = ["Claud", "클로드"]
    assert actions.is_mine("claud", names)
    assert actions.is_mine("클로드", names)
    assert actions.is_mine("공통", names)
    assert not actions.is_mine("Jennifer", names)
    assert not actions.is_mine("", names)


def test_build_prompt_contains_dates_and_rules():
    p = actions.build_prompt(SECTION, ["Claud", "Jennifer"], date(2026, 10, 7), date(2026, 10, 14), date(2026, 10, 7))
    assert "2026-10-07" in p and "2026-10-14" in p
    assert "JSON" in p and "estimate_min" in p and "next_meeting" in p
    assert "티켓 등록" in p


def test_build_prompt_without_next_meeting():
    p = actions.build_prompt(SECTION, [], date(2026, 10, 7), None, date(2026, 10, 7))
    assert "다음 차수: 미정" in p


def test_parse_items_extracts_array_from_prose():
    items = actions.parse_items("설명입니다.\n```json\n" + GOOD + "\n```\n끝")
    assert len(items) == 4 and items[1]["due"] == "2026-10-14"


def test_parse_items_rejects_bad_schema():
    import pytest
    with pytest.raises(ValueError):
        actions.parse_items('[{"text": "x"}]')
    with pytest.raises(ValueError):
        actions.parse_items("JSON 없음")
    with pytest.raises(ValueError):
        actions.parse_items('[{"text":"x","owner":"a","due":"2026-13-40","due_source":"explicit","kind":"block","estimate_min":30}]')


def test_extract_filters_mine_and_assigns_ids(cfg):
    items = actions.extract_action_items(cfg, "## ✅ 액션 아이템\n\n" + SECTION, ["Claud"],
                                         date(2026, 10, 7), date(2026, 10, 14),
                                         today=date(2026, 10, 7), call=lambda c, p: GOOD)
    assert [i["owner"] for i in items] == ["Claud", "Claud", "공통"]
    assert all(i["is_mine"] for i in items)
    assert len({i["id"] for i in items}) == 3
    assert items[2]["estimate_min"] == 0


def test_extract_retries_once_then_gives_up(cfg):
    calls = []

    def flaky(c, p):
        calls.append(p)
        return "그냥 텍스트"
    items = actions.extract_action_items(cfg, SECTION, [], date(2026, 10, 7), None, call=flaky)
    assert items == [] and len(calls) == 2
    assert "JSON" in calls[1] and calls[1] != calls[0]


def test_extract_recovers_on_second_try(cfg):
    answers = iter(["엉뚱한 답", GOOD])
    items = actions.extract_action_items(cfg, SECTION, [], date(2026, 10, 7), None,
                                         call=lambda c, p: next(answers))
    assert len(items) == 3


def test_extract_skips_when_no_section_or_no_names(cfg):
    assert actions.extract_action_items(cfg, "## 🎯 요약\n\n없음", [], date(2026, 10, 7), None,
                                        call=lambda c, p: GOOD) == []
    cfg2 = dict(cfg, MY_NAMES="")
    assert actions.extract_action_items(cfg2, SECTION, [], date(2026, 10, 7), None,
                                        call=lambda c, p: GOOD) == []


def test_estimate_rounded_to_30(cfg):
    odd = json.dumps([{"text": "x", "owner": "Claud", "due": "2026-10-10", "due_source": "explicit",
                       "kind": "block", "estimate_min": 45}])
    items = actions.extract_action_items(cfg, SECTION, [], date(2026, 10, 7), None, call=lambda c, p: odd)
    assert items[0]["estimate_min"] == 60


def test_parse_items_ignores_brackets_in_prose():
    text = "[참고] 아래는 결과입니다.\n- [ ] 원문 줄\n" + GOOD + "\n[끝]"
    assert len(actions.parse_items(text)) == 4


def test_extract_normalizes_due_source(cfg):
    odd = json.dumps([{"text": "x", "owner": "Claud", "due": "2026-10-10", "due_source": "none",
                       "kind": "block", "estimate_min": 30}])
    items = actions.extract_action_items(cfg, SECTION, [], date(2026, 10, 7), None, call=lambda c, p: odd)
    assert items[0]["due_source"] == "explicit"


def test_parse_items_accepts_empty_array():
    assert actions.parse_items("결과: []") == []
