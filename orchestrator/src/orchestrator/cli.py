"""CLI entrypoint: python -m orchestrator run --scenario <name>"""
import argparse
import sys


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
        # Wired up in later phases once stages/scenarios exist.
        print(f"Scenario runner not wired yet: {args.scenario}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
