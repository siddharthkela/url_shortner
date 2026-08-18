"""Turns an Agent + a payload-extraction function into a DAG Node.

Every SDLC stage's node-construction mechanics are identical: pull whatever
this stage needs out of the shared context, hand it to the agent tagged with
this stage's name, and on success record the decision into the lineage
before returning the output. Rather than duplicating that seven times (one
per stage), this is the one generic factory; stages/__init__.py exposes
named partials (build_requirements_node, build_design_node, ...) over it so
scenario code reads as "the requirements stage" rather than a raw stage
string.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from orchestrator.agents.base import Agent, AgentTask
from orchestrator.engine.context import ExecutionContext
from orchestrator.engine.dag import GateFn, Node, NodeFn, NodeResult

PayloadFn = Callable[[ExecutionContext], Dict[str, Any]]
SummaryFn = Callable[[Dict[str, Any]], str]


def build_agent_node(
    node_id: str,
    stage: str,
    agent: Agent,
    payload_fn: PayloadFn,
    depends_on: Optional[List[str]] = None,
    entry_gate: Optional[GateFn] = None,
    exit_gate: Optional[GateFn] = None,
    retry_policy: Optional[Any] = None,
    requires_approval: bool = False,
    fallback: Optional[NodeFn] = None,
    rollback: Optional[Callable[[Node, ExecutionContext], None]] = None,
    touches_files: Optional[List[str]] = None,
    decision_summary_fn: Optional[SummaryFn] = None,
) -> Node:
    async def _run(node: Node, context: ExecutionContext) -> NodeResult:
        payload = payload_fn(context)
        agent_result = await agent.run(AgentTask(stage=stage, payload=payload))
        if not agent_result.success:
            return NodeResult(success=False, error=agent_result.error or f"{stage} agent failed")

        summary = decision_summary_fn(agent_result.output) if decision_summary_fn else f"{stage} completed"
        context.record_decision(
            stage=stage,
            summary=summary,
            rationale=agent_result.rationale or "",
            inputs=payload,
            outputs=agent_result.output,
        )
        return NodeResult(success=True, output=agent_result.output)

    return Node(
        id=node_id,
        run=_run,
        depends_on=depends_on or [],
        entry_gate=entry_gate,
        exit_gate=exit_gate,
        retry_policy=retry_policy,
        requires_approval=requires_approval,
        fallback=fallback,
        rollback=rollback,
        touches_files=touches_files or [],
    )
