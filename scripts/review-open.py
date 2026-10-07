#!/usr/bin/env python3
"""검토 팝업 열기: 서버가 없으면 띄우고, 브라우저를 앱 모드로 연다. 표준 라이브러리만 사용."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from meetingflow import config, pending  # noqa: E402


def _healthy(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as r:
            return json.loads(r.read()).get("app") == "meetingflow"
    except Exception:  # noqa: BLE001
        return False


def _port_in_use(port: int) -> bool:
    import socket
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def main() -> int:
    cfg = config.load_config()
    server_file = pending.pending_dir(cfg) / ".server.json"
    port = config.int_cfg(cfg, "REVIEW_PORT")
    if server_file.exists():
        try:
            port = int(json.loads(server_file.read_text())["port"])
        except Exception:  # noqa: BLE001
            pass
    if not _healthy(port):
        port = config.int_cfg(cfg, "REVIEW_PORT")
        while _port_in_use(port):  # 다른 프로세스가 잡고 있으면 다음 포트
            port += 1
        pybin = sys.executable
        subprocess.Popen([pybin, "-m", "meetingflow.review_server", "--port", str(port)],
                         cwd=str(Path(__file__).resolve().parent),
                         stdout=open(config.meetings_dir(cfg) / ".review.log", "a"),
                         stderr=subprocess.STDOUT, start_new_session=True)
        for _ in range(40):
            if _healthy(port):
                break
            time.sleep(0.25)
    url = f"http://127.0.0.1:{port}/"
    chrome = "/Applications/Google Chrome.app"
    if Path(chrome).exists():
        subprocess.run(["open", "-na", "Google Chrome", "--args", f"--app={url}", "--window-size=1100,760"], check=False)
    else:
        subprocess.run(["open", url], check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
