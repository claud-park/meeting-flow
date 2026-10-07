#!/usr/bin/env python3
"""설치 상태 점검. 실패 항목이 있으면 종료 코드 1."""
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from meetingflow import config  # noqa: E402

OK, WARN, FAIL = "✅", "⚠️ ", "❌"


def check(label: str, cond: bool, hint: str = "", warn_only: bool = False) -> bool:
    mark = OK if cond else (WARN if warn_only else FAIL)
    print(f"  {mark} {label}" + ("" if cond or not hint else f"  → {hint}"))
    return cond or warn_only


def main() -> int:
    results = []
    print("═══ Meeting Flow 진단 ═══")
    print("[의존성]")
    for tool, hint in (("ffmpeg", "brew install ffmpeg"), ("icalBuddy", "brew install ical-buddy"),
                       ("SwitchAudioSource", "brew install switchaudio-osx")):
        results.append(check(tool, shutil.which(tool) is not None, hint))
    results.append(check("terminal-notifier (알림 클릭 동작)", shutil.which("terminal-notifier") is not None,
                         "brew install terminal-notifier — 없으면 알림을 클릭해도 팝업이 열리지 않음", warn_only=True))

    print("[설정]")
    results.append(check("config.env 존재", config.CONFIG_PATH.exists(), "cp config.env.example config.env"))
    cfg = config.load_config()
    for key in ("CALENDAR_NAME", "OBSIDIAN_DIR", "ANTHROPIC_API_KEY", "CLOVA_INVOKE_URL", "NCP_BUCKET"):
        results.append(check(f"{key} 설정됨", bool(cfg.get(key)) and not cfg[key].startswith("xoxp-...")))
    results.append(check("MY_NAMES 설정됨 (타임블록 추출용)", bool(config.my_names(cfg))))
    if cfg.get("OBSIDIAN_DIR"):
        results.append(check("OBSIDIAN_DIR 폴더 존재", config.obsidian_dir(cfg).is_dir()))

    print("[캘린더]")
    try:
        out = subprocess.run(["icalBuddy", "calendars"], capture_output=True, text=True, timeout=15).stdout
        hint = "시스템 설정 > 개인정보 보호 > 캘린더 에서 터미널 허용, 이름은 icalBuddy calendars 로 확인"
        if not out.strip():
            hint += " / 캘린더가 하나도 보이지 않음 — 권한 확인"
        results.append(check(f"캘린더 '{cfg.get('CALENDAR_NAME')}' 보임", cfg.get("CALENDAR_NAME", "") in out, hint))
    except Exception as e:  # noqa: BLE001
        results.append(check("icalBuddy 실행", False, str(e)))

    print("[자동화]")
    uid = subprocess.run(["id", "-u"], capture_output=True, text=True).stdout.strip()
    loaded = subprocess.run(["launchctl", "print", f"gui/{uid}/com.meetingflow.tick"],
                            capture_output=True, text=True).returncode == 0
    results.append(check("launchd 틱 로드됨 (com.meetingflow.tick)", loaded, "./scripts/install-launchd.sh", warn_only=True))
    services = Path.home() / "Library" / "Services"
    results.append(check("Quick Action '타임블록 검토' 설치됨", (services / "타임블록 검토.workflow").exists(),
                         "./scripts/install-quick-actions.sh (Raycast만 쓰면 무시)", warn_only=True))
    print("  ℹ️  캘린더·미리알림 자동화 권한은 첫 반영 때 macOS가 묻습니다."
          " 미리 확인: cd scripts && ../.venv/bin/python3 -m meetingflow.calendar_io --smoke")

    bad = results.count(False)
    print(f"\n{'모든 필수 항목 통과' if not bad else f'실패 {bad}건'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
