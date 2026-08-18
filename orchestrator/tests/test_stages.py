import pytest

from orchestrator.agents.base import AgentResult, AgentTask
from orchestrator.agents.deterministic import DeterministicAgent
from orchestrator.engine.context import ExecutionContext
from orchestrator.engine.dag import DAG, NodeStatus, Scheduler
from orchestrator.stages import (
    build_agent_node,
    build_design_node,
    build_implementation_node,
    build_requirements_node,
)


class _RecordingAgent:
    def __init__(self, result: AgentResult):
        self.result = result
        self.received_tasks = []

    async def run(self, task: AgentTask) -> AgentResult:
        self.received_tasks.append(task)
        return self.result


@pytest.mark.asyncio
async def test_build_agent_node_passes_payload_and_stage_to_agent():
    agent = _RecordingAgent(AgentResult(success=True, output={"x": 1}))
    node = build_agent_node(
        node_id="n",
        stage="design",
        agent=agent,
        payload_fn=lambda context: {"requirement": "add rate limiting"},
    )

    await Scheduler().run(_single_node_dag(node), ExecutionContext(run_id="s1"))

    assert len(agent.received_tasks) == 1
    assert agent.received_tasks[0].stage == "design"
    assert agent.received_tasks[0].payload == {"requirement": "add rate limiting"}


@pytest.mark.asyncio
async def test_build_agent_node_success_sets_output_and_records_decision():
    agent = _RecordingAgent(AgentResult(success=True, output={"approach": "token bucket"}, rationale="chosen for simplicity"))
    node = build_agent_node(
        node_id="design",
        stage="design",
        agent=agent,
        payload_fn=lambda context: {},
        decision_summary_fn=lambda output: f"Design: {output['approach']}",
    )

    context = ExecutionContext(run_id="s2")
    await Scheduler().run(_single_node_dag(node), context)

    assert context.get_output("design") == {"approach": "token bucket"}
    assert len(context.lineage) == 1
    assert context.lineage[0].stage == "design"
    assert context.lineage[0].summary == "Design: token bucket"
    assert context.lineage[0].rationale == "chosen for simplicity"


@pytest.mark.asyncio
async def test_build_agent_node_failure_does_not_record_decision():
    agent = _RecordingAgent(AgentResult(success=False, error="agent blew up"))
    node = build_agent_node(node_id="n", stage="design", agent=agent, payload_fn=lambda context: {})

    context = ExecutionContext(run_id="s3")
    await Scheduler().run(_single_node_dag(node), context)

    assert node.status == NodeStatus.FAILED
    assert context.lineage == []


@pytest.mark.asyncio
async def test_default_decision_summary_used_when_none_provided():
    agent = _RecordingAgent(AgentResult(success=True, output={}))
    node = build_agent_node(node_id="n", stage="test", agent=agent, payload_fn=lambda context: {})

    context = ExecutionContext(run_id="s4")
    await Scheduler().run(_single_node_dag(node), context)

    assert context.lineage[0].summary == "test completed"


@pytest.mark.asyncio
async def test_payload_fn_can_read_upstream_context_outputs():
    agent = _RecordingAgent(AgentResult(success=True, output={}))
    node = build_agent_node(
        node_id="n",
        stage="implementation",
        agent=agent,
        payload_fn=lambda context: {"design": context.get_output("design")},
        depends_on=["design"],
    )

    dag = DAG()
    async def design_run(node, context):
        from orchestrator.engine.dag import NodeResult
        return NodeResult(success=True, output={"approach": "token bucket"})

    from orchestrator.engine.dag import Node
    dag.add_node(Node(id="design", run=design_run))
    dag.add_node(node)

    await Scheduler().run(dag, ExecutionContext(run_id="s5"))

    assert agent.received_tasks[0].payload == {"design": {"approach": "token bucket"}}


@pytest.mark.asyncio
async def test_named_stage_builders_set_correct_stage_tag():
    agent = _RecordingAgent(AgentResult(success=True, output={}))

    req_node = build_requirements_node(node_id="a", agent=agent, payload_fn=lambda c: {})
    design_node = build_design_node(node_id="b", agent=agent, payload_fn=lambda c: {}, depends_on=["a"])
    impl_node = build_implementation_node(node_id="c", agent=agent, payload_fn=lambda c: {}, depends_on=["b"])

    dag = DAG()
    dag.add_node(req_node)
    dag.add_node(design_node)
    dag.add_node(impl_node)

    await Scheduler().run(dag, ExecutionContext(run_id="s6"))

    stages_called = [t.stage for t in agent.received_tasks]
    assert stages_called == ["requirements", "design", "implementation"]


@pytest.mark.asyncio
async def test_deterministic_agent_integrates_cleanly_with_stage_factory():
    async def design_handler(payload):
        return AgentResult(success=True, output={"approach": f"handle: {payload['requirement']}"})

    agent = DeterministicAgent(handlers={"design": design_handler})
    node = build_design_node(
        node_id="design",
        agent=agent,
        payload_fn=lambda context: {"requirement": "add QR codes"},
    )

    context = ExecutionContext(run_id="s7")
    await Scheduler().run(_single_node_dag(node), context)

    assert context.get_output("design") == {"approach": "handle: add QR codes"}


def _single_node_dag(node) -> DAG:
    dag = DAG()
    dag.add_node(node)
    return dag
