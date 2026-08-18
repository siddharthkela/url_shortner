import subprocess
from pathlib import Path

import pytest

from orchestrator.engine.context import ExecutionContext
from orchestrator.engine.dag import DAG, Node, NodeResult, NodeStatus, Scheduler
from orchestrator.engine.reliability import CircuitBreaker, RetryPolicy, git_rollback, make_retrying_executor


async def _noop_sleep(_seconds: float) -> None:
    return None


@pytest.mark.asyncio
async def test_retries_until_success_within_bounded_attempts():
    calls = {"n": 0}

    async def flaky(node, context):
        calls["n"] += 1
        if calls["n"] < 3:
            return NodeResult(success=False, error="transient")
        return NodeResult(success=True, output="ok")

    dag = DAG()
    dag.add_node(Node(id="n", run=flaky, retry_policy=RetryPolicy(max_attempts=5)))

    result = await Scheduler(retry_executor=make_retrying_executor(sleep_fn=_noop_sleep)).run(
        dag, ExecutionContext(run_id="r1")
    )

    assert dag.nodes["n"].status == NodeStatus.SUCCEEDED
    assert calls["n"] == 3
    assert result.succeeded


@pytest.mark.asyncio
async def test_gives_up_after_max_attempts_with_no_fallback():
    calls = {"n": 0}

    async def always_fails(node, context):
        calls["n"] += 1
        return NodeResult(success=False, error="nope")

    dag = DAG()
    dag.add_node(Node(id="n", run=always_fails, retry_policy=RetryPolicy(max_attempts=3)))

    await Scheduler(retry_executor=make_retrying_executor(sleep_fn=_noop_sleep)).run(dag, ExecutionContext(run_id="r2"))

    assert calls["n"] == 3
    assert dag.nodes["n"].status == NodeStatus.FAILED


@pytest.mark.asyncio
async def test_fallback_runs_after_retries_exhausted_and_is_flagged():
    async def always_fails(node, context):
        return NodeResult(success=False, error="nope")

    async def fallback(node, context):
        return NodeResult(success=True, output="fallback-output")

    dag = DAG()
    dag.add_node(Node(id="n", run=always_fails, fallback=fallback, retry_policy=RetryPolicy(max_attempts=2)))

    context = ExecutionContext(run_id="r3")
    await Scheduler(retry_executor=make_retrying_executor(sleep_fn=_noop_sleep)).run(dag, context)

    assert dag.nodes["n"].status == NodeStatus.SUCCEEDED
    assert dag.nodes["n"].result.used_fallback is True
    assert context.get_output("n") == "fallback-output"


@pytest.mark.asyncio
async def test_failing_fallback_still_marks_node_failed():
    async def always_fails(node, context):
        return NodeResult(success=False, error="nope")

    async def failing_fallback(node, context):
        return NodeResult(success=False, error="fallback also failed")

    dag = DAG()
    dag.add_node(Node(id="n", run=always_fails, fallback=failing_fallback, retry_policy=RetryPolicy(max_attempts=1)))

    await Scheduler(retry_executor=make_retrying_executor(sleep_fn=_noop_sleep)).run(dag, ExecutionContext(run_id="r4"))

    assert dag.nodes["n"].status == NodeStatus.FAILED


def test_circuit_breaker_trips_on_failure_threshold():
    breaker = CircuitBreaker(failure_threshold=2)
    assert not breaker.should_trip()
    breaker.record_result(False)
    assert not breaker.should_trip()
    breaker.record_result(False)
    assert breaker.should_trip()


def test_circuit_breaker_trips_on_failure_rate():
    breaker = CircuitBreaker(failure_rate_threshold=0.5, min_samples=4)
    breaker.record_result(True)
    breaker.record_result(False)
    breaker.record_result(False)
    assert not breaker.should_trip()  # only 3 samples, below min_samples
    breaker.record_result(False)
    assert breaker.should_trip()  # 4 samples, 3/4 = 0.75 >= 0.5


@pytest.mark.asyncio
async def test_tripped_circuit_breaker_safe_stops_remaining_pending_nodes():
    async def fails(node, context):
        return NodeResult(success=False, error="boom")

    async def succeeds(node, context):
        return NodeResult(success=True)

    dag = DAG()
    # warmup/a/b all run in the first tick (no deps); c depends on warmup so it
    # can only become ready in the second tick, by which point a and b have
    # already failed and should have tripped the breaker — proving safe-stop
    # actually prevents new work rather than just being computed after the fact.
    dag.add_node(Node(id="warmup", run=succeeds))
    dag.add_node(Node(id="a", run=fails))
    dag.add_node(Node(id="b", run=fails))
    dag.add_node(Node(id="c", run=succeeds, depends_on=["warmup"]))

    breaker = CircuitBreaker(failure_threshold=2)
    scheduler = Scheduler(circuit_breaker=breaker)
    result = await scheduler.run(dag, ExecutionContext(run_id="r5"))

    assert dag.nodes["warmup"].status == NodeStatus.SUCCEEDED
    assert dag.nodes["a"].status == NodeStatus.FAILED
    assert dag.nodes["b"].status == NodeStatus.FAILED
    assert dag.nodes["c"].status == NodeStatus.BLOCKED
    assert not result.succeeded


def test_git_rollback_reverts_tracked_change_and_removes_untracked_file(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)

    tracked = repo / "Tracked.java"
    tracked.write_text("original content\n")
    subprocess.run(["git", "add", "Tracked.java"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)

    # Simulate a node mutating the tracked file and creating a new untracked one.
    tracked.write_text("mutated by a failed node\n")
    untracked = repo / "NewFile.java"
    untracked.write_text("should be removed on rollback\n")

    rollback = git_rollback(files=["Tracked.java", "NewFile.java"], repo_root=str(repo))
    rollback(node=None, context=None)

    assert tracked.read_text() == "original content\n"
    assert not untracked.exists()
