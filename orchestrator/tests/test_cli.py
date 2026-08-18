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


def test_main_returns_nonzero_for_unwired_scenario(capsys):
    exit_code = main(["run", "--scenario", "ambiguous"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "ambiguous" in captured.err
