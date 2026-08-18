import orchestrator.cli as cli
from orchestrator.cli import build_parser, main


def test_parser_requires_scenario_for_run():
    parser = build_parser()
    args = parser.parse_args(["run", "--scenario", "greenfield"])
    assert args.scenario == "greenfield"
    assert args.autonomy == "assisted"
    assert args.auto_approve is False


def test_parser_accepts_autonomy_and_auto_approve():
    parser = build_parser()
    args = parser.parse_args(["run", "--scenario", "brownfield", "--autonomy", "autonomous", "--auto-approve"])
    assert args.autonomy == "autonomous"
    assert args.auto_approve is True


class _FakeResult:
    def __init__(self, succeeded: bool, summary=None):
        self.succeeded = succeeded
        self._summary = summary or {}

    def status_summary(self):
        return self._summary


def test_main_returns_nonzero_when_no_runner_is_wired(monkeypatch, capsys):
    """All three scenarios are real and wired now — this exercises the
    fallback path directly via monkeypatching rather than relying on one of
    them incidentally failing to import (a real run against the actual repo
    is never something a unit test should trigger).
    """
    monkeypatch.setattr(cli, "_load_scenario_runners", lambda: {})

    exit_code = main(["run", "--scenario", "greenfield"])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "greenfield" in captured.err


def test_main_returns_zero_and_prints_success_for_a_succeeding_runner(monkeypatch, capsys):
    async def fake_runner(repo_root, auto_approve_all):
        return _FakeResult(succeeded=True)

    monkeypatch.setattr(cli, "_load_scenario_runners", lambda: {"greenfield": fake_runner})

    exit_code = main(["run", "--scenario", "greenfield", "--auto-approve"])

    assert exit_code == 0
    assert "completed successfully" in capsys.readouterr().out


def test_main_returns_nonzero_and_prints_status_summary_for_a_failing_runner(monkeypatch, capsys):
    async def fake_runner(repo_root, auto_approve_all):
        return _FakeResult(succeeded=False, summary={"run_tests": "failed"})

    monkeypatch.setattr(cli, "_load_scenario_runners", lambda: {"brownfield": fake_runner})

    exit_code = main(["run", "--scenario", "brownfield", "--auto-approve"])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "did not complete successfully" in captured.err
    assert "run_tests" in captured.err
