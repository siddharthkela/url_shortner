"""Shared execution state passed across every stage, plus an immutable decision
lineage: an append-only record of what each stage decided and why. This is
what makes cross-stage reasoning auditable rather than a black box.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

_decision_ids = itertools.count(1)


@dataclass(frozen=True)
class DecisionRecord:
    id: int
    stage: str
    summary: str
    rationale: str
    timestamp: str
    inputs: Dict[str, Any] = field(default_factory=dict)
    outputs: Dict[str, Any] = field(default_factory=dict)


class ExecutionContext:
    """Mutable per-run state: node outputs plus the append-only decision lineage.

    A ``replan_hook`` may be attached by the engine so stages can request a
    live DAG mutation (see engine/replan.py) without importing the scheduler
    directly.
    """

    def __init__(self, run_id: str):
        self.run_id = run_id
        self.outputs: Dict[str, Any] = {}
        self._lineage: List[DecisionRecord] = []
        self.replan_hook: Optional[Callable[..., None]] = None

    def set_output(self, node_id: str, value: Any) -> None:
        self.outputs[node_id] = value

    def get_output(self, node_id: str, default: Any = None) -> Any:
        return self.outputs.get(node_id, default)

    def record_decision(
        self,
        stage: str,
        summary: str,
        rationale: str,
        inputs: Optional[Dict[str, Any]] = None,
        outputs: Optional[Dict[str, Any]] = None,
    ) -> DecisionRecord:
        record = DecisionRecord(
            id=next(_decision_ids),
            stage=stage,
            summary=summary,
            rationale=rationale,
            timestamp=datetime.now(timezone.utc).isoformat(),
            inputs=dict(inputs or {}),
            outputs=dict(outputs or {}),
        )
        self._lineage.append(record)
        return record

    @property
    def lineage(self) -> List[DecisionRecord]:
        return list(self._lineage)

    def replan(self, new_nodes: List[Any], new_edges: Optional[Dict[str, List[str]]] = None, reason: str = "") -> None:
        if self.replan_hook is None:
            raise RuntimeError("replan() called outside a running engine (no replan_hook attached)")
        self.replan_hook(new_nodes, new_edges or {}, reason)
