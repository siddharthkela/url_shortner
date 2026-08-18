"""Bounded retries, fallback, rollback, and a run-level safe-stop circuit
breaker — the reliability controls the assignment calls out explicitly.

These plug into the Scheduler's existing extension points (retry_executor,
circuit breaker hook) from dag.py without changing its core loop.
"""
from __future__ import annotations

import asyncio
import subprocess
from dataclasses import dataclass
from typing import Awaitable, Callable, List, Optional

from orchestrator.engine.context import ExecutionContext
from orchestrator.engine.dag import EventSink, Node, NodeResult

SleepFn = Callable[[float], Awaitable[None]]


@dataclass
class RetryPolicy:
    max_attempts: int = 1
    initial_backoff: float = 0.0
    multiplier: float = 2.0


def make_retrying_executor(sleep_fn: SleepFn = asyncio.sleep, event_sink: Optional[EventSink] = None):
    """Returns a retry_executor compatible with Scheduler(retry_executor=...).

    Emits a "node_retry_attempt" event on every failed-but-not-final attempt
    so the event log carries enough information for metrics.py to compute
    retry frequency and MTTR without needing to inspect Node state directly.
    """
    sink = event_sink or EventSink()

    async def _execute(node: Node, context: ExecutionContext) -> NodeResult:
        policy = node.retry_policy or RetryPolicy(max_attempts=1)
        backoff = policy.initial_backoff
        last_result: Optional[NodeResult] = None

        for attempt in range(1, policy.max_attempts + 1):
            node.attempts = attempt
            try:
                result = await node.run(node, context)
            except Exception as exc:  # noqa: BLE001
                result = NodeResult(success=False, error=str(exc))

            if result.success:
                return result

            last_result = result
            if attempt < policy.max_attempts:
                sink.emit("node_retry_attempt", node_id=node.id, attempt=attempt, error=result.error)
                if backoff > 0:
                    await sleep_fn(backoff)
                backoff *= policy.multiplier

        if node.fallback is not None:
            try:
                fallback_result = await node.fallback(node, context)
            except Exception as exc:  # noqa: BLE001
                fallback_result = NodeResult(success=False, error=str(exc))
            if fallback_result.success:
                fallback_result.used_fallback = True
                return fallback_result
            return fallback_result

        return last_result or NodeResult(success=False, error="node produced no result")

    return _execute


@dataclass
class CircuitBreaker:
    """Run-level safe-stop: trips when the run's failure count or failure
    rate crosses a threshold, after which the scheduler stops starting new
    nodes and marks everything still pending as BLOCKED.
    """

    failure_threshold: Optional[int] = None
    failure_rate_threshold: Optional[float] = None
    min_samples: int = 3

    def __post_init__(self) -> None:
        self._successes = 0
        self._failures = 0

    def record_result(self, success: bool) -> None:
        if success:
            self._successes += 1
        else:
            self._failures += 1

    @property
    def total(self) -> int:
        return self._successes + self._failures

    def should_trip(self) -> bool:
        if self.failure_threshold is not None and self._failures >= self.failure_threshold:
            return True
        if (
            self.failure_rate_threshold is not None
            and self.total >= self.min_samples
            and (self._failures / self.total) >= self.failure_rate_threshold
        ):
            return True
        return False


def git_rollback(files: List[str], repo_root: str) -> Callable[[Node, ExecutionContext], None]:
    """Builds a rollback function that reverts tracked-file changes and
    removes newly created untracked files, scoped only to the given paths
    inside repo_root. Never touches anything outside that file list.
    """

    def _rollback(node: Node, context: ExecutionContext) -> None:
        # Run per-file: `git checkout -- a b` aborts the *entire* command if any
        # single pathspec is untracked, which would silently skip reverting the
        # tracked files too. Per-file calls isolate that failure to just the
        # untracked one, which `git clean` handles instead.
        for f in files:
            subprocess.run(["git", "checkout", "--", f], cwd=repo_root, capture_output=True)
            subprocess.run(["git", "clean", "-f", "--", f], cwd=repo_root, capture_output=True)

    return _rollback
