import pytest

from orchestrator.engine.context import ExecutionContext
from orchestrator.engine.dag import DAG, Node, NodeResult, NodeStatus, Scheduler
from orchestrator.engine.gates import all_of, policy_exit_gate, require_output_keys, require_outputs
from orchestrator.engine.policy import PolicyContext, PolicyEngine


def ok(output=None):
    async def _run(node, context):
        return NodeResult(success=True, output=output)

    return _run


@pytest.mark.asyncio
async def test_require_outputs_blocks_when_upstream_output_missing():
    dag = DAG()
    dag.add_node(Node(id="a", run=ok(output=None)))  # succeeds but produces no output
    dag.add_node(Node(id="b", run=ok(), depends_on=["a"], entry_gate=require_outputs("a")))

    await Scheduler().run(dag, ExecutionContext(run_id="g1"))

    assert dag.nodes["b"].status == NodeStatus.BLOCKED


@pytest.mark.asyncio
async def test_require_outputs_passes_when_upstream_output_present():
    dag = DAG()
    dag.add_node(Node(id="a", run=ok(output={"x": 1})))
    dag.add_node(Node(id="b", run=ok(), depends_on=["a"], entry_gate=require_outputs("a")))

    await Scheduler().run(dag, ExecutionContext(run_id="g2"))

    assert dag.nodes["b"].status == NodeStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_require_output_keys_fails_gate_on_missing_key():
    dag = DAG()
    dag.add_node(Node(id="n", run=ok(output={"foo": 1}), exit_gate=require_output_keys("foo", "bar")))

    await Scheduler().run(dag, ExecutionContext(run_id="g3"))

    assert dag.nodes["n"].status == NodeStatus.FAILED


@pytest.mark.asyncio
async def test_all_of_short_circuits_on_first_failure():
    dag = DAG()
    dag.add_node(Node(
        id="n",
        run=ok(output=None),
        entry_gate=all_of(require_outputs("nonexistent")),
    ))

    await Scheduler().run(dag, ExecutionContext(run_id="g4"))

    assert dag.nodes["n"].status == NodeStatus.BLOCKED


@pytest.mark.asyncio
async def test_policy_exit_gate_fails_run_on_critical_violation():
    engine = PolicyEngine.default()

    def build_ctx(node, context):
        return PolicyContext(new_endpoints=["GET /x"], test_files_created=[])

    dag = DAG()
    dag.add_node(Node(id="n", run=ok(output={}), exit_gate=policy_exit_gate(engine, build_ctx)))

    await Scheduler().run(dag, ExecutionContext(run_id="g5"))

    assert dag.nodes["n"].status == NodeStatus.FAILED
    assert "policy violation" in dag.nodes["n"].result.error


@pytest.mark.asyncio
async def test_policy_exit_gate_passes_with_no_violations():
    engine = PolicyEngine.default()

    def build_ctx(node, context):
        return PolicyContext()

    dag = DAG()
    dag.add_node(Node(id="n", run=ok(output={}), exit_gate=policy_exit_gate(engine, build_ctx)))

    await Scheduler().run(dag, ExecutionContext(run_id="g6"))

    assert dag.nodes["n"].status == NodeStatus.SUCCEEDED
