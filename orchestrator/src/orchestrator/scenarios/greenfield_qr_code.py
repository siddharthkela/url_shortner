"""Greenfield scenario: "Let users get a QR code for their short URL."

New GET /api/v1/urls/{shortCode}/qrcode endpoint. This is the pure
new-feature demonstration — no existing behavior changes, only additions.
build_dag() is agent-agnostic (testable with any stub Agent); the real,
working Java is only in build_greenfield_agent()'s handlers, exercised by
the actual end-to-end run (scripts/run_greenfield.py), not by pytest.
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
from orchestrator.engine.gates import policy_exit_gate
from orchestrator.engine.policy import PolicyContext, PolicyEngine
from orchestrator.observability.dashboard import write_dashboard
from orchestrator.observability.event_log import JsonlEventSink
from orchestrator.observability.metrics import compute_metrics
from orchestrator.scenarios.common import (
    FileChange,
    commit_all,
    create_and_checkout_branch,
    write_files,
    run_git,
    run_maven_test,
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

RAW_REQUIREMENT = "Let users get a QR code image for their short URL so it can be shared/printed."
BRANCH_NAME = "orchestrator-demo/greenfield-qr-code"
NEW_ENDPOINT = "GET /api/v1/urls/{shortCode}/qrcode"


# --------------------------------------------------------------------------
# DAG structure — agent-agnostic, unit-tested with a stub agent.
# --------------------------------------------------------------------------

def build_dag(agent: Agent, repo_root: str) -> DAG:
    dag = DAG()

    dag.add_node(build_requirements_node(
        node_id="intake_requirement",
        agent=agent,
        payload_fn=lambda ctx: {"raw": RAW_REQUIREMENT},
    ))

    dag.add_node(build_codebase_analysis_node(
        node_id="analyze_codebase",
        agent=agent,
        payload_fn=lambda ctx: {"repo_root": repo_root, "requirement": ctx.get_output("intake_requirement")},
        depends_on=["intake_requirement"],
    ))

    dag.add_node(build_design_node(
        node_id="design",
        agent=agent,
        payload_fn=lambda ctx: {"impact": ctx.get_output("analyze_codebase")},
        depends_on=["analyze_codebase"],
    ))

    dag.add_node(build_implementation_node(
        node_id="implement_code",
        agent=agent,
        payload_fn=lambda ctx: {"design": ctx.get_output("design"), "repo_root": repo_root},
        depends_on=["design"],
    ))

    dag.add_node(build_test_node(
        node_id="draft_tests",
        agent=agent,
        payload_fn=lambda ctx: {"design": ctx.get_output("design"), "repo_root": repo_root},
        depends_on=["design"],
    ))

    dag.add_node(build_docs_node(
        node_id="update_docs",
        agent=agent,
        payload_fn=lambda ctx: {"design": ctx.get_output("design"), "repo_root": repo_root},
        depends_on=["design"],
    ))

    policy_engine = PolicyEngine.default()

    def _policy_ctx(node, ctx) -> PolicyContext:
        impl_files = ctx.get_output("implement_code", {}).get("files_written", [])
        test_files = ctx.get_output("draft_tests", {}).get("files_written", [])
        file_contents = {}
        for rel_path in impl_files + test_files:
            full = Path(repo_root) / rel_path
            if full.exists():
                file_contents[rel_path] = full.read_text()
        return PolicyContext(
            repo_root=repo_root,
            file_contents=file_contents,
            touches_files=impl_files + test_files,
            new_endpoints=[NEW_ENDPOINT],
            test_files_created=test_files,
        )

    async def _run_tests(node: Node, context) -> NodeResult:
        success, output = run_maven_test(repo_root)
        return NodeResult(success=success, output={"maven_output_tail": output[-2000:]}, error=None if success else "mvn test failed")

    dag.add_node(Node(
        id="run_tests",
        run=_run_tests,
        depends_on=["implement_code", "draft_tests"],
        exit_gate=policy_exit_gate(policy_engine, _policy_ctx),
    ))

    dag.add_node(build_release_node(
        node_id="release_readiness",
        agent=agent,
        payload_fn=lambda ctx: {"summary": "QR code endpoint ready for review"},
        depends_on=["run_tests", "update_docs"],
        requires_approval=True,
    ))

    async def _finalize(node: Node, context) -> NodeResult:
        commit_all(repo_root, "feat: add QR code endpoint for short URLs\n\nOrchestrator greenfield demo scenario.")
        push = run_git(repo_root, "push", "-u", "origin", BRANCH_NAME)
        return NodeResult(success=True, output={"pushed": push.returncode == 0, "push_stderr": push.stderr})

    dag.add_node(Node(id="finalize", run=_finalize, depends_on=["release_readiness"]))

    return dag


# --------------------------------------------------------------------------
# End-to-end runner: creates the branch, runs the DAG for real, writes
# artifacts. Event log/dashboard/summary are staged outside the git working
# tree during the run so `git add -A` on the feature branch only ever picks
# up the actual Java change — artifacts get copied onto `main` separately,
# after the branch work is done, keeping the two commit histories clean.
# --------------------------------------------------------------------------

async def run(repo_root: str, auto_approve_all: bool = True) -> RunResult:
    staging_dir = Path(tempfile.mkdtemp(prefix="orchestrator_greenfield_"))
    events_path = staging_dir / "events.jsonl"

    create_and_checkout_branch(repo_root, BRANCH_NAME, base="main")

    agent = build_greenfield_agent(repo_root)
    dag = build_dag(agent, repo_root)
    sink = JsonlEventSink(path=events_path)
    approval = ApprovalManager(
        autonomy=AutonomyLevel.ASSISTED,
        decision_fn=auto_approve if auto_approve_all else interactive_prompt,
        event_sink=sink,
    )
    context = ExecutionContext(run_id="greenfield-qr-code")
    scheduler = Scheduler(event_sink=sink, approval_manager=approval)

    result = await scheduler.run(dag, context)

    metrics = compute_metrics(sink.events)
    write_dashboard(staging_dir / "dashboard.html", run_id=context.run_id, dag=dag, metrics=metrics)
    write_run_summary(
        staging_dir / "SUMMARY.md",
        scenario_name="Greenfield: QR code generation",
        requirement=RAW_REQUIREMENT,
        branch_name=BRANCH_NAME,
        context=context,
        metrics=metrics,
        risks=[
            "ZXing is a new third-party dependency; supply-chain risk is low (widely used, "
            "Apache-2.0, no transitive dependencies pulled in beyond javase's AWT usage).",
            "QR generation happens synchronously in the request thread; a very high request "
            "rate to this endpoint specifically could add latency — acceptable at this app's "
            "target throughput, called out for future rate-limiting if usage grows.",
        ],
        assumptions=[
            "The QR code should encode the short URL (redirect link), not the original long URL, "
            "so scanning it always reflects the current target even after an update.",
            "PNG at 300x300 is a reasonable default size; no requirement specified print/display "
            "context that would justify a larger size or a different format (SVG).",
        ],
        limitations=[
            "No caching of generated QR images — regenerated on every request. Not a concern at "
            "this app's scale; would be the first thing to revisit if this endpoint got hot.",
        ],
    )

    run_git(repo_root, "checkout", "main")
    dest = Path(repo_root) / "orchestrator" / "runs" / "greenfield"
    dest.mkdir(parents=True, exist_ok=True)
    for artifact in ("events.jsonl", "dashboard.html", "SUMMARY.md"):
        shutil.copy(staging_dir / artifact, dest / artifact)
    shutil.rmtree(staging_dir, ignore_errors=True)

    return result


# --------------------------------------------------------------------------
# Real scripted handlers — the actual Java code this scenario produces.
# --------------------------------------------------------------------------

def build_greenfield_agent(repo_root: str) -> DeterministicAgent:
    async def requirements_handler(payload: Dict[str, Any]) -> AgentResult:
        return AgentResult(
            success=True,
            output={
                "normalized_requirement": "Add a GET endpoint returning a PNG QR code that encodes a short URL's redirect link.",
                "acceptance_criteria": [
                    "GET /api/v1/urls/{shortCode}/qrcode returns 200 with Content-Type image/png for an active short URL",
                    "Returns 404/410 consistent with existing details-lookup behavior for unknown/expired codes",
                    "The QR code encodes the short URL (redirect link), not the original long URL",
                ],
                "open_questions": [],
            },
            rationale="Requirement is well-defined; no ambiguity to surface.",
        )

    async def codebase_analysis_handler(payload: Dict[str, Any]) -> AgentResult:
        return AgentResult(
            success=True,
            output={
                "impacted_files": [
                    "src/main/java/com/urlshortener/controller/UrlController.java",
                    "pom.xml",
                ],
                "new_files": [
                    "src/main/java/com/urlshortener/service/QrCodeService.java",
                    "src/main/java/com/urlshortener/exception/QrCodeGenerationException.java",
                ],
                "approach": "Reuse UrlService.getDetails() for the existing active/expired lookup semantics; "
                            "add a small QrCodeService wrapping ZXing for PNG generation.",
            },
            rationale="UrlController already centralizes shortCode lookups; extending it keeps the endpoint "
                      "surface consistent instead of introducing a second controller.",
        )

    async def design_handler(payload: Dict[str, Any]) -> AgentResult:
        return AgentResult(
            success=True,
            output={
                "library": "com.google.zxing (core + javase), 3.5.4 — widely used, permissive Apache-2.0 license",
                "new_service": "QrCodeService.generatePng(String content) -> byte[]",
                "endpoint": NEW_ENDPOINT,
                "error_handling": "QrCodeGenerationException wraps ZXing's checked WriterException; falls "
                                   "through to the existing generic 500 handler rather than adding a new "
                                   "status mapping for what should never happen with valid input.",
            },
            rationale="Smallest change that satisfies the acceptance criteria: one new service, one new "
                      "endpoint method, reusing all existing lookup/error-handling machinery.",
        )

    async def implementation_handler(payload: Dict[str, Any]) -> AgentResult:
        changes = [
            FileChange("src/main/java/com/urlshortener/exception/QrCodeGenerationException.java", _QR_EXCEPTION_JAVA),
            FileChange("src/main/java/com/urlshortener/service/QrCodeService.java", _QR_SERVICE_JAVA),
        ]

        controller_path = Path(repo_root) / "src/main/java/com/urlshortener/controller/UrlController.java"
        original = controller_path.read_text()
        updated = _apply_controller_changes(original)
        changes.append(FileChange("src/main/java/com/urlshortener/controller/UrlController.java", updated))

        pom_path = Path(repo_root) / "pom.xml"
        pom_original = pom_path.read_text()
        pom_updated = _apply_pom_changes(pom_original)
        changes.append(FileChange("pom.xml", pom_updated))

        written = write_files(repo_root, changes)
        return AgentResult(success=True, output={"files_written": written})

    async def test_handler(payload: Dict[str, Any]) -> AgentResult:
        changes = [
            FileChange("src/test/java/com/urlshortener/service/QrCodeServiceTest.java", _QR_SERVICE_TEST_JAVA),
        ]

        controller_test_path = Path(repo_root) / "src/test/java/com/urlshortener/controller/UrlControllerTest.java"
        original = controller_test_path.read_text()
        updated = _apply_controller_test_changes(original)
        changes.append(FileChange("src/test/java/com/urlshortener/controller/UrlControllerTest.java", updated))

        written = write_files(repo_root, changes)
        return AgentResult(success=True, output={"files_written": written})

    async def docs_handler(payload: Dict[str, Any]) -> AgentResult:
        readme_path = Path(repo_root) / "README.md"
        original = readme_path.read_text()
        updated = _apply_readme_changes(original)
        written = write_files(repo_root, [FileChange("README.md", updated)])
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
# Java/text templates and precise insertions into existing files.
# --------------------------------------------------------------------------

_QR_EXCEPTION_JAVA = """package com.urlshortener.exception;

public class QrCodeGenerationException extends RuntimeException {
    public QrCodeGenerationException(String message, Throwable cause) {
        super(message, cause);
    }
}
"""

_QR_SERVICE_JAVA = """package com.urlshortener.service;

import com.google.zxing.BarcodeFormat;
import com.google.zxing.WriterException;
import com.google.zxing.client.j2se.MatrixToImageWriter;
import com.google.zxing.common.BitMatrix;
import com.google.zxing.qrcode.QRCodeWriter;
import com.urlshortener.exception.QrCodeGenerationException;
import org.springframework.stereotype.Service;

import java.io.ByteArrayOutputStream;
import java.io.IOException;

@Service
public class QrCodeService {

    private static final int QR_SIZE = 300;

    public byte[] generatePng(String content) {
        try {
            QRCodeWriter writer = new QRCodeWriter();
            BitMatrix matrix = writer.encode(content, BarcodeFormat.QR_CODE, QR_SIZE, QR_SIZE);
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            MatrixToImageWriter.writeToStream(matrix, "PNG", out);
            return out.toByteArray();
        } catch (WriterException | IOException e) {
            throw new QrCodeGenerationException("Failed to generate QR code for short URL", e);
        }
    }
}
"""

_QR_SERVICE_TEST_JAVA = """package com.urlshortener.service;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class QrCodeServiceTest {

    private final QrCodeService qrCodeService = new QrCodeService();

    @Test
    void generatesNonEmptyPngBytes() {
        byte[] png = qrCodeService.generatePng("http://localhost:8080/abc123");

        assertThat(png).isNotEmpty();
        // PNG magic number: 0x89 'P' 'N' 'G' 0x0D 0x0A 0x1A 0x0A
        assertThat(png[0]).isEqualTo((byte) 0x89);
        assertThat(png[1]).isEqualTo((byte) 'P');
        assertThat(png[2]).isEqualTo((byte) 'N');
        assertThat(png[3]).isEqualTo((byte) 'G');
    }

    @Test
    void differentContentProducesDifferentImages() {
        byte[] first = qrCodeService.generatePng("http://localhost:8080/aaa111");
        byte[] second = qrCodeService.generatePng("http://localhost:8080/zzz999");

        assertThat(first).isNotEqualTo(second);
    }

    @Test
    void handlesLongUrlsWithinQrCapacity() {
        String longUrl = "http://localhost:8080/" + "a".repeat(100);
        byte[] png = qrCodeService.generatePng(longUrl);

        assertThat(png).isNotEmpty();
    }
}
"""


def _apply_controller_changes(original: str) -> str:
    updated = original.replace(
        "import com.urlshortener.service.UrlService;",
        "import com.urlshortener.service.QrCodeService;\nimport com.urlshortener.service.UrlService;",
    )
    updated = updated.replace(
        "import org.springframework.http.HttpHeaders;",
        "import org.springframework.http.HttpHeaders;\nimport org.springframework.http.MediaType;",
    )
    updated = updated.replace(
        "    private final UrlService urlService;\n\n    public UrlController(UrlService urlService) {\n        this.urlService = urlService;\n    }",
        "    private final UrlService urlService;\n    private final QrCodeService qrCodeService;\n\n"
        "    public UrlController(UrlService urlService, QrCodeService qrCodeService) {\n"
        "        this.urlService = urlService;\n"
        "        this.qrCodeService = qrCodeService;\n"
        "    }",
    )
    updated = updated.replace(
        "    @PutMapping(\"/api/v1/urls/{shortCode}\")",
        "    @GetMapping(value = \"/api/v1/urls/{shortCode}/qrcode\", produces = MediaType.IMAGE_PNG_VALUE)\n"
        "    public ResponseEntity<byte[]> getQrCode(@PathVariable String shortCode) {\n"
        "        String shortUrl = urlService.getDetails(shortCode).shortUrl();\n"
        "        byte[] png = qrCodeService.generatePng(shortUrl);\n"
        "        return ResponseEntity.ok().contentType(MediaType.IMAGE_PNG).body(png);\n"
        "    }\n\n"
        "    @PutMapping(\"/api/v1/urls/{shortCode}\")",
    )
    return updated


def _apply_pom_changes(original: str) -> str:
    anchor = (
        "        <dependency>\n"
        "            <groupId>com.h2database</groupId>\n"
        "            <artifactId>h2</artifactId>\n"
        "            <scope>runtime</scope>\n"
        "        </dependency>\n"
    )
    addition = (
        anchor
        + "        <dependency>\n"
        "            <groupId>com.google.zxing</groupId>\n"
        "            <artifactId>core</artifactId>\n"
        "            <version>3.5.4</version>\n"
        "        </dependency>\n"
        "        <dependency>\n"
        "            <groupId>com.google.zxing</groupId>\n"
        "            <artifactId>javase</artifactId>\n"
        "            <version>3.5.4</version>\n"
        "        </dependency>\n"
    )
    return original.replace(anchor, addition)


def _apply_controller_test_changes(original: str) -> str:
    updated = original.replace(
        "import com.urlshortener.service.UrlService;",
        "import com.urlshortener.service.QrCodeService;\nimport com.urlshortener.service.UrlService;",
    )
    updated = updated.replace(
        "    @MockBean\n    private UrlService urlService;",
        "    @MockBean\n    private UrlService urlService;\n\n    @MockBean\n    private QrCodeService qrCodeService;",
    )
    new_tests = (
        "\n    @Test\n"
        "    void getQrCodeReturns200WithPngContentType() throws Exception {\n"
        "        UrlResponse response = new UrlResponse(\"abc123\", \"http://localhost:8080/abc123\",\n"
        "                \"https://example.com\", \"owner-token\", Instant.now(), null, true);\n"
        "        when(urlService.getDetails(\"abc123\")).thenReturn(response);\n"
        "        byte[] fakePng = new byte[]{(byte) 0x89, 'P', 'N', 'G'};\n"
        "        when(qrCodeService.generatePng(\"http://localhost:8080/abc123\")).thenReturn(fakePng);\n\n"
        "        mockMvc.perform(get(\"/api/v1/urls/abc123/qrcode\"))\n"
        "                .andExpect(status().isOk())\n"
        "                .andExpect(content().contentType(MediaType.IMAGE_PNG));\n"
        "    }\n\n"
        "    @Test\n"
        "    void getQrCodeReturns404WhenShortCodeNotFound() throws Exception {\n"
        "        when(urlService.getDetails(\"missing\")).thenThrow(new UrlNotFoundException(\"not found\"));\n\n"
        "        mockMvc.perform(get(\"/api/v1/urls/missing/qrcode\"))\n"
        "                .andExpect(status().isNotFound());\n"
        "    }\n\n"
        "    @Test\n"
        "    void getQrCodeReturns410WhenExpired() throws Exception {\n"
        "        when(urlService.getDetails(\"expired\")).thenThrow(new UrlExpiredException(\"expired\"));\n\n"
        "        mockMvc.perform(get(\"/api/v1/urls/expired/qrcode\"))\n"
        "                .andExpect(status().isGone());\n"
        "    }\n"
        "}\n"
    )
    updated = updated.rstrip("\n")
    assert updated.endswith("}")
    updated = updated[: -1] + new_tests
    return updated


def _apply_readme_changes(original: str) -> str:
    updated = original.replace(
        "| `GET` | `/api/v1/urls/{shortCode}/analytics` | Click count, first/last accessed timestamps. |\n",
        "| `GET` | `/api/v1/urls/{shortCode}/analytics` | Click count, first/last accessed timestamps. |\n"
        "| `GET` | `/api/v1/urls/{shortCode}/qrcode` | PNG QR code encoding the short URL. |\n",
    )
    updated = updated.replace(
        "### Custom alias",
        "### QR code\n\n"
        "```bash\n"
        "curl -s http://localhost:8080/api/v1/urls/1/qrcode --output qrcode.png\n"
        "```\n\n"
        "### Custom alias",
    )
    return updated
