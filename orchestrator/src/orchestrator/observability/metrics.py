"""Reliability metrics computed directly from the event log: success rate,
retry frequency, rollback frequency, MTTR, and end-to-end/per-stage latency.
Nothing here is tracked separately at runtime — it's all derived after the
fact from the same audit trail a human would read, which is the point:
the metrics are provably consistent with what actually happened.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


@dataclass
class ReliabilityMetrics:
    total_nodes: int
    succeeded_nodes: int
    failed_nodes: int
    success_rate: float
    retry_count: int
    retry_frequency: float  # retries per node
    rollback_count: int
    rollback_frequency: float  # rollbacks per node
    mttr_seconds: Optional[float]
    total_latency_seconds: Optional[float]
    per_node_latency_seconds: Dict[str, float]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "total_nodes": self.total_nodes,
            "succeeded_nodes": self.succeeded_nodes,
            "failed_nodes": self.failed_nodes,
            "success_rate": self.success_rate,
            "retry_count": self.retry_count,
            "retry_frequency": self.retry_frequency,
            "rollback_count": self.rollback_count,
            "rollback_frequency": self.rollback_frequency,
            "mttr_seconds": self.mttr_seconds,
            "total_latency_seconds": self.total_latency_seconds,
            "per_node_latency_seconds": self.per_node_latency_seconds,
        }


def compute_metrics(events: List[Dict[str, Any]]) -> ReliabilityMetrics:
    succeeded = {e["node_id"] for e in events if e["event_type"] == "node_succeeded"}
    failed = {e["node_id"] for e in events if e["event_type"] == "node_failed"}
    terminal_node_ids = succeeded | failed
    total_nodes = len(terminal_node_ids)
    success_rate = (len(succeeded) / total_nodes) if total_nodes else 0.0

    retry_events = [e for e in events if e["event_type"] == "node_retry_attempt"]
    retry_count = len(retry_events)
    retry_frequency = (retry_count / total_nodes) if total_nodes else 0.0

    rollback_events = [e for e in events if e["event_type"] == "node_rolled_back"]
    rollback_count = len(rollback_events)
    rollback_frequency = (rollback_count / total_nodes) if total_nodes else 0.0

    mttr_seconds = _compute_mttr(events)

    run_started = next((e for e in events if e["event_type"] == "run_started"), None)
    run_completed = next((e for e in events if e["event_type"] == "run_completed"), None)
    total_latency_seconds = None
    if run_started and run_completed:
        total_latency_seconds = (
            _parse_ts(run_completed["timestamp"]) - _parse_ts(run_started["timestamp"])
        ).total_seconds()

    per_node_latency_seconds = _compute_per_node_latency(events)

    return ReliabilityMetrics(
        total_nodes=total_nodes,
        succeeded_nodes=len(succeeded),
        failed_nodes=len(failed),
        success_rate=success_rate,
        retry_count=retry_count,
        retry_frequency=retry_frequency,
        rollback_count=rollback_count,
        rollback_frequency=rollback_frequency,
        mttr_seconds=mttr_seconds,
        total_latency_seconds=total_latency_seconds,
        per_node_latency_seconds=per_node_latency_seconds,
    )


def _compute_mttr(events: List[Dict[str, Any]]) -> Optional[float]:
    """Mean time between a node's first failure/retry signal and its eventual
    success (via a later retry attempt or fallback), for nodes that recovered.
    """
    recoveries: List[float] = []
    by_node: Dict[str, List[Dict[str, Any]]] = {}
    for e in events:
        node_id = e.get("node_id")
        if node_id is None:
            continue
        by_node.setdefault(node_id, []).append(e)

    for node_id, node_events in by_node.items():
        first_trouble = next(
            (e for e in node_events if e["event_type"] in ("node_retry_attempt", "node_failed")), None
        )
        succeeded_event = next((e for e in node_events if e["event_type"] == "node_succeeded"), None)
        if first_trouble and succeeded_event:
            delta = (_parse_ts(succeeded_event["timestamp"]) - _parse_ts(first_trouble["timestamp"])).total_seconds()
            if delta >= 0:
                recoveries.append(delta)

    if not recoveries:
        return None
    return sum(recoveries) / len(recoveries)


def _compute_per_node_latency(events: List[Dict[str, Any]]) -> Dict[str, float]:
    started: Dict[str, str] = {}
    ended: Dict[str, str] = {}
    for e in events:
        node_id = e.get("node_id")
        if node_id is None:
            continue
        if e["event_type"] == "node_started":
            started[node_id] = e["timestamp"]
        elif e["event_type"] in ("node_succeeded", "node_failed", "node_blocked"):
            ended[node_id] = e["timestamp"]

    latencies = {}
    for node_id, start_ts in started.items():
        end_ts = ended.get(node_id)
        if end_ts:
            latencies[node_id] = (_parse_ts(end_ts) - _parse_ts(start_ts)).total_seconds()
    return latencies
