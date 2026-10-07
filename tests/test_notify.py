from meetingflow import notify


def test_build_command_with_execute():
    cmd = notify.build_command("제목", "본문", execute="/x/review-open.sh", group="meetingflow")
    assert cmd[0] == "terminal-notifier"
    assert cmd[cmd.index("-title") + 1] == "제목"
    assert cmd[cmd.index("-message") + 1] == "본문"
    assert cmd[cmd.index("-execute") + 1] == "/x/review-open.sh"
    assert cmd[cmd.index("-group") + 1] == "meetingflow"
    assert "-open" not in cmd


def test_build_command_with_open_url():
    cmd = notify.build_command("t", "m", open_url="obsidian://open?vault=v&file=f")
    assert cmd[cmd.index("-open") + 1] == "obsidian://open?vault=v&file=f"


def test_notify_falls_back_to_osascript(monkeypatch):
    calls = []
    monkeypatch.setattr(notify, "has_terminal_notifier", lambda: False)
    notify.notify("t", "m", execute="/x.sh", run=lambda cmd, **kw: calls.append(cmd))
    assert calls and calls[0][0] == "osascript"
    assert "타임블록 검토" in calls[0][-1]  # 클릭 불가 안내 덧붙임


def test_notify_osascript_without_execute_has_no_hint(monkeypatch):
    calls = []
    monkeypatch.setattr(notify, "has_terminal_notifier", lambda: False)
    notify.notify("t", "m", run=lambda cmd, **kw: calls.append(cmd))
    assert "타임블록 검토" not in calls[0][-1]


def test_notify_uses_terminal_notifier_when_present(monkeypatch):
    calls = []
    monkeypatch.setattr(notify, "has_terminal_notifier", lambda: True)
    notify.notify("t", "m", execute="/x.sh", run=lambda cmd, **kw: calls.append(cmd))
    assert calls[0][0] == "terminal-notifier"


def test_notify_never_raises(monkeypatch):
    monkeypatch.setattr(notify, "has_terminal_notifier", lambda: True)

    def boom(cmd, **kw):
        raise OSError("no binary")
    notify.notify("t", "m", run=boom)  # 예외가 밖으로 나오면 테스트 실패
