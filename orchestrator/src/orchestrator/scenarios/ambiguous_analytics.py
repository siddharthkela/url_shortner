"""Ambiguous scenario: "Make the analytics better."

Genuinely vague — no acceptance criteria, no specifics. This scenario
demonstrates two things the other two didn't:

1. Real ambiguity handling: the requirements stage surfaces open questions
   and documents the assumption it proceeds under (autonomous mode, per
   Section 7 of the assignment — agents execute, humans get final review at
   the approval gate) along with the alternatives it rejected and why.

2. Real dynamic re-planning: the *initial* design proposes something that
   conflicts with a discovered constraint (bundling a charting dependency
   for what should be a data-only API), which a dedicated check_constraints
   node catches mid-run and uses to insert a revised design node and
   redirect the downstream implementation/test/docs nodes onto it — not a
   scripted "always replan," but conditional on what design actually
   proposed.
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
from orchestrator.engine.reliability import make_retrying_executor
from orchestrator.engine.replan import insert_nodes, redirect_existing_node
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
    build_agent_node,
    build_codebase_analysis_node,
    build_design_node,
    build_docs_node,
    build_implementation_node,
    build_release_node,
    build_requirements_node,
    build_test_node,
)

RAW_REQUIREMENT = "Make the analytics better."
BRANCH_NAME = "orchestrator-demo/ambiguous-analytics"


def _final_design(ctx: ExecutionContext) -> Dict[str, Any]:
    """Downstream nodes read whichever design actually ended up governing —
    the revised one if a replan happened, the original otherwise.
    """
    return ctx.get_output("redesign") or ctx.get_output("design")


# --------------------------------------------------------------------------
# DAG structure — agent-agnostic, unit-tested with a stub agent.
# --------------------------------------------------------------------------

def build_dag(agent: Agent, repo_root: str) -> DAG:
    dag = DAG()

    dag.add_node(build_requirements_node(
        node_id="intake_requirement",
        agent=agent,
        payload_fn=lambda ctx: {"raw": RAW_REQUIREMENT},
        decision_summary_fn=lambda out: f"Normalized under assumption: {out.get('assumption', '(n/a)')}",
    ))

    dag.add_node(build_codebase_analysis_node(
        node_id="analyze_codebase",
        agent=agent,
        payload_fn=lambda ctx: {"repo_root": repo_root, "requirement": ctx.get_output("intake_requirement")},
        depends_on=["intake_requirement"],
        decision_summary_fn=lambda out: f"Impacted: {out.get('impacted_files', [])}",
    ))

    dag.add_node(build_design_node(
        node_id="design",
        agent=agent,
        payload_fn=lambda ctx: {"impact": ctx.get_output("analyze_codebase")},
        depends_on=["analyze_codebase"],
        decision_summary_fn=lambda out: f"Initial approach: {out.get('approach', '(n/a)')}",
    ))

    # Runs after design, before any implementation work — this ordering is
    # what makes the replan land before implement_code/draft_tests/update_docs
    # start, rather than racing them.
    async def _check_constraints(node: Node, context) -> NodeResult:
        design_output = context.get_output("design", {})
        if design_output.get("introduces_new_dependency"):
            redesign_node = build_agent_node(
                node_id="redesign",
                stage="redesign",
                agent=agent,
                payload_fn=lambda ctx: {
                    "original_design": ctx.get_output("design"),
                    "constraint": "No new third-party dependency for a purely data/API-shape change "
                                   "— this app's established minimal-dependency architecture (see the "
                                   "original engineering plan) applies to feature work too, not just "
                                   "the initial infra choices.",
                },
                depends_on=["check_constraints"],
                decision_summary_fn=lambda out: f"Revised approach: {out.get('approach', '(n/a)')}",
            )
            insert_nodes(
                context,
                [redesign_node],
                reason="design proposed bundling a charting dependency for an API-only endpoint; "
                       "conflicts with the app's no-unnecessary-dependency constraint",
            )
            for downstream in ("implement_code", "draft_tests", "update_docs"):
                redirect_existing_node(
                    context, existing_node_id=downstream, extra_dependency_id="redesign",
                    reason="must implement the revised, dependency-free design, not the original",
                )
            return NodeResult(success=True, output={"replanned": True})
        return NodeResult(success=True, output={"replanned": False})

    dag.add_node(Node(id="check_constraints", run=_check_constraints, depends_on=["design"]))

    dag.add_node(build_implementation_node(
        node_id="implement_code",
        agent=agent,
        payload_fn=lambda ctx: {"design": _final_design(ctx), "repo_root": repo_root},
        depends_on=["check_constraints"],
        decision_summary_fn=lambda out: f"Wrote/modified: {out.get('files_written', [])}",
    ))

    dag.add_node(build_test_node(
        node_id="draft_tests",
        agent=agent,
        payload_fn=lambda ctx: {"design": _final_design(ctx), "repo_root": repo_root},
        depends_on=["check_constraints"],
        decision_summary_fn=lambda out: f"Wrote/modified: {out.get('files_written', [])}",
    ))

    dag.add_node(build_docs_node(
        node_id="update_docs",
        agent=agent,
        payload_fn=lambda ctx: {"design": _final_design(ctx), "repo_root": repo_root},
        depends_on=["check_constraints"],
        decision_summary_fn=lambda out: f"Wrote: {out.get('files_written', [])}",
    ))

    async def _run_tests(node: Node, context) -> NodeResult:
        success, output = run_maven_test(repo_root)
        return NodeResult(success=success, output={"maven_output_tail": output[-2000:]}, error=None if success else "mvn test failed")

    dag.add_node(Node(id="run_tests", run=_run_tests, depends_on=["implement_code", "draft_tests"]))

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
            repo_root=repo_root, file_contents=file_contents,
            touches_files=impl_files + test_files, new_endpoints=[], test_files_created=test_files,
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
        payload_fn=lambda ctx: {"summary": "Analytics improvement ready for review"},
        depends_on=["policy_check", "update_docs"],
        requires_approval=True,
        decision_summary_fn=lambda out: f"Release status: {out.get('status', '(n/a)')}",
    ))

    async def _finalize(node: Node, context) -> NodeResult:
        commit_all(repo_root, "feat: add daysActive/averageClicksPerDay to analytics\n\nOrchestrator ambiguous-requirement demo scenario.")
        push = run_git(repo_root, "push", "-u", "origin", BRANCH_NAME)
        return NodeResult(success=True, output={"pushed": push.returncode == 0, "push_stderr": push.stderr})

    dag.add_node(Node(id="finalize", run=_finalize, depends_on=["release_readiness"]))

    return dag


# --------------------------------------------------------------------------
# End-to-end runner (same pattern as the other two scenarios).
# --------------------------------------------------------------------------

async def run(repo_root: str, auto_approve_all: bool = True) -> RunResult:
    staging_dir = Path(tempfile.mkdtemp(prefix="orchestrator_ambiguous_"))
    events_path = staging_dir / "events.jsonl"

    create_and_checkout_branch(repo_root, BRANCH_NAME, base="main")

    agent = build_ambiguous_agent(repo_root)
    dag = build_dag(agent, repo_root)
    sink = JsonlEventSink(path=events_path)
    approval = ApprovalManager(
        autonomy=AutonomyLevel.ASSISTED,
        decision_fn=auto_approve if auto_approve_all else interactive_prompt,
        event_sink=sink,
    )
    context = ExecutionContext(run_id="ambiguous-analytics")
    scheduler = Scheduler(event_sink=sink, approval_manager=approval, retry_executor=make_retrying_executor(event_sink=sink))

    result = await scheduler.run(dag, context)

    metrics = compute_metrics(sink.events)
    write_dashboard(staging_dir / "dashboard.html", run_id=context.run_id, dag=dag, metrics=metrics)
    write_run_summary(
        staging_dir / "SUMMARY.md",
        scenario_name="Ambiguous: \"make the analytics better\"",
        requirement=RAW_REQUIREMENT,
        branch_name=BRANCH_NAME,
        context=context,
        metrics=metrics,
        risks=[
            "Proceeding under a documented assumption rather than blocking on human clarification "
            "carries the risk of building the wrong thing — mitigated by the assumption and "
            "rejected alternatives being explicit in this summary and the release-approval gate, "
            "not silently baked in.",
        ],
        assumptions=[
            "\"Better\" is interpreted as: more informative per-URL analytics (daysActive, "
            "averageClicksPerDay) computed from data already tracked — not a new dashboard UI, "
            "not CSV export, not per-referrer tracking (all plausible alternative readings, "
            "rejected because the vague requirement gave no signal favoring one over another, "
            "and this reading needs zero new dependencies or schema changes).",
        ],
        limitations=[
            "No historical time-series (e.g. clicks-per-day-for-the-last-30-days) — that would "
            "need a new per-click-event table, a materially bigger change than a two-day-old "
            "vague requirement justifies without further clarification.",
        ],
    )

    run_git(repo_root, "checkout", "main")
    dest = Path(repo_root) / "orchestrator" / "runs" / "ambiguous"
    dest.mkdir(parents=True, exist_ok=True)
    for artifact in ("events.jsonl", "dashboard.html", "SUMMARY.md"):
        shutil.copy(staging_dir / artifact, dest / artifact)
    shutil.rmtree(staging_dir, ignore_errors=True)

    return result


# --------------------------------------------------------------------------
# Real scripted handlers.
# --------------------------------------------------------------------------

def build_ambiguous_agent(repo_root: str) -> DeterministicAgent:
    async def requirements_handler(payload: Dict[str, Any]) -> AgentResult:
        return AgentResult(
            success=True,
            output={
                "normalized_requirement": "Add more informative per-URL analytics computed from "
                                           "already-tracked data, without new dependencies or schema changes.",
                "open_questions": [
                    "\"Better\" how — more granularity (per-day breakdown)? A UI/dashboard? "
                    "CSV export? Per-referrer tracking?",
                    "Is a new historical events table in scope, or should this stay within the "
                    "existing aggregate-counter schema?",
                ],
                "assumption": "Proceeding autonomously (per the assignment's controlled-autonomy "
                               "principle: agents execute, humans get final review at the approval "
                               "gate) under the narrowest reading that adds real value without new "
                               "infrastructure: daysActive + averageClicksPerDay, computed from "
                               "fields the entity already has.",
                "rejected_alternatives": [
                    "Dashboard UI — no frontend exists in this app yet; out of proportion for a "
                    "vague one-line requirement.",
                    "CSV export — plausible, but no signal in the requirement favors it over other "
                    "readings; a smaller, reversible step is safer under ambiguity.",
                    "Per-referrer tracking — needs a new column captured at redirect time; larger "
                    "surface change than justified without clarification.",
                ],
            },
            rationale="Under genuine ambiguity, prefer the reading that is smallest, reversible, and "
                      "needs no new infrastructure — easiest to correct later if the assumption "
                      "turns out wrong, and the assumption itself is surfaced for human review "
                      "rather than silently baked in.",
        )

    async def codebase_analysis_handler(payload: Dict[str, Any]) -> AgentResult:
        return AgentResult(
            success=True,
            output={
                "impacted_files": [
                    "src/main/java/com/urlshortener/dto/AnalyticsResponse.java",
                    "src/main/java/com/urlshortener/mapper/UrlMapper.java",
                ],
                "existing_fields_available": ["createdAt", "clickCount"],
            },
            rationale="ShortUrlEntity already has createdAt and clickCount — daysActive and "
                      "averageClicksPerDay are pure computations over data already persisted, "
                      "confirmed by reading the entity before designing around it.",
        )

    async def design_handler(payload: Dict[str, Any]) -> AgentResult:
        # Deliberately the "wrong" first idea — this is what triggers the replan.
        return AgentResult(
            success=True,
            output={
                "approach": "Add a small embedded sparkline chart (via a lightweight charting "
                            "library) rendered server-side into the analytics response for a quick "
                            "visual trend indicator.",
                "introduces_new_dependency": True,
            },
            rationale="A visual trend indicator seemed like the most literal reading of 'better' — "
                      "reconsidered once check_constraints flags the dependency conflict.",
        )

    async def redesign_handler(payload: Dict[str, Any]) -> AgentResult:
        return AgentResult(
            success=True,
            output={
                "approach": "Drop the charting idea. Add daysActive (days since creation, minimum "
                            "1) and averageClicksPerDay (clickCount / daysActive) as plain computed "
                            "fields on AnalyticsResponse — no new dependency, no schema change, "
                            "computed entirely from ShortUrlEntity.createdAt and clickCount.",
                "introduces_new_dependency": False,
            },
            rationale=f"Constraint violated by the original design: {payload.get('constraint', '')}. "
                      "A plain-data response satisfies the same underlying need (more informative "
                      "analytics) without the dependency, and is strictly simpler to maintain.",
        )

    async def implementation_handler(payload: Dict[str, Any]) -> AgentResult:
        analytics_dto_path = Path(repo_root) / "src/main/java/com/urlshortener/dto/AnalyticsResponse.java"
        mapper_path = Path(repo_root) / "src/main/java/com/urlshortener/mapper/UrlMapper.java"

        changes = [
            FileChange("src/main/java/com/urlshortener/dto/AnalyticsResponse.java", _ANALYTICS_RESPONSE_JAVA),
            FileChange(
                "src/main/java/com/urlshortener/mapper/UrlMapper.java",
                _apply_mapper_changes(mapper_path.read_text()),
            ),
        ]
        written = write_files(repo_root, changes)
        return AgentResult(success=True, output={"files_written": written})

    async def test_handler(payload: Dict[str, Any]) -> AgentResult:
        service_test_path = Path(repo_root) / "src/test/java/com/urlshortener/service/UrlServiceTest.java"
        controller_test_path = Path(repo_root) / "src/test/java/com/urlshortener/controller/UrlControllerTest.java"

        changes = [
            FileChange(
                "src/test/java/com/urlshortener/service/UrlServiceTest.java",
                _apply_service_test_changes(service_test_path.read_text()),
            ),
            FileChange(
                "src/test/java/com/urlshortener/controller/UrlControllerTest.java",
                _apply_controller_test_changes(controller_test_path.read_text()),
            ),
        ]
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
        "redesign": redesign_handler,
        "implementation": implementation_handler,
        "test": test_handler,
        "docs": docs_handler,
        "release": release_handler,
    })


# --------------------------------------------------------------------------
# Java/text templates and idempotent insertions.
# --------------------------------------------------------------------------

_ANALYTICS_RESPONSE_JAVA = """package com.urlshortener.dto;

import java.time.Instant;

public record AnalyticsResponse(
        String shortCode,
        long clickCount,
        Instant firstAccessedAt,
        Instant lastAccessedAt,
        long daysActive,
        double averageClicksPerDay
) {
}
"""


def _apply_mapper_changes(original: str) -> str:
    if "daysActive" in original:
        return original  # already applied — no-op
    updated = original.replace(
        "import com.urlshortener.entity.ShortUrlEntity;",
        "import com.urlshortener.entity.ShortUrlEntity;\n\nimport java.time.Duration;\nimport java.time.Instant;",
    )
    updated = updated.replace(
        "    public static AnalyticsResponse toAnalyticsResponse(ShortUrlEntity entity) {\n"
        "        return new AnalyticsResponse(\n"
        "                entity.getShortCode(),\n"
        "                entity.getClickCount(),\n"
        "                entity.getFirstAccessedAt(),\n"
        "                entity.getLastAccessedAt()\n"
        "        );\n"
        "    }",
        "    public static AnalyticsResponse toAnalyticsResponse(ShortUrlEntity entity) {\n"
        "        long daysActive = Math.max(1, Duration.between(entity.getCreatedAt(), Instant.now()).toDays());\n"
        "        double averageClicksPerDay = entity.getClickCount() / (double) daysActive;\n"
        "        return new AnalyticsResponse(\n"
        "                entity.getShortCode(),\n"
        "                entity.getClickCount(),\n"
        "                entity.getFirstAccessedAt(),\n"
        "                entity.getLastAccessedAt(),\n"
        "                daysActive,\n"
        "                averageClicksPerDay\n"
        "        );\n"
        "    }",
    )
    return updated


def _apply_service_test_changes(original: str) -> str:
    if "daysActive" in original:
        return original  # already applied — no-op
    return original.replace(
        "        assertThat(response.firstAccessedAt()).isEqualTo(first);\n"
        "        assertThat(response.lastAccessedAt()).isEqualTo(last);\n"
        "    }",
        "        assertThat(response.firstAccessedAt()).isEqualTo(first);\n"
        "        assertThat(response.lastAccessedAt()).isEqualTo(last);\n"
        "        assertThat(response.daysActive()).isEqualTo(1);\n"
        "        assertThat(response.averageClicksPerDay()).isEqualTo(7.0);\n"
        "    }",
    )


def _apply_controller_test_changes(original: str) -> str:
    if "daysActive" in original:
        return original  # already applied — no-op
    return original.replace(
        'AnalyticsResponse response = new AnalyticsResponse("abc123", 5, Instant.now(), Instant.now());',
        'AnalyticsResponse response = new AnalyticsResponse("abc123", 5, Instant.now(), Instant.now(), 3, 1.67);',
    )


def _apply_readme_changes(original: str) -> str:
    if "averageClicksPerDay" in original:
        return original  # already applied — no-op
    return original.replace(
        "| `GET` | `/api/v1/urls/{shortCode}/analytics` | Click count, first/last accessed timestamps. |\n",
        "| `GET` | `/api/v1/urls/{shortCode}/analytics` | Click count, first/last accessed timestamps, "
        "`daysActive`, `averageClicksPerDay`. |\n",
    )
