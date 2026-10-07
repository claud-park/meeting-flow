"""macOS 알림. terminal-notifier가 있으면 클릭 동작을 붙이고, 없으면 osascript로 폴백."""
from __future__ import annotations

import shutil
import subprocess


def has_terminal_notifier() -> bool:
    return shutil.which("terminal-notifier") is not None


def build_command(title: str, message: str, execute: str | None = None,
                  open_url: str | None = None, group: str | None = None) -> list:
    cmd = ["terminal-notifier", "-title", title, "-message", message]
    if execute:
        cmd += ["-execute", execute]
    if open_url:
        cmd += ["-open", open_url]
    if group:
        cmd += ["-group", group]
    return cmd


def _osascript_command(title: str, message: str, clickable: bool) -> list:
    if clickable:
        message = f"{message} (타임블록 검토 트리거로 열어 주세요)"
    safe_msg = message.replace("\\", "\\\\").replace('"', '\\"')
    safe_title = title.replace("\\", "\\\\").replace('"', '\\"')
    return ["osascript", "-e",
            f'display notification "{safe_msg}" with title "{safe_title}"']


def notify(title: str, message: str, execute: str | None = None,
           open_url: str | None = None, group: str | None = None,
           run=subprocess.run) -> None:
    """알림을 보낸다. 어떤 경우에도 예외를 밖으로 내지 않는다."""
    try:
        if has_terminal_notifier():
            cmd = build_command(title, message, execute, open_url, group)
        else:
            cmd = _osascript_command(title, message, clickable=bool(execute or open_url))
        run(cmd, check=False, capture_output=True, timeout=10)
    except Exception as e:  # noqa: BLE001
        print(f"[notify] 알림 실패: {e}")
