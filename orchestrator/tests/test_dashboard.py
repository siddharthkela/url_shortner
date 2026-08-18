from pathlib import Path

import pytest

from orchestrator.engine.context import ExecutionContext
from orchestrator.engine.dag import DAG, Node, NodeResult, NodeStatus, Scheduler
from orchestrator.observability.dashboard import compute_layers, render_dag_svg, render_dashboard_html, write_dashboard
from orchestrator.observability.event_log import JsonlEventSink, read_events
from orchestrator.observability.metrics import compute_metrics


def ok():
    async def _run(node, context):
        return NodeResult(success=True)

    return _run


def _sample_dag() -> DAG:
    dag = DAG()
    dag.add_node(Node(id="a", run=ok()))
    dag.add_node(Node(id="b", run=ok(), depends_on=["a"]))
    dag.add_node(Node(id="c", run=ok(), depends_on=["a"]))
    dag.add_node(Node(id="join", run=ok(), depends_on=["b", "c"]))
    return dag


def test_compute_layers_reflects_dependency_depth():
    dag = _sample_dag()
    layers = compute_layers(dag)
    assert layers["a"] == 0
    assert layers["b"] == 1
    assert layers["c"] == 1
    assert layers["join"] == 2


def test_render_dag_svg_contains_node_ids_and_is_valid_svg_wrapper():
    dag = _sample_dag()
    svg = render_dag_svg(dag)
    assert svg.startswith("<svg")
    assert svg.endswith("</svg>")
    for node_id in ["a", "b", "c", "join"]:
        assert node_id in svg


@pytest.mark.asyncio
async def test_render_dashboard_html_end_to_end_from_a_real_run(tmp_path: Path):
    dag = _sample_dag()
    sink = JsonlEventSink(path=tmp_path / "events.jsonl")
    await Scheduler(event_sink=sink).run(dag, ExecutionContext(run_id="dash1"))

    events = read_events(tmp_path / "events.jsonl")
    metrics = compute_metrics(events)
    html = render_dashboard_html(run_id="dash1", dag=dag, metrics=metrics)

    assert "dash1" in html
    assert "100%" in html  # success rate stat tile, all 4 nodes succeeded
    assert "<svg" in html
    for node_id in ["a", "b", "c", "join"]:
        assert node_id in html


@pytest.mark.asyncio
async def test_write_dashboard_creates_readable_file(tmp_path: Path):
    dag = _sample_dag()
    sink = JsonlEventSink(path=tmp_path / "events.jsonl")
    await Scheduler(event_sink=sink).run(dag, ExecutionContext(run_id="dash2"))
    metrics = compute_metrics(sink.events)

    out_path = tmp_path / "dashboard.html"
    write_dashboard(out_path, run_id="dash2", dag=dag, metrics=metrics)

    assert out_path.exists()
    content = out_path.read_text()
    assert "<html>" in content
    assert "dash2" in content


def test_dashboard_reflects_failed_node_status_color():
    dag = DAG()
    dag.add_node(Node(id="a", run=ok()))
    dag.nodes["a"].status = NodeStatus.FAILED  # simulate post-run state directly
    svg = render_dag_svg(dag)
    assert "failed" in svg
