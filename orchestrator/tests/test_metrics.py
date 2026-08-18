from datetime import datetime, timedelta, timezone

from orchestrator.observability.metrics import compute_metrics

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def ts(offset_seconds: float) -> str:
    return (BASE + timedelta(seconds=offset_seconds)).isoformat()


def test_success_rate_and_node_counts():
    events = [
        {"event_type": "node_succeeded", "node_id": "a", "timestamp": ts(1)},
        {"event_type": "node_failed", "node_id": "b", "timestamp": ts(1)},
        {"event_type": "node_succeeded", "node_id": "c", "timestamp": ts(1)},
    ]
    metrics = compute_metrics(events)
    assert metrics.total_nodes == 3
    assert metrics.succeeded_nodes == 2
    assert metrics.failed_nodes == 1
    assert abs(metrics.success_rate - (2 / 3)) < 1e-9


def test_success_rate_is_zero_with_no_terminal_events():
    metrics = compute_metrics([{"event_type": "run_started", "timestamp": ts(0)}])
    assert metrics.total_nodes == 0
    assert metrics.success_rate == 0.0


def test_retry_count_and_frequency():
    events = [
        {"event_type": "node_retry_attempt", "node_id": "a", "attempt": 1, "timestamp": ts(0)},
        {"event_type": "node_retry_attempt", "node_id": "a", "attempt": 2, "timestamp": ts(1)},
        {"event_type": "node_succeeded", "node_id": "a", "timestamp": ts(2)},
        {"event_type": "node_succeeded", "node_id": "b", "timestamp": ts(2)},
    ]
    metrics = compute_metrics(events)
    assert metrics.retry_count == 2
    assert metrics.retry_frequency == 1.0  # 2 retries / 2 total nodes


def test_rollback_count_and_frequency():
    events = [
        {"event_type": "node_failed", "node_id": "a", "timestamp": ts(0)},
        {"event_type": "node_rolled_back", "node_id": "a", "timestamp": ts(0)},
        {"event_type": "node_succeeded", "node_id": "b", "timestamp": ts(0)},
    ]
    metrics = compute_metrics(events)
    assert metrics.rollback_count == 1
    assert metrics.rollback_frequency == 0.5


def test_mttr_computed_from_retry_to_success_for_same_node():
    events = [
        {"event_type": "node_retry_attempt", "node_id": "a", "timestamp": ts(0)},
        {"event_type": "node_succeeded", "node_id": "a", "timestamp": ts(4)},
    ]
    metrics = compute_metrics(events)
    assert metrics.mttr_seconds == 4.0


def test_mttr_averages_across_multiple_recoveries():
    events = [
        {"event_type": "node_retry_attempt", "node_id": "a", "timestamp": ts(0)},
        {"event_type": "node_succeeded", "node_id": "a", "timestamp": ts(2)},  # 2s recovery
        {"event_type": "node_retry_attempt", "node_id": "b", "timestamp": ts(10)},
        {"event_type": "node_succeeded", "node_id": "b", "timestamp": ts(16)},  # 6s recovery
    ]
    metrics = compute_metrics(events)
    assert metrics.mttr_seconds == 4.0  # (2 + 6) / 2


def test_mttr_is_none_when_nothing_ever_failed():
    events = [{"event_type": "node_succeeded", "node_id": "a", "timestamp": ts(0)}]
    assert compute_metrics(events).mttr_seconds is None


def test_total_latency_from_run_boundary_events():
    events = [
        {"event_type": "run_started", "timestamp": ts(0)},
        {"event_type": "node_succeeded", "node_id": "a", "timestamp": ts(5)},
        {"event_type": "run_completed", "timestamp": ts(7.5)},
    ]
    metrics = compute_metrics(events)
    assert metrics.total_latency_seconds == 7.5


def test_per_node_latency_from_started_to_terminal():
    events = [
        {"event_type": "node_started", "node_id": "a", "timestamp": ts(0)},
        {"event_type": "node_succeeded", "node_id": "a", "timestamp": ts(3)},
        {"event_type": "node_started", "node_id": "b", "timestamp": ts(1)},
        {"event_type": "node_failed", "node_id": "b", "timestamp": ts(1.5)},
    ]
    metrics = compute_metrics(events)
    assert metrics.per_node_latency_seconds == {"a": 3.0, "b": 0.5}
