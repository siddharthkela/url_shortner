"""Agent abstraction: every SDLC stage delegates its actual reasoning/codegen
work to an Agent. The interface is deliberately narrow (one task in, one
result out) so DeterministicAgent (scripted, offline, used by every demo
run) and ClaudeAgent (real Anthropic API calls) are interchangeable —
switching which one a stage uses is a config change, not a redesign.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Protocol


@dataclass
class AgentTask:
    stage: str
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResult:
    success: bool
    output: Dict[str, Any] = field(default_factory=dict)
    rationale: str = ""
    error: str = ""


class Agent(Protocol):
    async def run(self, task: AgentTask) -> AgentResult: ...


HandlerFn = Callable[[Dict[str, Any]], Awaitable[AgentResult]]
