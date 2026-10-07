"""회의록 액션 아이템에서 내 할 일을 구조화 JSON으로 추출한다 (Claude 호출)."""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime

from . import config, notes

MODEL = "claude-sonnet-4-6"
REQUIRED = {"text", "owner", "due", "due_source", "kind", "estimate_min"}
DUE_SOURCES = {"explicit", "next_meeting", "none"}
KINDS = {"block", "reminder"}


def is_mine(owner: str, my_names: list) -> bool:
    o = (owner or "").strip().lower()
    if not o:
        return False
    if o == "공통":
        return True
    return any(o == n.lower() for n in my_names)


def build_prompt(action_section: str, attendees: list, meeting_date: date,
                 next_meeting_date: date | None, today: date) -> str:
    nxt = next_meeting_date.isoformat() if next_meeting_date else "미정"
    return f"""다음은 {meeting_date.isoformat()}에 열린 회의의 액션 아이템 목록입니다.
오늘 날짜: {today.isoformat()}
참석자: {", ".join(attendees) if attendees else "미상"}
같은 회의의 다음 차수: {nxt}

각 항목을 아래 스키마의 JSON 배열로만 출력하세요. 설명이나 코드 펜스 없이 배열만 출력합니다.
완료된 항목(- [x])은 제외합니다.

[
  {{
    "text": "할 일 (담당자 이름과 기한 표현을 뺀 한 줄)",
    "owner": "담당자 이름 (원문 표기 그대로, 공통이면 \\"공통\\")",
    "due": "YYYY-MM-DD 또는 null",
    "due_source": "explicit | next_meeting | none",
    "kind": "block | reminder",
    "estimate_min": 30
  }}
]

규칙:
- due: 날짜·요일·"오늘"·"내일"·"이번 주" 등 기한 표현이 있으면 오늘 날짜를 기준으로 YYYY-MM-DD로 환산하고 due_source는 "explicit".
  "다음 회의 전까지"·"다음 주 공유"처럼 차수를 기준으로 하면 다음 차수 날짜를 쓰고 due_source는 "next_meeting". 다음 차수가 미정이면 due는 null, due_source는 "none".
  기한 단서가 전혀 없으면 due는 null, due_source는 "none".
- kind: 자료 작성·분석·개발·정리처럼 앉아서 작업할 시간이 필요하면 "block", 확인·회신·참석·공유처럼 몇 분이면 끝나면 "reminder".
- estimate_min: block이면 필요한 작업 시간을 30분 단위(30, 60, 90, 120, 180)로 추정, reminder면 0.

액션 아이템:
{action_section}"""


def _first_json_array(text: str):
    """본문에서 첫 JSON 배열을 찾는다. `- [ ]` 같은 빈 배열 오탐을 피하기 위해
    dict 원소로만 이뤄진 비어 있지 않은 배열을 우선하고, 없으면 첫 배열을 쓴다."""
    dec = json.JSONDecoder()
    first_any = None
    for i, ch in enumerate(text):
        if ch != "[":
            continue
        try:
            obj, _ = dec.raw_decode(text, i)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, list):
            continue
        if obj and all(isinstance(x, dict) for x in obj):
            return obj
        if first_any is None:
            first_any = obj
    if first_any is None:
        raise ValueError("JSON 배열을 찾을 수 없음")
    return first_any


def parse_items(text: str) -> list:
    data = _first_json_array(text)
    for it in data:
        if not isinstance(it, dict) or not REQUIRED.issubset(it):
            raise ValueError(f"필드 누락: {it}")
        if it["due_source"] not in DUE_SOURCES or it["kind"] not in KINDS:
            raise ValueError(f"enum 값 오류: {it}")
        if it["due"] is not None:
            datetime.strptime(it["due"], "%Y-%m-%d")  # 형식 검증, 실패 시 ValueError
    return data


def call_claude(cfg: dict, prompt: str) -> str:
    import requests  # tick 경로에서 import되지 않도록 지연 import
    res = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": cfg["ANTHROPIC_API_KEY"],
                 "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json={"model": MODEL, "max_tokens": 2000,
              "messages": [{"role": "user", "content": prompt}]},
        timeout=120,
    )
    res.raise_for_status()
    return "".join(b.get("text", "") for b in res.json()["content"] if b.get("type") == "text")


def _round30(n) -> int:
    try:
        n = int(n)
    except (TypeError, ValueError):
        return 30
    return max(30, ((n + 29) // 30) * 30)


def extract_action_items(cfg: dict, summary: str, attendees: list, meeting_date: date,
                         next_meeting_date: date | None, today: date | None = None,
                         call=None) -> list:
    """요약의 액션 아이템 섹션에서 내 항목만 구조화해 반환. 실패하면 빈 리스트."""
    call = call or call_claude
    today = today or date.today()
    names = config.my_names(cfg)
    if not names:
        print("[actions] MY_NAMES가 비어 있어 추출을 건너뜀")
        return []
    section = notes.extract_section(summary, "액션 아이템") if "## " in summary else summary
    if not section or not notes.parse_action_items(section):
        print("[actions] 액션 아이템 섹션 없음")
        return []
    prompt = build_prompt(section, attendees, meeting_date, next_meeting_date, today)
    raw_items = None
    for attempt in range(2):
        try:
            raw_items = parse_items(call(cfg, prompt))
            break
        except Exception as e:  # noqa: BLE001
            print(f"[actions] 추출 실패 ({attempt + 1}/2): {e}")
            prompt = prompt + "\n\n중요: 다른 말 없이 JSON 배열만 출력하세요."
    if raw_items is None:
        return []
    out = []
    for it in raw_items:
        if not is_mine(it["owner"], names):
            continue
        kind = it["kind"]
        due_source = it["due_source"]
        if it["due"] and due_source == "none":
            due_source = "explicit"
        elif not it["due"]:
            due_source = "none"
        out.append({
            "id": uuid.uuid4().hex,
            "text": str(it["text"]).strip(),
            "owner": str(it["owner"]).strip(),
            "is_mine": True,
            "due": it["due"],
            "due_source": due_source,
            "kind": kind,
            "estimate_min": 0 if kind == "reminder" else _round30(it["estimate_min"]),
        })
    print(f"[actions] 내 액션 아이템 {len(out)}건 추출")
    return out
