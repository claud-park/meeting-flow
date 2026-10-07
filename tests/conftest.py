import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


@pytest.fixture
def cfg(tmp_path):
    """테스트용 설정: 모든 경로를 tmp_path 아래로 돌린다."""
    from meetingflow import config
    c = dict(config.DEFAULTS)
    c["MEETINGS_DIR"] = str(tmp_path / "Meetings")
    c["OBSIDIAN_DIR"] = str(tmp_path / "vault" / "Meetings")
    c["PROJECTS_DIR"] = str(tmp_path / "vault" / "Projects")
    c["CALENDAR_NAME"] = "work@example.com"
    c["ANTHROPIC_API_KEY"] = "test-key"
    (tmp_path / "Meetings").mkdir()
    (tmp_path / "vault" / "Meetings").mkdir(parents=True)
    (tmp_path / "vault" / "Projects").mkdir(parents=True)
    return c
