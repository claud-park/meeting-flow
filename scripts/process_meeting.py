#!/usr/bin/env python3
"""
Meeting Flow 후처리 파이프라인
  1. icalBuddy로 녹음 시간대의 캘린더 이벤트명 조회 → 파일명 바인딩
  2. NCP Object Storage 업로드
  3. CLOVA Speech 장문 인식 (화자분리) 호출 + 폴링
  4. Claude API 요약
  5. Obsidian vault에 md 저장
"""

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import truststore

truststore.inject_into_ssl()  # macOS 시스템 키체인의 신뢰 인증서를 그대로 사용 (회사 TLS 검사 장비 대응)

import boto3
from botocore.config import Config
import requests

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR.parent / "config.env"


# ---------- 설정 로드 ----------

def load_config() -> dict:
    cfg = {}
    for line in CONFIG_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        val = val.strip()
        # 따옴표로 감싼 값이면 닫는 따옴표까지만, 아니면 인라인 주석 제거
        m = re.match(r'^"([^"]*)"|^\'([^\']*)\'', val)
        if m:
            val = m.group(1) if m.group(1) is not None else m.group(2)
        else:
            val = val.split("#", 1)[0].strip()
        val = val.replace("$HOME", str(Path.home()))
        cfg[key.strip()] = val
    return cfg


def notify(title: str, message: str) -> None:
    """macOS 알림"""
    try:
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{message}" with title "{title}"'],
            check=False,
        )
    except Exception:
        pass


# ---------- 1. 캘린더 이벤트명 + 참석자 조회 ----------

def get_meeting_info(cfg: dict, start_ts: int, end_ts: int) -> tuple:
    """녹음 구간과 가장 많이 겹치는 오늘 이벤트의 (제목, 참석자) 반환.

    icalBuddy의 eventsFrom:'날짜 시간' 범위 지정이 버전에 따라 조용히
    빈 결과를 반환하는 문제가 있어, eventsToday로 하루 전체를 받아
    시간 겹침을 직접 계산하는 방식을 사용한다.
    """
    cmd = [
        "icalBuddy",
        "-npn", "-nc", "-b", "",
        "-nrd",              # 'today' 같은 상대 날짜 표현 비활성화 (파싱 필수)
        "-iep", "title,datetime,attendees",
        "-df", "%Y-%m-%d",   # 날짜 포맷 고정 (파싱용)
        "-tf", "%H:%M",      # 시간 포맷 고정
        "-ic", cfg["CALENDAR_NAME"],
        "eventsToday",
    ]
    try:
        out = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30
        ).stdout
    except Exception as e:
        print(f"[calendar] icalBuddy 실패: {e}")
        return "회의", []

    events = parse_icalbuddy_events(out)
    if not events:
        return "회의", []

    # 녹음 구간과의 겹침(초)이 가장 큰 이벤트 선택
    best, best_overlap = None, 0
    for ev in events:
        if ev["start_ts"] is None:  # 종일 이벤트 등 시간 없는 항목 제외
            continue
        overlap = min(end_ts, ev["end_ts"]) - max(start_ts, ev["start_ts"])
        if overlap > best_overlap:
            best, best_overlap = ev, overlap
    if best is None:
        return "회의", []
    return best["title"], best["attendees"]


def parse_icalbuddy_events(out: str) -> list:
    """icalBuddy 출력을 이벤트 블록 리스트로 파싱"""
    from datetime import timedelta
    events = []
    cur = None
    time_re = re.compile(r"(\d{4}-\d{2}-\d{2}).*?(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})")
    # -nrd를 빼먹은 구버전 호환: 'today at 11:00 - 12:00' 형태도 해석
    rel_re = re.compile(r"^(today|tomorrow|yesterday)\b(.*?)(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})", re.I)
    today_s = datetime.now().strftime("%Y-%m-%d")

    for line in out.splitlines():
        if not line.strip():
            continue
        if not line.startswith((" ", "\t")):  # 제목 줄 (비들여쓰기)
            cur = {"title": line.strip(), "attendees": [],
                   "start_ts": None, "end_ts": None}
            events.append(cur)
            continue
        if cur is None:
            continue
        stripped = line.strip()
        if stripped.lower().startswith("attendees:"):
            raw = stripped.split(":", 1)[1]
            cur["attendees"] = [
                a for a in (clean_attendee(x) for x in raw.split(",")) if a
            ]
            continue

        m = time_re.search(stripped)
        if m:
            date_s, t1, t2 = m.groups()
        else:
            rm = rel_re.search(stripped)
            if rm:
                rel, _, t1, t2 = rm.groups()
                base = datetime.now()
                if rel.lower() == "tomorrow":
                    base += timedelta(days=1)
                elif rel.lower() == "yesterday":
                    base -= timedelta(days=1)
                date_s = base.strftime("%Y-%m-%d")
            else:
                # 날짜 없이 시간만 있는 줄: '11:45 - 12:30'
                # (icalBuddy가 오늘 일정에서 날짜를 생략하는 케이스)
                tm = re.match(r"^(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})$", stripped)
                if not tm:
                    continue
                t1, t2 = tm.groups()
                date_s = today_s
        try:
            s = datetime.strptime(f"{date_s} {t1}", "%Y-%m-%d %H:%M")
            e = datetime.strptime(f"{date_s} {t2}", "%Y-%m-%d %H:%M")
            cur["start_ts"] = int(s.timestamp())
            cur["end_ts"] = int(e.timestamp())
        except ValueError:
            pass
    return events


def clean_attendee(raw: str) -> str:
    """'mailto:jane.doe@company.com' → 'jane.doe'. 회의실 리소스 계정은 제외."""
    a = raw.strip().replace("mailto:", "")
    if not a:
        return ""
    # Google 회의실/리소스 캘린더 계정은 참석자가 아님
    if "resource.calendar.google.com" in a:
        return ""
    if "@" in a:
        a = a.split("@", 1)[0]
    return a


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\n\r]+', "_", name).strip()
    return name[:80] or "회의"


# ---------- 2. Object Storage 업로드 ----------

def upload_to_ncp(cfg: dict, wav_path: Path) -> str:
    s3 = boto3.client(
        "s3",
        endpoint_url=cfg["NCP_OS_ENDPOINT"],
        aws_access_key_id=cfg["NCP_ACCESS_KEY"],
        aws_secret_access_key=cfg["NCP_SECRET_KEY"],
        region_name="kr-standard",
        # NCP Object Storage 호환: 최신 boto3의 기본 체크섬 전송이
        # AccessDenied를 유발하므로 필요할 때만 계산하도록 설정
        config=Config(
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        ),
    )
    # dataKey는 한글/특수문자 이슈를 피하기 위해 ASCII 타임스탬프 사용
    # (로컬 파일명과 Obsidian 노트에는 한글 회의명 유지)
    data_key = f"meetings/rec_{int(time.time())}.wav"
    s3.upload_file(str(wav_path), cfg["NCP_BUCKET"], data_key)
    print(f"[upload] s3://{cfg['NCP_BUCKET']}/{data_key}")
    return data_key


# ---------- 3. CLOVA Speech 장문 인식 (화자분리) ----------

def clova_transcribe(
    cfg: dict, data_key: str,
    speaker_count: int = 0, count_fixed: bool = False,
    names: list = None,
) -> dict:
    headers = {
        "X-CLOVASPEECH-API-KEY": cfg["CLOVA_SECRET_KEY"],
        "Content-Type": "application/json",
    }
    diarization = {"enable": True}
    if speaker_count >= 2:
        if count_fixed:
            # 수동 입력 → 정확한 수로 고정
            diarization["speakerCountMin"] = speaker_count
            diarization["speakerCountMax"] = speaker_count
        else:
            # 캘린더 자동 추출 → 노쇼/난입 대비 ±1 여유
            diarization["speakerCountMin"] = max(1, speaker_count - 1)
            diarization["speakerCountMax"] = speaker_count + 1
        print(f"[clova] 화자 수 힌트: {diarization['speakerCountMin']}"
              f"~{diarization['speakerCountMax']}명")

    body = {
        "dataKey": data_key,
        "language": "ko-KR",
        "completion": "sync",  # async는 callback/resultToObs 필수라 sync 사용
        "diarization": diarization,
        "fullText": True,
        "wordAlignment": False,
    }
    # 참석자 이름 키워드 부스팅 (대화 중 언급되는 이름 인식률 향상)
    if names:
        body["boostings"] = [{"words": n} for n in names[:20]]

    invoke = cfg["CLOVA_INVOKE_URL"].rstrip("/")
    print("[clova] 변환 요청 (sync — 완료까지 대기)")
    res = requests.post(
        f"{invoke}/recognizer/object-storage",
        headers=headers, json=body, timeout=1800,  # 최대 30분 대기
    )
    res.raise_for_status()
    result = res.json()
    if result.get("result") != "COMPLETED":
        raise RuntimeError(f"CLOVA 변환 실패: {result}")
    print("[clova] 변환 완료")
    return result


def build_speaker_transcript(clova_result: dict) -> str:
    """화자별 발화를 '화자N: 내용' 형식으로, 연속 발화는 병합"""
    lines = []
    prev_speaker = None
    buf = []
    for seg in clova_result.get("segments", []):
        speaker = (seg.get("speaker") or {}).get("label", "?")
        text = (seg.get("textEdited") or seg.get("text") or "").strip()
        if not text:
            continue
        if speaker != prev_speaker and buf:
            lines.append(f"**화자{prev_speaker}**: {' '.join(buf)}")
            buf = []
        buf.append(text)
        prev_speaker = speaker
    if buf:
        lines.append(f"**화자{prev_speaker}**: {' '.join(buf)}")
    return "\n\n".join(lines)


# ---------- 4. Claude 요약 ----------

TEMPLATES_DIR = SCRIPT_DIR.parent / "templates"

# templates/default.md까지 없을 때 파이프라인이 죽지 않기 위한 최후 폴백
FALLBACK_TEMPLATE = """## 요약
(3~5문장 핵심 요약)

## 주요 논의 사항
(주제별 정리)

## 결정 사항
(명확히 결정된 것만, 없으면 "없음")

## 액션 아이템
(- [ ] 담당자(추정): 할 일 형식, 없으면 "없음")"""


def load_template(cfg: dict, title: str) -> str:
    """회의 제목 키워드 매칭으로 요약 템플릿 선택.

    TEMPLATE_RULES="키워드:템플릿명,키워드:템플릿명,..." 형식이며
    앞에서부터 제목에 키워드가 포함되는(대소문자 무시) 첫 규칙을 적용,
    매칭이 없으면 default 템플릿을 사용한다.
    """
    name = "default"
    for rule in cfg.get("TEMPLATE_RULES", "").split(","):
        # 키워드에 ':'가 들어갈 수 있어 마지막 ':' 기준으로 분리
        keyword, _, tmpl = rule.strip().rpartition(":")
        if keyword and tmpl and keyword.lower() in title.lower():
            name = tmpl
            break
    path = TEMPLATES_DIR / f"{name}.md"
    if not path.exists() and name != "default":
        print(f"[template] {path.name} 없음 → default 사용")
        path = TEMPLATES_DIR / "default.md"
    if not path.exists():
        print("[template] default.md 없음 → 내장 기본 템플릿 사용")
        return FALLBACK_TEMPLATE
    print(f"[template] {path.stem}")
    return path.read_text(encoding="utf-8").strip()


def list_project_notes(cfg: dict) -> list:
    """PROJECTS_DIR 하위(서브폴더 포함)의 md 노트 이름(stem) 목록"""
    projects_dir = cfg.get("PROJECTS_DIR", "")
    if not projects_dir:
        return []
    root = Path(projects_dir)
    if not root.is_dir():
        print(f"[projects] 디렉토리 없음: {root}")
        return []
    return sorted({p.stem for p in root.rglob("*.md") if p.stem})


def parse_project_aliases(cfg: dict, valid: set) -> list:
    """PROJECT_ALIASES="별칭:노트명,..." → [(별칭, 노트명)]. 없는 노트는 경고 후 제외"""
    pairs = []
    for rule in cfg.get("PROJECT_ALIASES", "").split(","):
        alias, _, note = rule.strip().rpartition(":")
        if not alias or not note:
            continue
        if note not in valid:
            print(f"[projects] 별칭 '{alias}'의 노트 '{note}' 없음 → 무시")
            continue
        pairs.append((alias, note))
    return pairs


def build_project_block(cfg: dict) -> str:
    """관련 프로젝트 선정 지시 + 후보 목록 + 별칭 힌트 프롬프트 블록"""
    stems = list_project_notes(cfg)
    if not stems:
        return ""
    aliases = parse_project_aliases(cfg, set(stems))
    alias_lines = ""
    if aliases:
        alias_lines = "\n프로젝트 별칭 (회의에서 이렇게 불릴 수 있음):\n" + "\n".join(
            f"- {alias} → {note}" for alias, note in aliases
        )
    return f"""
회의록 맨 끝에는 "## 🔗 관련 프로젝트" 섹션을 추가하세요.
회의 제목과 전사록 내용을 근거로, 아래 프로젝트 노트 목록에 있는 이름 그대로만 골라
"- [[노트명]] (관련 근거 한 줄)" 형식으로 나열하세요.
목록에 없는 이름을 새로 만들지 말고, 관련 프로젝트가 없으면 "없음"이라고만 적으세요.

프로젝트 노트 목록: {", ".join(stems)}
{alias_lines}
"""


def extract_related_projects(summary: str, valid: set) -> list:
    """요약의 '관련 프로젝트' 섹션에서 실존 노트 [[링크]]만 추출"""
    in_section = False
    found = []
    for line in summary.splitlines():
        if line.startswith("## "):
            in_section = "관련 프로젝트" in line
            continue
        if not in_section:
            continue
        for name in re.findall(r"\[\[([^\]|#]+)", line):
            name = name.strip()
            if name in valid and name not in found:
                found.append(name)
    return found


def summarize(cfg: dict, title: str, transcript: str, attendees: list = None) -> str:
    attendee_block = ""
    if attendees:
        attendee_block = f"""
참석자 명단: {", ".join(attendees)}

전사록의 화자 라벨(화자1, 화자2...)을 대화 내용(자기 언급, 호칭, 역할 맥락)을 근거로
참석자 실명과 매핑해주세요. 회의록 맨 앞에 아래 형식의 매핑 표를 넣고,
요약/결정사항/액션아이템에서는 확신할 수 있는 경우 실명을 사용하세요.
근거가 부족한 화자는 억지로 매핑하지 말고 "화자N (미상)"으로 남기세요.

## 화자 매핑 (추정)
- 화자1: 이름 (근거 한 줄) 또는 미상
"""

    template = load_template(cfg, title)
    project_block = build_project_block(cfg)
    prompt = f"""다음은 "{title}" 회의의 화자분리 전사록입니다. 아래 형식의 한국어 회의록으로 정리해주세요.
{attendee_block}{project_block}
{template}

전사록:
{transcript}"""

    res = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": cfg["ANTHROPIC_API_KEY"],
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-sonnet-4-6",
            "max_tokens": 4000,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=300,
    )
    res.raise_for_status()
    return "".join(
        b.get("text", "") for b in res.json()["content"] if b.get("type") == "text"
    )


# ---------- 5. Obsidian 저장 ----------

def write_obsidian_note(
    cfg: dict, title: str, start_dt: datetime, end_dt: datetime,
    summary: str, transcript: str, wav_path: Path, attendees: list = None,
    projects: list = None,
) -> Path:
    vault = Path(cfg["OBSIDIAN_DIR"])
    vault.mkdir(parents=True, exist_ok=True)

    date_str = start_dt.strftime("%Y-%m-%d")
    time_str = start_dt.strftime("%H%M")
    note_path = vault / f"{date_str}_{time_str}_{sanitize_filename(title)}.md"

    duration_min = int((end_dt - start_dt).total_seconds() // 60)
    participants = ""
    if attendees:
        participants = "participants: [" + ", ".join(attendees) + "]\n"
    projects_line = ""
    if projects:
        projects_line = (
            "projects: [" + ", ".join(f'"[[{p}]]"' for p in projects) + "]\n"
        )
    content = f"""---
title: "{title}"
date: {date_str}
time: {start_dt.strftime("%H:%M")} - {end_dt.strftime("%H:%M")}
duration: {duration_min}분
{participants}{projects_line}tags: [meeting]
audio: "{wav_path}"
---

# {title}

{summary}

---

## 전체 전사록 (화자분리)

{transcript}
"""
    note_path.write_text(content, encoding="utf-8")
    print(f"[obsidian] {note_path}")
    return note_path


# ---------- main ----------

def parse_manual_attendees(arg: str) -> tuple:
    """'4' → (4, [], True) / '예림,철수,민지' → (3, [이름들], True)"""
    arg = arg.strip()
    if not arg:
        return 0, [], False
    if arg.isdigit():
        return int(arg), [], True
    names = [n.strip() for n in re.split(r"[,\s]+", arg) if n.strip()]
    return len(names), names, True


def main() -> None:
    state_file = Path(sys.argv[1])
    manual_arg = sys.argv[2] if len(sys.argv) > 2 else ""
    state = json.loads(state_file.read_text())
    cfg = load_config()

    start_ts = state["start_ts"]
    end_ts = state.get("end_ts") or int(time.time())
    start_dt = datetime.fromtimestamp(start_ts)
    end_dt = datetime.fromtimestamp(end_ts)
    wav_path = Path(state["wav_path"])

    try:
        # 1. 캘린더 이벤트명 + 참석자 → 파일명 바인딩
        title, attendees = get_meeting_info(cfg, start_ts, end_ts)
        speaker_count, count_fixed = len(attendees), False

        # 수동 입력이 있으면 우선 (즉석 회의, 실참석 인원 보정)
        m_count, m_names, m_fixed = parse_manual_attendees(manual_arg)
        if m_fixed:
            speaker_count, count_fixed = m_count, True
            if m_names:
                attendees = m_names
        print(f"[calendar] 회의명: {title} / 참석자: {attendees or '미상'}"
              f" ({speaker_count}명{', 고정' if count_fixed else ''})")

        new_name = (
            f"{start_dt.strftime('%Y-%m-%d_%H%M')}_{sanitize_filename(title)}.wav"
        )
        new_path = wav_path.parent / new_name
        wav_path.rename(new_path)
        wav_path = new_path

        # 2~3. 업로드 + 화자분리 STT (화자 수/이름 힌트 반영)
        data_key = upload_to_ncp(cfg, wav_path)
        clova_result = clova_transcribe(
            cfg, data_key,
            speaker_count=speaker_count, count_fixed=count_fixed,
            names=attendees,
        )
        transcript = build_speaker_transcript(clova_result)
        if not transcript:
            raise RuntimeError("전사 결과가 비어 있음")

        # 4. 요약 (참석자 실명 매핑 + 관련 프로젝트 선정 포함)
        summary = summarize(cfg, title, transcript, attendees)
        projects = extract_related_projects(
            summary, set(list_project_notes(cfg))
        )
        if projects:
            print(f"[projects] 관련 프로젝트: {projects}")

        # 5. Obsidian 저장
        note = write_obsidian_note(
            cfg, title, start_dt, end_dt, summary, transcript, wav_path,
            attendees, projects,
        )

        state_file.unlink(missing_ok=True)
        notify("회의록 완성 ✅", f"{title} → {note.name}")
    except Exception as e:
        print(f"[error] {e}")
        # 실패해도 세션 파일은 지워서 다음 녹음이 가능하게 하되, 백업 남김
        state_file.rename(state_file.with_suffix(".failed.json"))
        notify("회의록 생성 실패 ⚠️", str(e)[:100])
        raise


if __name__ == "__main__":
    main()