# Agentic SDLC Orchestrator

An orchestration engine that automates the software delivery lifecycle —
requirements → codebase analysis → design → implementation → tests → docs →
release — as an explicit dependency graph with parallel execution, human
approval checkpoints, bounded retries/rollback/safe-stop, policy guardrails,
audit-grade observability, and dynamic re-planning. This is the actual
deliverable for the assignment; the [url-shortener](../README.md) app in the
parent directory is this engine's **target/demo system**, not the point of
the exercise.

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for how it's built and
[`FINAL_SUMMARY.md`](FINAL_SUMMARY.md) for the plan/rationale, risks, and
limitations across all three demo runs.

## Setup

Requires Python 3.9+. No API keys, no external services, no Docker.

```bash
cd orchestrator
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Run the tests

```bash
python -m pytest -q
```

106 tests, fully offline, run in ~1 second. Every engine mechanism (DAG
scheduling, parallelism, gates, retries/fallback/rollback, the safe-stop
circuit breaker, approval checkpoints, dynamic re-planning, observability)
is exercised against a `DeterministicAgent` — no network calls, no git
operations against the real repo, no Java toolchain required.

## Run a scenario for real

This is different from the test suite: it actually creates a git branch,
writes real Java files into the parent `url-shortener` repo, runs the
app's real `./mvnw test`, and (on approval) commits and pushes the branch.
Run from the **repo root** (one level up from `orchestrator/`):

```bash
cd ..   # if you're inside orchestrator/
python -m orchestrator run --scenario greenfield --auto-approve
python -m orchestrator run --scenario brownfield --auto-approve
python -m orchestrator run --scenario ambiguous --auto-approve
```

- `--auto-approve` auto-approves every human-approval checkpoint, for a
  non-interactive demo run. Omit it to be prompted interactively at the
  `release_readiness` gate (autonomy level `assisted`, the default: only
  nodes explicitly marked `requires_approval=True` pause).
- `--autonomy dry_run` pauses at *every* node for approval.
  `--autonomy autonomous` never pauses (only the circuit breaker can halt
  the run).
- Each run creates/reuses a branch named `orchestrator-demo/<scenario>`,
  leaves it **pushed but unmerged** (the human-approval boundary — this
  tool does not merge to `main`), and writes `events.jsonl`, `dashboard.html`,
  and `SUMMARY.md` into `orchestrator/runs/<scenario>/` on `main`.
- Open `orchestrator/runs/<scenario>/dashboard.html` directly in a browser
  to see the executed DAG (colored by final status) and reliability metrics.

Each `_apply_*` file-patching function is idempotent — re-running a
scenario against a branch it already touched is a safe no-op on files
already patched, not a duplicate edit. (This was a real bug on the first
manual test of the greenfield scenario; see `FINAL_SUMMARY.md`.)

## What's pluggable

Every SDLC stage delegates to an `Agent` (`orchestrator/agents/base.py`).
All three demo scenarios use `DeterministicAgent` — scripted, real,
offline logic (real Java gets written, real tests get run) rather than
live LLM calls. `ClaudeAgent` exists on the same interface for real
Anthropic API calls and is fully unit-tested (prompt building, response
parsing, and the full call path via an injected fake client), but isn't
used by any demo run — no API key is configured or required anywhere in
this deliverable. Swapping a stage from scripted to live reasoning is a
constructor argument, not a redesign.
