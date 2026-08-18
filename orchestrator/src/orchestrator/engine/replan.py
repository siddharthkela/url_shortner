"""Convenience layer over ExecutionContext.replan() for stages that need to
mutate the live DAG mid-run — e.g. codebase analysis discovers more impacted
files than expected, or a clarified requirement expands scope partway
through a run. The underlying mechanism lives in context.py (the
replan_hook) and dag.py (Scheduler._apply_replan); this module just gives
stage code two clear, purpose-built entry points instead of hand-building
DAG mutations inline.
"""
from __future__ import annotations

from typing import List

from orchestrator.engine.context import ExecutionContext
from orchestrator.engine.dag import Node


def insert_nodes(context: ExecutionContext, new_nodes: List[Node], reason: str) -> None:
    """Add new nodes to the live DAG. Each node's own `depends_on` is honored
    as-is — set it before calling this to wire the new work to existing or
    other newly-inserted nodes.
    """
    context.replan(new_nodes=new_nodes, new_edges={}, reason=reason)


def redirect_existing_node(context: ExecutionContext, existing_node_id: str, extra_dependency_id: str, reason: str) -> None:
    """Make an already-defined node additionally wait on another node — e.g.
    a newly inserted task should also gate release, not just the original
    dependency chain.
    """
    context.replan(new_nodes=[], new_edges={existing_node_id: [extra_dependency_id]}, reason=reason)
