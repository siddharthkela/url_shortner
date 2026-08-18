import pytest

import orchestrator.scenarios.ambiguous_analytics as ambiguous
from orchestrator.agents.base import AgentResult, AgentTask
from orchestrator.engine.approval import ApprovalManager, AutonomyLevel, auto_approve, auto_deny
from orchestrator.engine.context import ExecutionContext
from orchestrator.engine.dag import NodeStatus, Scheduler
from orchestrator.engine.reliability import make_retrying_executor


class _StubAgentThatProposesTheDependency:
    """Mimics the real design_handler's first (wrong) idea, forcing a replan."""

    async def run(self, task: AgentTask) -> AgentResult:
        if task.stage == "design":
            return AgentResult(success=True, output={"approach": "charting lib", "introduces_new_dependency": True})
        if task.stage == "implementation":
            return AgentResult(success=True, output={"files_written": ["fake/Impl.java"]})
        if task.stage == "test":
            return AgentResult(success=True, output={"files_written": ["fake/ImplTest.java"]})
        return AgentResult(success=True, output={"stage": task.stage})


class _StubAgentWithNoConflict:
    """Mimics a design that never triggers the constraint — replan should not fire."""

    async def run(self, task: AgentTask) -> AgentResult:
        if task.stage == "design":
            return AgentResult(success=True, output={"approach": "plain fields", "introduces_new_dependency": False})
        if task.stage == "implementation":
            return AgentResult(success=True, output={"files_written": ["fake/Impl.java"]})
        if task.stage == "test":
            return AgentResult(success=True, output={"files_written": ["fake/ImplTest.java"]})
        return AgentResult(success=True, output={"stage": task.stage})


@pytest.fixture(autouse=True)
def _fake_git_and_maven(monkeypatch):
    class _FakeCompletedProcess:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(ambiguous, "run_maven_test", lambda repo_root: (True, "BUILD SUCCESS"))
    monkeypatch.setattr(ambiguous, "commit_all", lambda repo_root, message: _FakeCompletedProcess())
    monkeypatch.setattr(ambiguous, "run_git", lambda repo_root, *args: _FakeCompletedProcess())


async def _instant_sleep(_seconds):
    return None


@pytest.mark.asyncio
async def test_replan_fires_and_redirects_downstream_nodes_when_constraint_violated():
    dag = ambiguous.build_dag(_StubAgentThatProposesTheDependency(), repo_root="/fake/repo")
    manager = ApprovalManager(autonomy=AutonomyLevel.ASSISTED, decision_fn=auto_approve)

    result = await Scheduler(
        approval_manager=manager, retry_executor=make_retrying_executor(sleep_fn=_instant_sleep),
    ).run(dag, ExecutionContext(run_id="ambiguous-replan-test"))

    assert result.succeeded
    assert "redesign" in dag.nodes
    assert dag.nodes["redesign"].status == NodeStatus.SUCCEEDED
    # implement_code/draft_tests/update_docs were redirected onto redesign in addition
    # to their original dependency on check_constraints
    assert set(dag.nodes["implement_code"].depends_on) == {"check_constraints", "redesign"}
    assert set(dag.nodes["draft_tests"].depends_on) == {"check_constraints", "redesign"}
    assert set(dag.nodes["update_docs"].depends_on) == {"check_constraints", "redesign"}


@pytest.mark.asyncio
async def test_no_replan_when_design_has_no_conflict():
    dag = ambiguous.build_dag(_StubAgentWithNoConflict(), repo_root="/fake/repo")
    manager = ApprovalManager(autonomy=AutonomyLevel.ASSISTED, decision_fn=auto_approve)

    result = await Scheduler(
        approval_manager=manager, retry_executor=make_retrying_executor(sleep_fn=_instant_sleep),
    ).run(dag, ExecutionContext(run_id="ambiguous-no-replan-test"))

    assert result.succeeded
    assert "redesign" not in dag.nodes
    assert dag.nodes["implement_code"].depends_on == ["check_constraints"]


@pytest.mark.asyncio
async def test_replan_reason_and_decisions_captured_in_lineage():
    dag = ambiguous.build_dag(_StubAgentThatProposesTheDependency(), repo_root="/fake/repo")
    manager = ApprovalManager(autonomy=AutonomyLevel.ASSISTED, decision_fn=auto_approve)
    context = ExecutionContext(run_id="ambiguous-lineage-test")

    await Scheduler(
        approval_manager=manager, retry_executor=make_retrying_executor(sleep_fn=_instant_sleep),
    ).run(dag, context)

    replan_records = [d for d in context.lineage if d.stage == "engine"]
    # one insert_nodes + three redirect_existing_node calls = 4 replan decisions
    assert len(replan_records) == 4
    assert any("dependency conflict" in r.rationale or "conflict" in r.rationale for r in replan_records)


@pytest.mark.asyncio
async def test_ambiguous_dag_blocks_at_release_when_approval_denied():
    dag = ambiguous.build_dag(_StubAgentWithNoConflict(), repo_root="/fake/repo")
    manager = ApprovalManager(autonomy=AutonomyLevel.ASSISTED, decision_fn=auto_deny)

    result = await Scheduler(
        approval_manager=manager, retry_executor=make_retrying_executor(sleep_fn=_instant_sleep),
    ).run(dag, ExecutionContext(run_id="ambiguous-denied-test"))

    assert not result.succeeded
    assert dag.nodes["release_readiness"].status == NodeStatus.BLOCKED
    assert dag.nodes["finalize"].status == NodeStatus.BLOCKED


def test_apply_functions_are_idempotent():
    from orchestrator.scenarios.ambiguous_analytics import (
        _apply_controller_test_changes,
        _apply_mapper_changes,
        _apply_readme_changes,
        _apply_service_test_changes,
    )

    mapper = (
        "import com.urlshortener.entity.ShortUrlEntity;\n\n"
        "    public static AnalyticsResponse toAnalyticsResponse(ShortUrlEntity entity) {\n"
        "        return new AnalyticsResponse(\n"
        "                entity.getShortCode(),\n"
        "                entity.getClickCount(),\n"
        "                entity.getFirstAccessedAt(),\n"
        "                entity.getLastAccessedAt()\n"
        "        );\n"
        "    }"
    )
    m_once = _apply_mapper_changes(mapper)
    m_twice = _apply_mapper_changes(m_once)
    assert m_once == m_twice
    assert m_twice.count("daysActive") >= 1
    assert m_twice.count("import java.time.Duration;") == 1

    controller_test = 'AnalyticsResponse response = new AnalyticsResponse("abc123", 5, Instant.now(), Instant.now());'
    c_once = _apply_controller_test_changes(controller_test)
    c_twice = _apply_controller_test_changes(c_once)
    assert c_once == c_twice
    assert "3, 1.67" in c_once

    service_test = (
        "        assertThat(response.firstAccessedAt()).isEqualTo(first);\n"
        "        assertThat(response.lastAccessedAt()).isEqualTo(last);\n"
        "    }"
    )
    s_once = _apply_service_test_changes(service_test)
    s_twice = _apply_service_test_changes(s_once)
    assert s_once == s_twice
    assert s_twice.count("daysActive()") == 1

    readme = "| `GET` | `/api/v1/urls/{shortCode}/analytics` | Click count, first/last accessed timestamps. |\n"
    r_once = _apply_readme_changes(readme)
    r_twice = _apply_readme_changes(r_once)
    assert r_once == r_twice
