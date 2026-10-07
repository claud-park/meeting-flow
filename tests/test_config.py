from datetime import time
from pathlib import Path

from meetingflow import config


def test_defaults_applied_when_key_missing(tmp_path):
    p = tmp_path / "config.env"
    p.write_text('MEETINGS_DIR="$HOME/M"\n', encoding="utf-8")
    cfg = config.load_config(p)
    assert cfg["REVIEW_PORT"] == "47321"
    assert cfg["MY_NAMES"] == "Claud,클로드"
    assert cfg["MEETINGS_DIR"] == str(Path.home() / "M")


def test_file_value_overrides_default(tmp_path):
    p = tmp_path / "config.env"
    p.write_text('REVIEW_PORT="50000"  # 주석\nWORK_HOURS=09:00-17:00\n', encoding="utf-8")
    cfg = config.load_config(p)
    assert cfg["REVIEW_PORT"] == "50000"
    assert config.work_hours(cfg) == (time(9, 0), time(17, 0))


def test_empty_value_falls_back_to_default(tmp_path):
    p = tmp_path / "config.env"
    p.write_text('TIMEBLOCK_CALENDAR=""\nCALENDAR_NAME="me@x.com"\n', encoding="utf-8")
    cfg = config.load_config(p)
    assert cfg["TIMEBLOCK_CALENDAR"] == ""
    assert config.timeblock_calendar(cfg) == "me@x.com"


def test_my_names_split_and_strip():
    assert config.my_names({"MY_NAMES": " Claud, 클로드 ,"}) == ["Claud", "클로드"]
    assert config.my_names({"MY_NAMES": ""}) == []


def test_briefs_dir_under_obsidian(cfg):
    assert config.briefs_dir(cfg) == Path(cfg["OBSIDIAN_DIR"]) / "_briefs"


def test_parse_hhmm():
    assert config.parse_hhmm("9:05") == time(9, 5)
    assert config.parse_hhmm("18:00") == time(18, 0)
