import json
from pathlib import Path

import pytest

from orchestrator.engine.context import ExecutionContext
from orchestrator.engine.dag import DAG, Node, NodeResult, Scheduler
from orchestrator.observability.event_log import JsonlEventSink, read_events


def test_emit_writes_valid_jsonl_line(tmp_path: Path):
    sink = JsonlEventSink(path=tmp_path / "events.jsonl")
    sink.emit("node_started", node_id="a")
    sink.emit("node_succeeded", node_id="a")

    lines = (tmp_path / "events.jsonl").read_text().strip().split("\n")
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["event_type"] == "node_started"
    assert first["node_id"] == "a"
    assert "timestamp" in first


def test_in_memory_events_match_file_contents(tmp_path: Path):
    sink = JsonlEventSink(path=tmp_path / "events.jsonl")
    sink.emit("a")
    sink.emit("b", extra=1)

    from_file = read_events(tmp_path / "events.jsonl")
    assert [e["event_type"] for e in from_file] == ["a", "b"]
    assert sink.events == from_file


def test_read_events_ignores_blank_lines(tmp_path: Path):
    path = tmp_path / "events.jsonl"
    path.write_text('{"event_type": "x"}\n\n{"event_type": "y"}\n')
    events = read_events(path)
    assert [e["event_type"] for e in events] == ["x", "y"]


@pytest.mark.asyncio
async def test_scheduler_run_produces_expected_event_types(tmp_path: Path):
    async def ok(node, context):
        return NodeResult(success=True)

    dag = DAG()
    dag.add_node(Node(id="a", run=ok))

    sink = JsonlEventSink(path=tmp_path / "run.jsonl")
    await Scheduler(event_sink=sink).run(dag, ExecutionContext(run_id="e1"))

    event_types = [e["event_type"] for e in sink.events]
    assert "run_started" in event_types
    assert "node_started" in event_types
    assert "node_succeeded" in event_types
    assert "run_completed" in event_types
    assert event_types.index("run_started") < event_types.index("node_started")
    assert event_types.index("node_succeeded") < event_types.index("run_completed")
