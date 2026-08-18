"""Brownfield scenario: "Add rate limiting to URL creation to prevent abuse."

Unlike the greenfield scenario, this one *changes existing behavior* on
files that already have real logic and real tests in them — the point is
to demonstrate real codebase-impact analysis (which files does this touch,
and why) rather than just adding new files in a vacuum. It also
deliberately injects one transient failure into run_tests to exercise the
retry mechanism for real, and models policy_check as its own DAG node
(rather than folded into an exit gate, as the greenfield scenario did) —
a different valid way to use the same primitives.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict

from orchestrator.agents.base import Agent, AgentResult
from orchestrator.agents.deterministic import DeterministicAgent
from orchestrator.engine.approval import ApprovalManager, AutonomyLevel, auto_approve, interactive_prompt
from orchestrator.engine.context import ExecutionContext
from orchestrator.engine.dag import DAG, Node, NodeResult, RunResult, Scheduler
from orchestrator.engine.policy import PolicyContext, PolicyEngine
from orchestrator.engine.reliability import RetryPolicy, make_retrying_executor
from orchestrator.observability.dashboard import write_dashboard
from orchestrator.observability.event_log import JsonlEventSink
from orchestrator.observability.metrics import compute_metrics
from orchestrator.scenarios.common import (
    FileChange,
    commit_all,
    create_and_checkout_branch,
    run_git,
    run_maven_test,
    write_files,
    write_run_summary,
)
from orchestrator.stages import (
    build_codebase_analysis_node,
    build_design_node,
    build_docs_node,
    build_implementation_node,
    build_release_node,
    build_requirements_node,
    build_test_node,
)

RAW_REQUIREMENT = "Add rate limiting to URL creation to prevent abuse."
BRANCH_NAME = "orchestrator-demo/brownfield-rate-limit"
IMPACTED_FILES = [
    "src/main/java/com/urlshortener/controller/UrlController.java",
    "src/main/resources/application.yml",
    "src/main/java/com/urlshortener/exception/GlobalExceptionHandler.java",
]


# --------------------------------------------------------------------------
# DAG structure — agent-agnostic, unit-tested with a stub agent.
# --------------------------------------------------------------------------

def build_dag(agent: Agent, repo_root: str) -> DAG:
    dag = DAG()

    dag.add_node(build_requirements_node(
        node_id="intake_requirement",
        agent=agent,
        payload_fn=lambda ctx: {"raw": RAW_REQUIREMENT},
        decision_summary_fn=lambda out: f"Normalized: {out.get('normalized_requirement', '(n/a)')}",
    ))

    dag.add_node(build_codebase_analysis_node(
        node_id="analyze_codebase",
        agent=agent,
        payload_fn=lambda ctx: {"repo_root": repo_root, "requirement": ctx.get_output("intake_requirement")},
        depends_on=["intake_requirement"],
        decision_summary_fn=lambda out: f"Impacted (existing): {out.get('impacted_files', [])}; new: {out.get('new_files', [])}",
    ))

    dag.add_node(build_design_node(
        node_id="design",
        agent=agent,
        payload_fn=lambda ctx: {"impact": ctx.get_output("analyze_codebase")},
        depends_on=["analyze_codebase"],
        decision_summary_fn=lambda out: f"Approach: {out.get('approach', '(n/a)')}",
    ))

    dag.add_node(build_implementation_node(
        node_id="implement_code",
        agent=agent,
        payload_fn=lambda ctx: {"design": ctx.get_output("design"), "repo_root": repo_root},
        depends_on=["design"],
        decision_summary_fn=lambda out: f"Wrote/modified: {out.get('files_written', [])}",
    ))

    dag.add_node(build_test_node(
        node_id="draft_tests",
        agent=agent,
        payload_fn=lambda ctx: {"design": ctx.get_output("design"), "repo_root": repo_root},
        depends_on=["design"],
        decision_summary_fn=lambda out: f"Wrote/modified: {out.get('files_written', [])}",
    ))

    dag.add_node(build_docs_node(
        node_id="update_docs",
        agent=agent,
        payload_fn=lambda ctx: {"design": ctx.get_output("design"), "repo_root": repo_root},
        depends_on=["design"],
        decision_summary_fn=lambda out: f"Wrote: {out.get('files_written', [])}",
    ))

    # Deliberately injected transient failure: attempt 1 always fails (a
    # simulated flaky test-runner infra issue), attempt 2 actually runs the
    # real ./mvnw test — exercising the retry mechanism for real rather than
    # just asserting it works in isolation.
    async def _run_tests(node: Node, context) -> NodeResult:
        if node.attempts == 1:
            return NodeResult(success=False, error="Simulated transient failure: test runner connection reset (injected for demonstration)")
        success, output = run_maven_test(repo_root)
        return NodeResult(success=success, output={"maven_output_tail": output[-2000:]}, error=None if success else "mvn test failed")

    dag.add_node(Node(
        id="run_tests",
        run=_run_tests,
        depends_on=["implement_code", "draft_tests"],
        retry_policy=RetryPolicy(max_attempts=3, initial_backoff=0.1),
    ))

    policy_engine = PolicyEngine.default()

    async def _policy_check(node: Node, context) -> NodeResult:
        impl_files = context.get_output("implement_code", {}).get("files_written", [])
        test_files = context.get_output("draft_tests", {}).get("files_written", [])
        file_contents = {}
        for rel_path in impl_files + test_files:
            full = Path(repo_root) / rel_path
            if full.exists():
                file_contents[rel_path] = full.read_text()
        ctx = PolicyContext(
            repo_root=repo_root,
            file_contents=file_contents,
            touches_files=impl_files + test_files,
            new_endpoints=[],  # this scenario changes existing endpoint behavior, doesn't add a new one
            test_files_created=test_files,
        )
        violations = policy_engine.evaluate(ctx)
        if PolicyEngine.has_critical(violations):
            messages = "; ".join(f"{v.rule}: {v.message}" for v in violations if v.severity == "CRITICAL")
            return NodeResult(success=False, error=f"policy violation(s): {messages}")
        return NodeResult(success=True, output={"violations": len(violations)})

    dag.add_node(Node(id="policy_check", run=_policy_check, depends_on=["run_tests"]))

    dag.add_node(build_release_node(
        node_id="release_readiness",
        agent=agent,
        payload_fn=lambda ctx: {"summary": "Rate limiting change ready for review"},
        depends_on=["policy_check", "update_docs"],
        requires_approval=True,
        decision_summary_fn=lambda out: f"Release status: {out.get('status', '(n/a)')}",
    ))

    async def _finalize(node: Node, context) -> NodeResult:
        commit_all(repo_root, "feat: add rate limiting to URL creation\n\nOrchestrator brownfield demo scenario.")
        push = run_git(repo_root, "push", "-u", "origin", BRANCH_NAME)
        return NodeResult(success=True, output={"pushed": push.returncode == 0, "push_stderr": push.stderr})

    dag.add_node(Node(id="finalize", run=_finalize, depends_on=["release_readiness"]))

    return dag


# --------------------------------------------------------------------------
# End-to-end runner (same pattern as the greenfield scenario).
# --------------------------------------------------------------------------

async def run(repo_root: str, auto_approve_all: bool = True) -> RunResult:
    staging_dir = Path(tempfile.mkdtemp(prefix="orchestrator_brownfield_"))
    events_path = staging_dir / "events.jsonl"

    create_and_checkout_branch(repo_root, BRANCH_NAME, base="main")

    agent = build_brownfield_agent(repo_root)
    dag = build_dag(agent, repo_root)
    sink = JsonlEventSink(path=events_path)
    approval = ApprovalManager(
        autonomy=AutonomyLevel.ASSISTED,
        decision_fn=auto_approve if auto_approve_all else interactive_prompt,
        event_sink=sink,
    )
    context = ExecutionContext(run_id="brownfield-rate-limit")
    scheduler = Scheduler(event_sink=sink, approval_manager=approval, retry_executor=make_retrying_executor(event_sink=sink))

    result = await scheduler.run(dag, context)

    metrics = compute_metrics(sink.events)
    write_dashboard(staging_dir / "dashboard.html", run_id=context.run_id, dag=dag, metrics=metrics)
    write_run_summary(
        staging_dir / "SUMMARY.md",
        scenario_name="Brownfield: rate limiting on URL creation",
        requirement=RAW_REQUIREMENT,
        branch_name=BRANCH_NAME,
        context=context,
        metrics=metrics,
        risks=[
            "The rate limiter is in-memory per-instance; since the app is explicitly "
            "single-instance (per the engineering plan), this is consistent with the "
            "existing architecture rather than a new limitation.",
            "Keying by remote IP address means users behind a shared NAT/proxy share a "
            "limit — acceptable for an abuse-prevention safety valve, not precise per-user "
            "throttling.",
            "State resets on restart along with everything else in this app (by design) — "
            "not a new durability concern specific to this feature.",
        ],
        assumptions=[
            "Rate limiting applies only to POST /api/v1/urls (creation) — the abuse vector "
            "named in the requirement — not to redirects/reads, which have no cost-of-abuse "
            "concern of the same kind.",
            "A fixed per-minute window is sufficient; the requirement didn't specify burst "
            "tolerance that would justify a more complex token-bucket-with-burst design.",
        ],
        limitations=[
            "No per-owner-token limiting (only per-IP), since ownerToken doesn't exist until "
            "after creation succeeds — a future iteration could add a second limiter keyed on "
            "ownerToken for update/delete abuse specifically.",
        ],
    )

    run_git(repo_root, "checkout", "main")
    dest = Path(repo_root) / "orchestrator" / "runs" / "brownfield"
    dest.mkdir(parents=True, exist_ok=True)
    for artifact in ("events.jsonl", "dashboard.html", "SUMMARY.md"):
        shutil.copy(staging_dir / artifact, dest / artifact)
    shutil.rmtree(staging_dir, ignore_errors=True)

    return result


# --------------------------------------------------------------------------
# Real scripted handlers.
# --------------------------------------------------------------------------

def build_brownfield_agent(repo_root: str) -> DeterministicAgent:
    async def requirements_handler(payload: Dict[str, Any]) -> AgentResult:
        return AgentResult(
            success=True,
            output={
                "normalized_requirement": "Reject URL-creation requests beyond a configurable "
                                           "per-client rate, returning 429, before they reach persistence.",
                "acceptance_criteria": [
                    "POST /api/v1/urls returns 429 once a client exceeds the configured rate",
                    "Existing create behavior (201/400/409/429-for-cap) is unchanged below the limit",
                    "The limit is configurable, not hardcoded, consistent with app.max-active-urls",
                ],
                "open_questions": [],
            },
            rationale="Clear abuse-prevention requirement with an obvious existing pattern "
                      "(app.max-active-urls' 429) to extend rather than reinvent.",
        )

    async def codebase_analysis_handler(payload: Dict[str, Any]) -> AgentResult:
        repo_root_str = payload.get("repo_root", repo_root)
        controller_path = Path(repo_root_str) / IMPACTED_FILES[0]
        handler_path = Path(repo_root_str) / IMPACTED_FILES[2]
        controller_text = controller_path.read_text()
        handler_text = handler_path.read_text()

        return AgentResult(
            success=True,
            output={
                "impacted_files": IMPACTED_FILES,
                "new_files": [
                    "src/main/java/com/urlshortener/service/RateLimiter.java",
                    "src/main/java/com/urlshortener/exception/RateLimitExceededException.java",
                ],
                "confirmed_create_endpoint_present": "createShortUrl" in controller_text,
                "confirmed_existing_429_pattern": "TOO_MANY_REQUESTS" in handler_text,
                "approach": "Extend GlobalExceptionHandler's existing 429 pattern (currently only "
                            "TooManyActiveUrlsException) with a second, distinct exception rather "
                            "than overloading the existing one's meaning.",
            },
            rationale="Actually read UrlController.java and GlobalExceptionHandler.java to confirm "
                      "the create endpoint and the existing 429-mapping pattern exist before "
                      "designing around them, rather than assuming.",
        )

    async def design_handler(payload: Dict[str, Any]) -> AgentResult:
        return AgentResult(
            success=True,
            output={
                "approach": "New RateLimiter @Component: fixed per-minute window, ConcurrentHashMap"
                            "<clientKey, Window>, no external dependency (no Redis — consistent "
                            "with the whole app's no-external-infra design). Checked in "
                            "UrlController.createShortUrl before delegating to UrlService.",
                "config": "app.rate-limit.enabled (bool), app.rate-limit.requests-per-minute (int)",
                "new_exception": "RateLimitExceededException -> 429, mapped alongside the existing "
                                  "TooManyActiveUrlsException -> 429 handler, kept as a distinct "
                                  "exception type since they represent different concerns despite "
                                  "sharing a status code.",
            },
            rationale="In-memory + no new dependency matches this app's established single-instance, "
                      "no-external-infra architecture (see the original engineering plan's rationale "
                      "for dropping Redis) rather than introducing a new pattern.",
        )

    async def implementation_handler(payload: Dict[str, Any]) -> AgentResult:
        changes = [
            FileChange("src/main/java/com/urlshortener/exception/RateLimitExceededException.java", _RATE_LIMIT_EXCEPTION_JAVA),
            FileChange("src/main/java/com/urlshortener/service/RateLimiter.java", _RATE_LIMITER_JAVA),
        ]

        controller_path = Path(repo_root) / "src/main/java/com/urlshortener/controller/UrlController.java"
        changes.append(FileChange(
            "src/main/java/com/urlshortener/controller/UrlController.java",
            _apply_controller_changes(controller_path.read_text()),
        ))

        handler_path = Path(repo_root) / "src/main/java/com/urlshortener/exception/GlobalExceptionHandler.java"
        changes.append(FileChange(
            "src/main/java/com/urlshortener/exception/GlobalExceptionHandler.java",
            _apply_handler_changes(handler_path.read_text()),
        ))

        yml_path = Path(repo_root) / "src/main/resources/application.yml"
        changes.append(FileChange(
            "src/main/resources/application.yml",
            _apply_yml_changes(yml_path.read_text()),
        ))

        written = write_files(repo_root, changes)
        return AgentResult(success=True, output={"files_written": written})

    async def test_handler(payload: Dict[str, Any]) -> AgentResult:
        changes = [
            FileChange("src/test/java/com/urlshortener/service/RateLimiterTest.java", _RATE_LIMITER_TEST_JAVA),
        ]
        controller_test_path = Path(repo_root) / "src/test/java/com/urlshortener/controller/UrlControllerTest.java"
        changes.append(FileChange(
            "src/test/java/com/urlshortener/controller/UrlControllerTest.java",
            _apply_controller_test_changes(controller_test_path.read_text()),
        ))
        written = write_files(repo_root, changes)
        return AgentResult(success=True, output={"files_written": written})

    async def docs_handler(payload: Dict[str, Any]) -> AgentResult:
        readme_path = Path(repo_root) / "README.md"
        written = write_files(repo_root, [
            FileChange("README.md", _apply_readme_changes(readme_path.read_text())),
        ])
        return AgentResult(success=True, output={"files_written": written})

    async def release_handler(payload: Dict[str, Any]) -> AgentResult:
        return AgentResult(success=True, output={"status": "ready", "summary": payload.get("summary", "")})

    return DeterministicAgent(handlers={
        "requirements": requirements_handler,
        "codebase_analysis": codebase_analysis_handler,
        "design": design_handler,
        "implementation": implementation_handler,
        "test": test_handler,
        "docs": docs_handler,
        "release": release_handler,
    })


# --------------------------------------------------------------------------
# Java/text templates and precise, idempotent insertions into existing files.
# --------------------------------------------------------------------------

_RATE_LIMIT_EXCEPTION_JAVA = """package com.urlshortener.exception;

public class RateLimitExceededException extends RuntimeException {
    public RateLimitExceededException(String message) {
        super(message);
    }
}
"""

_RATE_LIMITER_JAVA = """package com.urlshortener.service;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.time.Instant;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * Fixed per-minute window, keyed per client. In-memory only, consistent with
 * this app's single-instance, no-external-infra architecture (see the
 * engineering plan's rationale for dropping Redis) — a distributed rate
 * limiter is out of scope for the same reason a shared cache was ruled out.
 */
@Component
public class RateLimiter {

    private final int requestsPerMinute;
    private final boolean enabled;
    private final ConcurrentHashMap<String, Window> windows = new ConcurrentHashMap<>();

    public RateLimiter(@Value("${app.rate-limit.requests-per-minute}") int requestsPerMinute,
                        @Value("${app.rate-limit.enabled}") boolean enabled) {
        this.requestsPerMinute = requestsPerMinute;
        this.enabled = enabled;
    }

    public boolean tryAcquire(String clientKey) {
        if (!enabled) {
            return true;
        }
        long currentMinute = Instant.now().getEpochSecond() / 60;
        Window window = windows.compute(clientKey, (key, existing) ->
                (existing == null || existing.minute != currentMinute) ? new Window(currentMinute) : existing);
        return window.count.incrementAndGet() <= requestsPerMinute;
    }

    private static final class Window {
        final long minute;
        final AtomicInteger count = new AtomicInteger(0);

        Window(long minute) {
            this.minute = minute;
        }
    }
}
"""

_RATE_LIMITER_TEST_JAVA = """package com.urlshortener.service;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class RateLimiterTest {

    @Test
    void allowsRequestsUpToTheLimit() {
        RateLimiter limiter = new RateLimiter(3, true);

        assertThat(limiter.tryAcquire("client-a")).isTrue();
        assertThat(limiter.tryAcquire("client-a")).isTrue();
        assertThat(limiter.tryAcquire("client-a")).isTrue();
    }

    @Test
    void rejectsRequestsBeyondTheLimit() {
        RateLimiter limiter = new RateLimiter(2, true);

        assertThat(limiter.tryAcquire("client-b")).isTrue();
        assertThat(limiter.tryAcquire("client-b")).isTrue();
        assertThat(limiter.tryAcquire("client-b")).isFalse();
    }

    @Test
    void tracksDifferentClientsIndependently() {
        RateLimiter limiter = new RateLimiter(1, true);

        assertThat(limiter.tryAcquire("client-c")).isTrue();
        assertThat(limiter.tryAcquire("client-d")).isTrue();
    }

    @Test
    void allowsUnlimitedRequestsWhenDisabled() {
        RateLimiter limiter = new RateLimiter(1, false);

        assertThat(limiter.tryAcquire("client-e")).isTrue();
        assertThat(limiter.tryAcquire("client-e")).isTrue();
        assertThat(limiter.tryAcquire("client-e")).isTrue();
    }
}
"""


def _apply_controller_changes(original: str) -> str:
    if "RateLimiter" in original:
        return original  # already applied — no-op
    updated = original.replace(
        "import com.urlshortener.dto.UrlResponse;\nimport com.urlshortener.service.UrlService;",
        "import com.urlshortener.dto.UrlResponse;\n"
        "import com.urlshortener.exception.RateLimitExceededException;\n"
        "import com.urlshortener.service.RateLimiter;\n"
        "import com.urlshortener.service.UrlService;",
    )
    updated = updated.replace(
        "import jakarta.validation.Valid;",
        "import jakarta.servlet.http.HttpServletRequest;\nimport jakarta.validation.Valid;",
    )
    updated = updated.replace(
        "    private final UrlService urlService;\n\n    public UrlController(UrlService urlService) {\n        this.urlService = urlService;\n    }",
        "    private final UrlService urlService;\n    private final RateLimiter rateLimiter;\n\n"
        "    public UrlController(UrlService urlService, RateLimiter rateLimiter) {\n"
        "        this.urlService = urlService;\n"
        "        this.rateLimiter = rateLimiter;\n"
        "    }",
    )
    updated = updated.replace(
        "    public ResponseEntity<UrlResponse> createShortUrl(@Valid @RequestBody CreateUrlRequest request,\n"
        "                                                        @RequestHeader(value = \"Idempotency-Key\", required = false) String idempotencyKey) {\n"
        "        UrlResponse response = urlService.createShortUrl(request, idempotencyKey);",
        "    public ResponseEntity<UrlResponse> createShortUrl(@Valid @RequestBody CreateUrlRequest request,\n"
        "                                                        @RequestHeader(value = \"Idempotency-Key\", required = false) String idempotencyKey,\n"
        "                                                        HttpServletRequest httpRequest) {\n"
        "        if (!rateLimiter.tryAcquire(httpRequest.getRemoteAddr())) {\n"
        "            throw new RateLimitExceededException(\"Rate limit exceeded for URL creation. Try again later.\");\n"
        "        }\n"
        "        UrlResponse response = urlService.createShortUrl(request, idempotencyKey);",
    )
    return updated


def _apply_handler_changes(original: str) -> str:
    if "RateLimitExceededException" in original:
        return original  # already applied — no-op
    anchor = (
        "    @ExceptionHandler(TooManyActiveUrlsException.class)\n"
        "    public ResponseEntity<ErrorResponse> handleTooManyActiveUrls(TooManyActiveUrlsException ex, HttpServletRequest request) {\n"
        "        return build(HttpStatus.TOO_MANY_REQUESTS, ex.getMessage(), request);\n"
        "    }\n"
    )
    addition = (
        anchor
        + "\n    @ExceptionHandler(RateLimitExceededException.class)\n"
        "    public ResponseEntity<ErrorResponse> handleRateLimitExceeded(RateLimitExceededException ex, HttpServletRequest request) {\n"
        "        return build(HttpStatus.TOO_MANY_REQUESTS, ex.getMessage(), request);\n"
        "    }\n"
    )
    return original.replace(anchor, addition)


def _apply_yml_changes(original: str) -> str:
    if "rate-limit" in original:
        return original  # already applied — no-op
    anchor = "app:\n  max-active-urls: 1000000\n  base-url: http://localhost:8080\n"
    addition = anchor + "  rate-limit:\n    enabled: true\n    requests-per-minute: 30\n"
    return original.replace(anchor, addition)


def _apply_controller_test_changes(original: str) -> str:
    if "RateLimiter" in original:
        return original  # already applied — no-op
    updated = original.replace(
        "import com.urlshortener.service.UrlService;",
        "import com.urlshortener.service.RateLimiter;\nimport com.urlshortener.service.UrlService;",
    )
    updated = updated.replace(
        "import org.junit.jupiter.api.Test;",
        "import org.junit.jupiter.api.BeforeEach;\nimport org.junit.jupiter.api.Test;",
    )
    updated = updated.replace(
        "    @MockBean\n    private UrlService urlService;\n",
        "    @MockBean\n    private UrlService urlService;\n\n"
        "    @MockBean\n    private RateLimiter rateLimiter;\n\n"
        "    @BeforeEach\n"
        "    void setUpRateLimiter() {\n"
        "        when(rateLimiter.tryAcquire(any())).thenReturn(true);\n"
        "    }\n",
    )
    new_test = (
        "\n    @Test\n"
        "    void createReturns429WhenRateLimited() throws Exception {\n"
        "        when(rateLimiter.tryAcquire(any())).thenReturn(false);\n\n"
        "        mockMvc.perform(post(\"/api/v1/urls\")\n"
        "                        .contentType(MediaType.APPLICATION_JSON)\n"
        "                        .content(\"{\\\"originalUrl\\\": \\\"https://example.com\\\"}\"))\n"
        "                .andExpect(status().isTooManyRequests());\n"
        "    }\n"
        "}\n"
    )
    updated = updated.rstrip("\n")
    assert updated.endswith("}")
    updated = updated[:-1] + new_test
    return updated


def _apply_readme_changes(original: str) -> str:
    if "Rate-limited" in original:
        return original  # already applied — no-op
    updated = original.replace(
        "| `POST` | `/api/v1/urls` | Create a short URL. Optional `Idempotency-Key` header. |\n",
        "| `POST` | `/api/v1/urls` | Create a short URL. Optional `Idempotency-Key` header. Rate-limited per client IP. |\n",
    )
    updated = updated.replace(
        "### Custom alias",
        "### Rate limiting\n\n"
        "`POST /api/v1/urls` is rate-limited per client IP "
        "(`app.rate-limit.requests-per-minute`, default 30/minute). Exceeding it returns "
        "`429 Too Many Requests`. Disable entirely with `app.rate-limit.enabled: false`.\n\n"
        "### Custom alias",
    )
    return updated
