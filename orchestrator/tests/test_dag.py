import asyncio
import time

import pytest

from orchestrator.engine.context import ExecutionContext
from orchestrator.engine.dag import DAG, GateResult, Node, NodeResult, NodeStatus, Scheduler


def ok(output=None):
    async def _run(node, context):
        return NodeResult(success=True, output=output)

    return _run


def fail(error="boom"):
    async def _run(node, context):
        return NodeResult(success=False, error=error)

    return _run


def recording(order: list, output=None):
    async def _run(node, context):
        order.append(node.id)
        return NodeResult(success=True, output=output)

    return _run


def timed(sleep_seconds: float, timeline: dict):
    async def _run(node, context):
        start = time.monotonic()
        await asyncio.sleep(sleep_seconds)
        end = time.monotonic()
        timeline[node.id] = (start, end)
        return NodeResult(success=True)

    return _run


@pytest.mark.asyncio
async def test_linear_dependencies_run_in_order():
    order = []
    dag = DAG()
    dag.add_node(Node(id="a", run=recording(order)))
    dag.add_node(Node(id="b", run=recording(order), depends_on=["a"]))
    dag.add_node(Node(id="c", run=recording(order), depends_on=["b"]))

    result = await Scheduler().run(dag, ExecutionContext(run_id="t1"))

    assert order == ["a", "b", "c"]
    assert result.succeeded


@pytest.mark.asyncio
async def test_independent_nodes_execute_concurrently():
    timeline = {}
    dag = DAG()
    dag.add_node(Node(id="a", run=timed(0.05, timeline)))
    dag.add_node(Node(id="b", run=timed(0.05, timeline)))

    started = time.monotonic()
    await Scheduler().run(dag, ExecutionContext(run_id="t2"))
    total = time.monotonic() - started

    # If these ran sequentially this would take >=0.1s; concurrently, ~0.05s.
    assert total < 0.09
    a_start, a_end = timeline["a"]
    b_start, b_end = timeline["b"]
    assert a_start < b_end and b_start < a_end  # overlapping windows


@pytest.mark.asyncio
async def test_join_node_waits_for_all_parents():
    order = []
    dag = DAG()
    dag.add_node(Node(id="a", run=recording(order)))
    dag.add_node(Node(id="b", run=recording(order)))
    dag.add_node(Node(id="join", run=recording(order), depends_on=["a", "b"]))

    await Scheduler().run(dag, ExecutionContext(run_id="t3"))

    assert order[-1] == "join"
    assert set(order[:2]) == {"a", "b"}


@pytest.mark.asyncio
async def test_failed_node_blocks_dependents_but_not_independent_branches():
    order = []
    dag = DAG()
    dag.add_node(Node(id="fails", run=fail()))
    dag.add_node(Node(id="blocked_child", run=recording(order), depends_on=["fails"]))
    dag.add_node(Node(id="independent", run=recording(order)))

    result = await Scheduler().run(dag, ExecutionContext(run_id="t4"))

    assert dag.nodes["fails"].status == NodeStatus.FAILED
    assert dag.nodes["blocked_child"].status == NodeStatus.BLOCKED
    assert dag.nodes["independent"].status == NodeStatus.SUCCEEDED
    assert "blocked_child" not in order
    assert "independent" in order
    assert not result.succeeded


@pytest.mark.asyncio
async def test_entry_gate_blocks_node_without_running_it():
    ran = []

    def deny_gate(node, context):
        return GateResult(passed=False, reason="policy violation")

    dag = DAG()
    dag.add_node(Node(id="gated", run=recording(ran), entry_gate=deny_gate))

    await Scheduler().run(dag, ExecutionContext(run_id="t5"))

    assert dag.nodes["gated"].status == NodeStatus.BLOCKED
    assert ran == []


@pytest.mark.asyncio
async def test_exit_gate_failure_marks_node_failed_and_triggers_rollback():
    rolled_back = []

    def deny_exit(node, context):
        return GateResult(passed=False, reason="output invalid")

    dag = DAG()
    dag.add_node(Node(
        id="n",
        run=ok(output="stuff"),
        exit_gate=deny_exit,
        rollback=lambda node, context: rolled_back.append(node.id),
    ))

    context = ExecutionContext(run_id="t6")
    await Scheduler().run(dag, context)

    assert dag.nodes["n"].status == NodeStatus.FAILED
    assert context.get_output("n") is None
    assert rolled_back == ["n"]


@pytest.mark.asyncio
async def test_context_outputs_and_lineage_are_populated():
    dag = DAG()
    dag.add_node(Node(id="n", run=ok(output={"x": 1})))

    context = ExecutionContext(run_id="t7")
    context.record_decision(stage="test", summary="did a thing", rationale="because")
    await Scheduler().run(dag, context)

    assert context.get_output("n") == {"x": 1}
    assert len(context.lineage) == 1
    assert context.lineage[0].summary == "did a thing"


def test_duplicate_node_id_rejected():
    dag = DAG()
    dag.add_node(Node(id="a", run=ok()))
    with pytest.raises(ValueError):
        dag.add_node(Node(id="a", run=ok()))


def test_cycle_detection():
    dag = DAG()
    dag.add_node(Node(id="a", run=ok(), depends_on=["b"]))
    dag.add_node(Node(id="b", run=ok(), depends_on=["a"]))
    with pytest.raises(ValueError, match="Cycle"):
        dag.validate()


@pytest.mark.asyncio
async def test_run_result_status_summary():
    dag = DAG()
    dag.add_node(Node(id="a", run=ok()))
    dag.add_node(Node(id="b", run=fail()))

    result = await Scheduler().run(dag, ExecutionContext(run_id="t8"))

    assert result.status_summary() == {"a": "succeeded", "b": "failed"}
    assert not result.succeeded
