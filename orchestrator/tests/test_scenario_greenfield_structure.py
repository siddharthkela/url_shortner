import pytest

import orchestrator.scenarios.greenfield_qr_code as greenfield
from orchestrator.agents.base import AgentResult, AgentTask
from orchestrator.engine.approval import ApprovalManager, AutonomyLevel, auto_approve
from orchestrator.engine.context import ExecutionContext
from orchestrator.engine.dag import NodeStatus, Scheduler


class _StubAgent:
    """Returns success for every stage without touching real files. The
    implementation/test stages return the same output *shape* the real
    handlers produce (files_written) since the run_tests policy gate reads
    it — this caught a real bug on first run: a stub returning an empty
    shape correctly tripped the "new endpoint needs tests" policy rule.
    """

    async def run(self, task: AgentTask) -> AgentResult:
        if task.stage == "implementation":
            return AgentResult(success=True, output={"files_written": ["fake/Impl.java"]})
        if task.stage == "test":
            return AgentResult(success=True, output={"files_written": ["fake/ImplTest.java"]})
        return AgentResult(success=True, output={"stage": task.stage})


@pytest.fixture(autouse=True)
def _fake_git_and_maven(monkeypatch):
    """The DAG shape/scheduling is what this test verifies — not real git or
    a real Maven build — so replace those two integration points with fast
    no-ops scoped to this test module.
    """
    class _FakeCompletedProcess:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(greenfield, "run_maven_test", lambda repo_root: (True, "BUILD SUCCESS"))
    monkeypatch.setattr(greenfield, "commit_all", lambda repo_root, message: _FakeCompletedProcess())
    monkeypatch.setattr(greenfield, "run_git", lambda repo_root, *args: _FakeCompletedProcess())


@pytest.mark.asyncio
async def test_greenfield_dag_has_expected_non_linear_shape():
    dag = greenfield.build_dag(_StubAgent(), repo_root="/fake/repo")

    assert dag.nodes["intake_requirement"].depends_on == []
    assert dag.nodes["analyze_codebase"].depends_on == ["intake_requirement"]
    assert dag.nodes["design"].depends_on == ["analyze_codebase"]

    # implement_code, draft_tests, update_docs all fan out from design in parallel
    assert dag.nodes["implement_code"].depends_on == ["design"]
    assert dag.nodes["draft_tests"].depends_on == ["design"]
    assert dag.nodes["update_docs"].depends_on == ["design"]

    # run_tests is a synchronization join on the two parallel work nodes
    assert set(dag.nodes["run_tests"].depends_on) == {"implement_code", "draft_tests"}

    # release_readiness joins run_tests and update_docs, and is human-gated
    assert set(dag.nodes["release_readiness"].depends_on) == {"run_tests", "update_docs"}
    assert dag.nodes["release_readiness"].requires_approval is True

    assert dag.nodes["finalize"].depends_on == ["release_readiness"]


@pytest.mark.asyncio
async def test_greenfield_dag_runs_to_completion_with_auto_approval():
    dag = greenfield.build_dag(_StubAgent(), repo_root="/fake/repo")
    manager = ApprovalManager(autonomy=AutonomyLevel.ASSISTED, decision_fn=auto_approve)

    result = await Scheduler(approval_manager=manager).run(dag, ExecutionContext(run_id="greenfield-structure-test"))

    assert result.succeeded
    assert dag.nodes["finalize"].status == NodeStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_greenfield_dag_blocks_at_release_when_approval_denied():
    from orchestrator.engine.approval import auto_deny

    dag = greenfield.build_dag(_StubAgent(), repo_root="/fake/repo")
    manager = ApprovalManager(autonomy=AutonomyLevel.ASSISTED, decision_fn=auto_deny)

    result = await Scheduler(approval_manager=manager).run(dag, ExecutionContext(run_id="greenfield-denied-test"))

    assert not result.succeeded
    assert dag.nodes["release_readiness"].status == NodeStatus.BLOCKED
    assert dag.nodes["finalize"].status == NodeStatus.BLOCKED
    # everything upstream of the approval gate still completed
    assert dag.nodes["implement_code"].status == NodeStatus.SUCCEEDED
    assert dag.nodes["draft_tests"].status == NodeStatus.SUCCEEDED
