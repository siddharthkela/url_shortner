import pytest

import orchestrator.scenarios.brownfield_rate_limit as brownfield
from orchestrator.agents.base import AgentResult, AgentTask
from orchestrator.engine.approval import ApprovalManager, AutonomyLevel, auto_approve, auto_deny
from orchestrator.engine.context import ExecutionContext
from orchestrator.engine.dag import NodeStatus, Scheduler


class _StubAgent:
    async def run(self, task: AgentTask) -> AgentResult:
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

    monkeypatch.setattr(brownfield, "run_maven_test", lambda repo_root: (True, "BUILD SUCCESS"))
    monkeypatch.setattr(brownfield, "commit_all", lambda repo_root, message: _FakeCompletedProcess())
    monkeypatch.setattr(brownfield, "run_git", lambda repo_root, *args: _FakeCompletedProcess())


@pytest.mark.asyncio
async def test_brownfield_dag_matches_the_planned_non_linear_shape():
    dag = brownfield.build_dag(_StubAgent(), repo_root="/fake/repo")

    assert dag.nodes["analyze_codebase"].depends_on == ["intake_requirement"]
    assert dag.nodes["design"].depends_on == ["analyze_codebase"]
    assert dag.nodes["implement_code"].depends_on == ["design"]
    assert dag.nodes["draft_tests"].depends_on == ["design"]
    assert dag.nodes["update_docs"].depends_on == ["design"]
    assert set(dag.nodes["run_tests"].depends_on) == {"implement_code", "draft_tests"}
    # policy_check is its own node here (unlike greenfield's inline exit gate)
    assert dag.nodes["policy_check"].depends_on == ["run_tests"]
    assert set(dag.nodes["release_readiness"].depends_on) == {"policy_check", "update_docs"}
    assert dag.nodes["release_readiness"].requires_approval is True
    assert dag.nodes["finalize"].depends_on == ["release_readiness"]


@pytest.mark.asyncio
async def test_run_tests_has_a_bounded_retry_policy():
    dag = brownfield.build_dag(_StubAgent(), repo_root="/fake/repo")
    assert dag.nodes["run_tests"].retry_policy.max_attempts == 3


@pytest.mark.asyncio
async def test_injected_transient_failure_actually_recovers_via_retry():
    """The scheduler needs a real retry_executor wired in for retry_policy to
    do anything — Scheduler()'s bare default just runs once. This proves the
    deliberate first-attempt failure is followed by a real second attempt
    that succeeds, not just that the DAG *declares* a retry policy.
    """
    from orchestrator.engine.reliability import make_retrying_executor

    dag = brownfield.build_dag(_StubAgent(), repo_root="/fake/repo")
    manager = ApprovalManager(autonomy=AutonomyLevel.ASSISTED, decision_fn=auto_approve)

    async def _instant_sleep(_seconds):
        return None

    result = await Scheduler(
        approval_manager=manager,
        retry_executor=make_retrying_executor(sleep_fn=_instant_sleep),
    ).run(dag, ExecutionContext(run_id="brownfield-retry-test"))

    assert dag.nodes["run_tests"].status == NodeStatus.SUCCEEDED
    assert dag.nodes["run_tests"].attempts == 2  # failed once (injected), succeeded on retry
    assert result.succeeded


@pytest.mark.asyncio
async def test_brownfield_dag_blocks_at_release_when_approval_denied():
    from orchestrator.engine.reliability import make_retrying_executor

    dag = brownfield.build_dag(_StubAgent(), repo_root="/fake/repo")
    manager = ApprovalManager(autonomy=AutonomyLevel.ASSISTED, decision_fn=auto_deny)

    async def _instant_sleep(_seconds):
        return None

    result = await Scheduler(
        approval_manager=manager,
        retry_executor=make_retrying_executor(sleep_fn=_instant_sleep),
    ).run(dag, ExecutionContext(run_id="brownfield-denied-test"))

    assert not result.succeeded
    assert dag.nodes["release_readiness"].status == NodeStatus.BLOCKED
    assert dag.nodes["finalize"].status == NodeStatus.BLOCKED
    assert dag.nodes["policy_check"].status == NodeStatus.SUCCEEDED


def test_apply_functions_are_idempotent():
    from orchestrator.scenarios.brownfield_rate_limit import (
        _apply_controller_changes,
        _apply_handler_changes,
        _apply_yml_changes,
    )

    controller = (
        "import com.urlshortener.dto.UrlResponse;\n"
        "import com.urlshortener.service.UrlService;\n"
        "import jakarta.validation.Valid;\n\n"
        "    private final UrlService urlService;\n\n"
        "    public UrlController(UrlService urlService) {\n"
        "        this.urlService = urlService;\n"
        "    }\n\n"
        "    public ResponseEntity<UrlResponse> createShortUrl(@Valid @RequestBody CreateUrlRequest request,\n"
        "                                                        @RequestHeader(value = \"Idempotency-Key\", required = false) String idempotencyKey) {\n"
        "        UrlResponse response = urlService.createShortUrl(request, idempotencyKey);\n"
    )
    once = _apply_controller_changes(controller)
    twice = _apply_controller_changes(once)
    assert once == twice
    assert twice.count("rateLimiter.tryAcquire") == 1
    assert twice.count("import com.urlshortener.service.RateLimiter;") == 1

    handler = (
        "    @ExceptionHandler(TooManyActiveUrlsException.class)\n"
        "    public ResponseEntity<ErrorResponse> handleTooManyActiveUrls(TooManyActiveUrlsException ex, HttpServletRequest request) {\n"
        "        return build(HttpStatus.TOO_MANY_REQUESTS, ex.getMessage(), request);\n"
        "    }\n"
    )
    h_once = _apply_handler_changes(handler)
    h_twice = _apply_handler_changes(h_once)
    assert h_once == h_twice
    assert h_twice.count("RateLimitExceededException") == 2  # annotation + method name reference

    yml = "app:\n  max-active-urls: 1000000\n  base-url: http://localhost:8080\n"
    y_once = _apply_yml_changes(yml)
    y_twice = _apply_yml_changes(y_once)
    assert y_once == y_twice
    assert y_twice.count("rate-limit") == 1
