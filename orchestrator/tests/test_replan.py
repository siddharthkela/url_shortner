import pytest

from orchestrator.engine.context import ExecutionContext
from orchestrator.engine.dag import DAG, Node, NodeResult, NodeStatus, Scheduler
from orchestrator.engine.replan import insert_nodes, redirect_existing_node


def ok(output=None):
    async def _run(node, context):
        return NodeResult(success=True, output=output)

    return _run


@pytest.mark.asyncio
async def test_replanning_node_inserts_new_work_that_runs_in_a_later_tick():
    async def design(node, context):
        new_node = Node(id="extra_task", run=ok(), depends_on=[])
        insert_nodes(context, [new_node], reason="discovered additional scope during design")
        return NodeResult(success=True)

    dag = DAG()
    dag.add_node(Node(id="design", run=design))
    assert "extra_task" not in dag.nodes  # doesn't exist until the run inserts it

    result = await Scheduler().run(dag, ExecutionContext(run_id="rp1"))

    assert dag.nodes["design"].status == NodeStatus.SUCCEEDED
    assert "extra_task" in dag.nodes
    assert dag.nodes["extra_task"].status == NodeStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_already_completed_node_outputs_untouched_by_later_replan():
    async def design(node, context):
        insert_nodes(context, [Node(id="extra", run=ok(output="extra-out"))], reason="scope grew")
        return NodeResult(success=True, output="design-out")

    dag = DAG()
    dag.add_node(Node(id="design", run=design))

    context = ExecutionContext(run_id="rp2")
    await Scheduler().run(dag, context)

    assert context.get_output("design") == "design-out"
    assert context.get_output("extra") == "extra-out"


@pytest.mark.asyncio
async def test_redirect_existing_node_makes_release_wait_on_new_work():
    async def design(node, context):
        extra = Node(id="extra", run=ok())
        insert_nodes(context, [extra], reason="scope grew")
        redirect_existing_node(context, existing_node_id="release", extra_dependency_id="extra", reason="release must wait on the new task too")
        return NodeResult(success=True)

    dag = DAG()
    dag.add_node(Node(id="design", run=design))
    dag.add_node(Node(id="release", run=ok(), depends_on=["design"]))

    await Scheduler().run(dag, ExecutionContext(run_id="rp3"))

    # release originally only depended on "design"; the redirect added "extra" too.
    assert dag.nodes["release"].depends_on == ["design", "extra"]
    # the scheduler only runs release once every dependency has SUCCEEDED, so
    # release reaching SUCCEEDED here structurally proves it waited on "extra".
    assert dag.nodes["extra"].status == NodeStatus.SUCCEEDED
    assert dag.nodes["release"].status == NodeStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_replan_reason_recorded_in_decision_lineage():
    async def design(node, context):
        insert_nodes(context, [Node(id="extra", run=ok())], reason="clarified requirement expanded scope")
        return NodeResult(success=True)

    dag = DAG()
    dag.add_node(Node(id="design", run=design))

    context = ExecutionContext(run_id="rp4")
    await Scheduler().run(dag, context)

    replan_records = [d for d in context.lineage if d.stage == "engine"]
    assert len(replan_records) == 1
    assert "clarified requirement expanded scope" == replan_records[0].rationale
    assert "extra" in replan_records[0].summary


@pytest.mark.asyncio
async def test_replan_introducing_a_cycle_fails_the_originating_node_without_crashing_run():
    async def design(node, context):
        # extra depends on design, and this redirects design to depend on extra -> cycle
        insert_nodes(context, [Node(id="extra", run=ok(), depends_on=["design"])], reason="oops")
        redirect_existing_node(context, existing_node_id="design", extra_dependency_id="extra", reason="oops cycle")
        return NodeResult(success=True)

    dag = DAG()
    dag.add_node(Node(id="design", run=design))

    result = await Scheduler().run(dag, ExecutionContext(run_id="rp5"))

    assert dag.nodes["design"].status == NodeStatus.FAILED
    assert "Cycle" in dag.nodes["design"].result.error
    assert not result.succeeded


def test_replan_outside_a_running_engine_raises():
    context = ExecutionContext(run_id="rp6")
    with pytest.raises(RuntimeError, match="replan_hook"):
        insert_nodes(context, [Node(id="x", run=ok())], reason="no engine running")
