"""CLI entrypoint: python -m orchestrator run --scenario <name>"""
import argparse
import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

SCENARIO_RUNNERS = {}


def _load_scenario_runners():
    """Imported lazily so `orchestrator run --scenario X` for an unwired X
    still gives a clean error instead of an ImportError from scenarios that
    don't exist yet during incremental development.
    """
    global SCENARIO_RUNNERS
    if SCENARIO_RUNNERS:
        return SCENARIO_RUNNERS
    try:
        from orchestrator.scenarios import greenfield_qr_code
        SCENARIO_RUNNERS["greenfield"] = greenfield_qr_code.run
    except ImportError:
        pass
    try:
        from orchestrator.scenarios import brownfield_rate_limit
        SCENARIO_RUNNERS["brownfield"] = brownfield_rate_limit.run
    except ImportError:
        pass
    try:
        from orchestrator.scenarios import ambiguous_analytics
        SCENARIO_RUNNERS["ambiguous"] = ambiguous_analytics.run
    except ImportError:
        pass
    return SCENARIO_RUNNERS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="orchestrator")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Execute a scenario end to end")
    run_parser.add_argument(
        "--scenario",
        required=True,
        choices=["greenfield", "brownfield", "ambiguous"],
        help="Which demonstration scenario to run",
    )
    run_parser.add_argument(
        "--autonomy",
        default="assisted",
        choices=["dry_run", "assisted", "autonomous"],
        help="Autonomy level controlling which gates pause for human approval",
    )
    run_parser.add_argument(
        "--auto-approve",
        action="store_true",
        help="Auto-approve every approval checkpoint (non-interactive demo runs)",
    )
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "run":
        runners = _load_scenario_runners()
        runner = runners.get(args.scenario)
        if runner is None:
            print(f"Scenario runner not wired yet: {args.scenario}", file=sys.stderr)
            return 1

        result = asyncio.run(runner(repo_root=str(REPO_ROOT), auto_approve_all=args.auto_approve))
        if not result.succeeded:
            print(f"Scenario '{args.scenario}' did not complete successfully: {result.status_summary()}", file=sys.stderr)
            return 1
        print(f"Scenario '{args.scenario}' completed successfully.")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
