"""Human approval checkpoints and autonomy levels.

"Controlled autonomy" per the assignment: agents execute multi-step work,
but humans approve high-impact actions. The autonomy level controls *which*
nodes actually pause; individual nodes still declare requires_approval=True
for the things that always warrant a human look regardless of autonomy
level (e.g. merging/releasing).
"""
from __future__ import annotations

from enum import Enum
from typing import Callable, Optional

from orchestrator.engine.context import ExecutionContext
from orchestrator.engine.dag import EventSink, Node


class AutonomyLevel(str, Enum):
    DRY_RUN = "dry_run"  # pause for approval on every node
    ASSISTED = "assisted"  # pause only on nodes explicitly marked requires_approval
    AUTONOMOUS = "autonomous"  # never pause; only the circuit breaker (safe-stop) can halt the run


DecisionFn = Callable[[Node, ExecutionContext], bool]


def auto_approve(node: Node, context: ExecutionContext) -> bool:
    return True


def auto_deny(node: Node, context: ExecutionContext) -> bool:
    return False


def interactive_prompt(node: Node, context: ExecutionContext) -> bool:
    answer = input(f"[approval required] approve node '{node.id}'? [y/N] ")
    return answer.strip().lower() in ("y", "yes")


class ApprovalManager:
    """Callable compatible with Scheduler(approval_manager=...)."""

    def __init__(
        self,
        autonomy: AutonomyLevel = AutonomyLevel.ASSISTED,
        decision_fn: DecisionFn = interactive_prompt,
        event_sink: Optional[EventSink] = None,
    ) -> None:
        self.autonomy = autonomy
        self.decision_fn = decision_fn
        self.event_sink = event_sink or EventSink()

    def gate_required(self, node: Node) -> bool:
        if self.autonomy == AutonomyLevel.DRY_RUN:
            return True
        if self.autonomy == AutonomyLevel.AUTONOMOUS:
            return False
        return node.requires_approval  # ASSISTED

    async def __call__(self, node: Node, context: ExecutionContext) -> bool:
        if not self.gate_required(node):
            return True

        self.event_sink.emit("approval_requested", node_id=node.id, autonomy=self.autonomy.value)
        approved = self.decision_fn(node, context)
        context.record_decision(
            stage="approval",
            summary=f"{'Approved' if approved else 'Denied'} node '{node.id}'",
            rationale=f"autonomy={self.autonomy.value}, requires_approval={node.requires_approval}",
        )
        self.event_sink.emit("approval_decided", node_id=node.id, approved=approved)
        return approved
