import os
from dataclasses import dataclass
from typing import List

import pytest

from orchestrator.agents.base import AgentResult, AgentTask
from orchestrator.agents.claude import ClaudeAgent, build_prompt, parse_response
from orchestrator.agents.deterministic import DeterministicAgent


# --- DeterministicAgent -------------------------------------------------

@pytest.mark.asyncio
async def test_deterministic_agent_dispatches_to_registered_handler():
    async def requirements_handler(payload):
        return AgentResult(success=True, output={"normalized": payload["raw"].upper()})

    agent = DeterministicAgent(handlers={"requirements": requirements_handler})
    result = await agent.run(AgentTask(stage="requirements", payload={"raw": "add qr codes"}))

    assert result.success
    assert result.output["normalized"] == "ADD QR CODES"


@pytest.mark.asyncio
async def test_deterministic_agent_fails_clearly_for_unregistered_stage():
    agent = DeterministicAgent(handlers={})
    result = await agent.run(AgentTask(stage="unknown_stage", payload={}))

    assert not result.success
    assert "unknown_stage" in result.error


@pytest.mark.asyncio
async def test_deterministic_agent_supports_multiple_stages():
    async def design_handler(payload):
        return AgentResult(success=True, output={"approach": "token bucket"})

    async def test_handler(payload):
        return AgentResult(success=True, output={"tests": ["RateLimitTest"]})

    agent = DeterministicAgent(handlers={"design": design_handler, "test": test_handler})

    design_result = await agent.run(AgentTask(stage="design", payload={}))
    test_result = await agent.run(AgentTask(stage="test", payload={}))

    assert design_result.output["approach"] == "token bucket"
    assert test_result.output["tests"] == ["RateLimitTest"]


# --- ClaudeAgent prompt/response (pure functions, no network) ----------

def test_build_prompt_includes_stage_instruction_and_payload():
    prompt = build_prompt("design", {"requirement": "add rate limiting"})
    assert "design stage" in prompt.lower()
    assert "add rate limiting" in prompt


def test_build_prompt_falls_back_for_unknown_stage():
    prompt = build_prompt("some_future_stage", {"x": 1})
    assert "some_future_stage" in prompt


def test_parse_response_wraps_text_into_agent_result():
    result = parse_response("design", "Use a token bucket per owner token.")
    assert result.success
    assert result.output["text"] == "Use a token bucket per owner token."


def test_parse_response_fails_on_empty_text():
    result = parse_response("design", "   ")
    assert not result.success
    assert "empty response" in result.error


# --- ClaudeAgent with an injected fake client (still no network) -------

@dataclass
class _FakeTextBlock:
    text: str


@dataclass
class _FakeResponse:
    content: List[_FakeTextBlock]


class _FakeMessages:
    def __init__(self, response_text: str):
        self._response_text = response_text
        self.last_call_kwargs = None

    async def create(self, **kwargs):
        self.last_call_kwargs = kwargs
        return _FakeResponse(content=[_FakeTextBlock(text=self._response_text)])


class _FakeClient:
    def __init__(self, response_text: str):
        self.messages = _FakeMessages(response_text)


@pytest.mark.asyncio
async def test_claude_agent_run_with_injected_client_returns_parsed_result():
    fake_client = _FakeClient(response_text="Proposed approach: token bucket rate limiter.")
    agent = ClaudeAgent(client=fake_client)

    result = await agent.run(AgentTask(stage="design", payload={"requirement": "rate limit creation"}))

    assert result.success
    assert "token bucket" in result.output["text"]
    assert fake_client.messages.last_call_kwargs["model"] == "claude-sonnet-5"


@pytest.mark.asyncio
async def test_claude_agent_without_client_or_api_key_raises_clear_error(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    agent = ClaudeAgent()

    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        await agent.run(AgentTask(stage="design", payload={}))
