import pytest

from orchestrator.engine.approval import ApprovalManager, AutonomyLevel, auto_approve, auto_deny
from orchestrator.engine.context import ExecutionContext
from orchestrator.engine.dag import DAG, Node, NodeResult, NodeStatus, Scheduler


def ok():
    async def _run(node, context):
        return NodeResult(success=True)

    return _run


@pytest.mark.asyncio
async def test_assisted_only_pauses_flagged_nodes():
    manager = ApprovalManager(autonomy=AutonomyLevel.ASSISTED, decision_fn=auto_deny)

    dag = DAG()
    dag.add_node(Node(id="plain", run=ok()))
    dag.add_node(Node(id="gated", run=ok(), requires_approval=True))

    await Scheduler(approval_manager=manager).run(dag, ExecutionContext(run_id="a1"))

    assert dag.nodes["plain"].status == NodeStatus.SUCCEEDED
    assert dag.nodes["gated"].status == NodeStatus.BLOCKED


@pytest.mark.asyncio
async def test_dry_run_pauses_every_node():
    manager = ApprovalManager(autonomy=AutonomyLevel.DRY_RUN, decision_fn=auto_deny)

    dag = DAG()
    dag.add_node(Node(id="plain", run=ok()))

    await Scheduler(approval_manager=manager).run(dag, ExecutionContext(run_id="a2"))

    assert dag.nodes["plain"].status == NodeStatus.BLOCKED


@pytest.mark.asyncio
async def test_autonomous_never_pauses_even_flagged_nodes():
    manager = ApprovalManager(autonomy=AutonomyLevel.AUTONOMOUS, decision_fn=auto_deny)

    dag = DAG()
    dag.add_node(Node(id="gated", run=ok(), requires_approval=True))

    await Scheduler(approval_manager=manager).run(dag, ExecutionContext(run_id="a3"))

    assert dag.nodes["gated"].status == NodeStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_approval_decision_recorded_in_lineage():
    manager = ApprovalManager(autonomy=AutonomyLevel.ASSISTED, decision_fn=auto_approve)

    dag = DAG()
    dag.add_node(Node(id="gated", run=ok(), requires_approval=True))

    context = ExecutionContext(run_id="a4")
    await Scheduler(approval_manager=manager).run(dag, context)

    approval_records = [d for d in context.lineage if d.stage == "approval"]
    assert len(approval_records) == 1
    assert "Approved" in approval_records[0].summary
    assert "gated" in approval_records[0].summary


@pytest.mark.asyncio
async def test_approval_denied_blocks_dependents():
    manager = ApprovalManager(autonomy=AutonomyLevel.ASSISTED, decision_fn=auto_deny)

    dag = DAG()
    dag.add_node(Node(id="gated", run=ok(), requires_approval=True))
    dag.add_node(Node(id="child", run=ok(), depends_on=["gated"]))

    await Scheduler(approval_manager=manager).run(dag, ExecutionContext(run_id="a5"))

    assert dag.nodes["gated"].status == NodeStatus.BLOCKED
    assert dag.nodes["child"].status == NodeStatus.BLOCKED
