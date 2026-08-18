"""Scripted agent: dispatches each task to a handler function registered by
stage name. This is what every demo scenario actually runs against — the
scenario definition supplies the handlers (its real, hand-authored
requirements/design/implementation/test/docs logic for that specific
feature), and DeterministicAgent is just the generic dispatcher. Offline,
zero-cost, fully reproducible — which is also why it's what the automated
test suite exercises.
"""
from __future__ import annotations

from typing import Dict

from orchestrator.agents.base import AgentResult, AgentTask, HandlerFn


class DeterministicAgent:
    def __init__(self, handlers: Dict[str, HandlerFn]):
        self.handlers = handlers

    async def run(self, task: AgentTask) -> AgentResult:
        handler = self.handlers.get(task.stage)
        if handler is None:
            return AgentResult(
                success=False,
                error=f"no deterministic handler registered for stage '{task.stage}'",
            )
        return await handler(task.payload)
