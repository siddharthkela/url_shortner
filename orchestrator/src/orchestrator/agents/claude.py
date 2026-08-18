"""Real Anthropic API adapter — pluggable, not used by any demo run in this
deliverable (no API key is configured; see ARCHITECTURE.md). Wired to the
same Agent protocol as DeterministicAgent so switching a stage from scripted
to live reasoning is a one-line config change.

Prompt-building and response-parsing are plain functions, independent of
the network client, so they're unit-testable without a live API key — only
_get_client() and run() touch the network, and run() accepts an injectable
client for the same reason.
"""
from __future__ import annotations

import os
from typing import Any, Optional

from orchestrator.agents.base import AgentResult, AgentTask

STAGE_INSTRUCTIONS = {
    "requirements": (
        "You are the requirements-understanding stage of an SDLC orchestrator. "
        "Given a raw requirement, interpret intent, list open ambiguities, and "
        "propose a normalized problem statement with explicit acceptance criteria."
    ),
    "codebase_analysis": (
        "You are the codebase-reasoning stage. Given a requirement and a repo "
        "summary, identify impacted files/modules/APIs and describe the blast radius."
    ),
    "design": (
        "You are the design stage. Given a normalized requirement and impact "
        "analysis, propose a concrete technical approach and the tasks it decomposes into."
    ),
    "implementation": (
        "You are the implementation stage. Given a design, produce the actual code change."
    ),
    "test": (
        "You are the test stage. Given a design/implementation, produce unit/integration tests."
    ),
    "docs": (
        "You are the documentation stage. Given a design/implementation, produce user-facing docs."
    ),
    "release": (
        "You are the release-readiness stage. Summarize what changed, risks, and validation status."
    ),
}


def build_prompt(stage: str, payload: dict) -> str:
    instruction = STAGE_INSTRUCTIONS.get(stage, f"You are the '{stage}' stage of an SDLC orchestrator.")
    context_lines = "\n".join(f"- {key}: {value}" for key, value in payload.items())
    return f"{instruction}\n\nContext:\n{context_lines}\n"


def parse_response(stage: str, response_text: str) -> AgentResult:
    if not response_text or not response_text.strip():
        return AgentResult(success=False, error=f"empty response from model for stage '{stage}'")
    return AgentResult(
        success=True,
        output={"text": response_text},
        rationale=response_text[:200],
    )


class ClaudeAgent:
    def __init__(self, model: str = "claude-sonnet-5", api_key: Optional[str] = None, client: Optional[Any] = None):
        self.model = model
        self._api_key = api_key
        self._client = client

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client

        # Check for the API key before importing the SDK: it's the more
        # fundamental blocker (no key means no call is possible regardless
        # of whether the package is installed), so fail on that first with
        # the more actionable message.
        api_key = self._api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. ClaudeAgent requires a real API key for "
                "live calls; every demo scenario in this deliverable uses "
                "DeterministicAgent instead and needs no key."
            )

        try:
            import anthropic
        except ImportError as exc:
            raise RuntimeError(
                "The 'anthropic' package is required for ClaudeAgent live calls. "
                "Install with: pip install -e '.[claude]'"
            ) from exc

        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        return self._client

    async def run(self, task: AgentTask) -> AgentResult:
        client = self._get_client()
        prompt = build_prompt(task.stage, task.payload)
        response = await client.messages.create(
            model=self.model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        response_text = "".join(block.text for block in response.content if hasattr(block, "text"))
        return parse_response(task.stage, response_text)
