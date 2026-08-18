"""Node/DAG model and the async scheduler that executes it.

The scheduler is deliberately built around four small extension points
(GateEvaluator, RetryExecutor, ApprovalManager, EventSink) with trivial
pass-through defaults here. Later phases (gates, reliability, approval,
observability) replace the defaults with real implementations without
touching the scheduler's core loop — each phase's diff stays small and each
phase's tests exercise the same scheduler real subsequent phases will use.

Non-linearity: at every tick the scheduler computes the set of nodes whose
dependencies are all SUCCEEDED and runs all of them concurrently
(asyncio.gather). A node with multiple dependencies is a synchronization
barrier for free — it simply won't be ready until every predecessor is done.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional

from orchestrator.engine.context import ExecutionContext


class NodeStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"


@dataclass
class NodeResult:
    success: bool
    output: Any = None
    error: Optional[str] = None
    used_fallback: bool = False


@dataclass
class GateResult:
    passed: bool
    reason: str = ""


NodeFn = Callable[["Node", ExecutionContext], Awaitable[NodeResult]]
GateFn = Callable[["Node", ExecutionContext], GateResult]


@dataclass
class Node:
    id: str
    run: NodeFn
    depends_on: List[str] = field(default_factory=list)
    entry_gate: Optional[GateFn] = None
    exit_gate: Optional[GateFn] = None
    retry_policy: Optional[Any] = None  # engine.reliability.RetryPolicy, wired in that phase
    requires_approval: bool = False
    fallback: Optional[NodeFn] = None
    rollback: Optional[Callable[["Node", ExecutionContext], None]] = None
    touches_files: List[str] = field(default_factory=list)

    # Runtime state, mutated by the scheduler.
    status: NodeStatus = field(default=NodeStatus.PENDING, compare=False)
    result: Optional[NodeResult] = field(default=None, compare=False)
    attempts: int = field(default=0, compare=False)


class DAG:
    def __init__(self) -> None:
        self.nodes: Dict[str, Node] = {}

    def add_node(self, node: Node) -> None:
        if node.id in self.nodes:
            raise ValueError(f"Duplicate node id: {node.id}")
        for dep in node.depends_on:
            if dep not in self.nodes and dep != node.id:
                # Forward references are allowed (nodes can be added in any
                # order); validated fully in validate_acyclic().
                pass
        self.nodes[node.id] = node

    def add_edge(self, from_id: str, to_id: str) -> None:
        if to_id not in self.nodes:
            raise ValueError(f"Unknown node id: {to_id}")
        if from_id not in self.nodes[to_id].depends_on:
            self.nodes[to_id].depends_on.append(from_id)

    def dependents_of(self, node_id: str) -> List[str]:
        return [n.id for n in self.nodes.values() if node_id in n.depends_on]

    def validate(self) -> None:
        for node in self.nodes.values():
            for dep in node.depends_on:
                if dep not in self.nodes:
                    raise ValueError(f"Node '{node.id}' depends on unknown node '{dep}'")
        self._assert_acyclic()

    def _assert_acyclic(self) -> None:
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {node_id: WHITE for node_id in self.nodes}

        def visit(node_id: str, stack: List[str]) -> None:
            color[node_id] = GRAY
            for dep in self.nodes[node_id].depends_on:
                if color[dep] == GRAY:
                    cycle = " -> ".join(stack + [dep])
                    raise ValueError(f"Cycle detected in DAG: {cycle}")
                if color[dep] == WHITE:
                    visit(dep, stack + [dep])
            color[node_id] = BLACK

        for node_id in self.nodes:
            if color[node_id] == WHITE:
                visit(node_id, [node_id])


def _default_gate_evaluator(gate: Optional[GateFn], node: Node, context: ExecutionContext) -> GateResult:
    if gate is None:
        return GateResult(passed=True)
    return gate(node, context)


async def _default_retry_executor(node: Node, context: ExecutionContext) -> NodeResult:
    node.attempts += 1
    try:
        return await node.run(node, context)
    except Exception as exc:  # noqa: BLE001 - node failures are data, not crashes
        return NodeResult(success=False, error=str(exc))


def _default_approval_manager(node: Node, context: ExecutionContext) -> Awaitable[bool]:
    async def _approved() -> bool:
        return True

    return _approved()


class EventSink:
    """No-op default; observability.event_log.JsonlEventSink replaces this."""

    def emit(self, event_type: str, **fields: Any) -> None:
        pass


@dataclass
class RunResult:
    context: ExecutionContext
    dag: DAG

    @property
    def succeeded(self) -> bool:
        return all(n.status in (NodeStatus.SUCCEEDED,) for n in self.dag.nodes.values())

    def status_summary(self) -> Dict[str, str]:
        return {node_id: node.status.value for node_id, node in self.dag.nodes.items()}


class Scheduler:
    """Runs a DAG to completion, parallelizing independent ready nodes."""

    def __init__(
        self,
        gate_evaluator: Callable[[Optional[GateFn], Node, ExecutionContext], GateResult] = _default_gate_evaluator,
        retry_executor: Callable[[Node, ExecutionContext], Awaitable[NodeResult]] = _default_retry_executor,
        approval_manager: Callable[[Node, ExecutionContext], Awaitable[bool]] = _default_approval_manager,
        event_sink: Optional[EventSink] = None,
    ) -> None:
        self.gate_evaluator = gate_evaluator
        self.retry_executor = retry_executor
        self.approval_manager = approval_manager
        self.event_sink = event_sink or EventSink()

    async def run(self, dag: DAG, context: ExecutionContext) -> RunResult:
        dag.validate()
        context.replan_hook = lambda new_nodes, new_edges, reason: self._apply_replan(
            dag, context, new_nodes, new_edges, reason
        )

        while True:
            ready = self._ready_nodes(dag)
            if not ready:
                self._propagate_blocked(dag)
                break
            self.event_sink.emit("tick_ready", run_id=context.run_id, node_ids=[n.id for n in ready])
            await asyncio.gather(*(self._execute_node(node, dag, context) for node in ready))

        return RunResult(context=context, dag=dag)

    def _ready_nodes(self, dag: DAG) -> List[Node]:
        ready = []
        for node in dag.nodes.values():
            if node.status != NodeStatus.PENDING:
                continue
            deps = [dag.nodes[d] for d in node.depends_on]
            if all(d.status == NodeStatus.SUCCEEDED for d in deps):
                ready.append(node)
        return ready

    def _propagate_blocked(self, dag: DAG) -> None:
        changed = True
        while changed:
            changed = False
            for node in dag.nodes.values():
                if node.status != NodeStatus.PENDING:
                    continue
                deps = [dag.nodes[d] for d in node.depends_on]
                if any(d.status in (NodeStatus.FAILED, NodeStatus.BLOCKED) for d in deps):
                    node.status = NodeStatus.BLOCKED
                    self.event_sink.emit("node_blocked", node_id=node.id, reason="upstream dependency failed/blocked")
                    changed = True

    async def _execute_node(self, node: Node, dag: DAG, context: ExecutionContext) -> None:
        entry = self.gate_evaluator(node.entry_gate, node, context)
        if not entry.passed:
            node.status = NodeStatus.BLOCKED
            self.event_sink.emit("node_blocked", node_id=node.id, reason=entry.reason or "entry gate failed")
            return

        if node.requires_approval:
            approved = await self.approval_manager(node, context)
            if not approved:
                node.status = NodeStatus.BLOCKED
                self.event_sink.emit("node_blocked", node_id=node.id, reason="approval denied")
                return

        node.status = NodeStatus.RUNNING
        self.event_sink.emit("node_started", node_id=node.id)

        result = await self.retry_executor(node, context)
        node.result = result

        if result.success:
            exit_gate = self.gate_evaluator(node.exit_gate, node, context)
            if exit_gate.passed:
                node.status = NodeStatus.SUCCEEDED
                context.set_output(node.id, result.output)
                self.event_sink.emit("node_succeeded", node_id=node.id, used_fallback=result.used_fallback)
            else:
                node.status = NodeStatus.FAILED
                node.result = NodeResult(success=False, error=exit_gate.reason or "exit gate failed")
                self.event_sink.emit("node_failed", node_id=node.id, reason=exit_gate.reason)
                self._maybe_rollback(node, context)
        else:
            node.status = NodeStatus.FAILED
            self.event_sink.emit("node_failed", node_id=node.id, reason=result.error)
            self._maybe_rollback(node, context)

    def _maybe_rollback(self, node: Node, context: ExecutionContext) -> None:
        if node.rollback is not None:
            node.rollback(node, context)
            self.event_sink.emit("node_rolled_back", node_id=node.id)

    def _apply_replan(
        self,
        dag: DAG,
        context: ExecutionContext,
        new_nodes: List[Node],
        new_edges: Dict[str, List[str]],
        reason: str,
    ) -> None:
        for node in new_nodes:
            if node.id not in dag.nodes:
                dag.add_node(node)
        for to_id, from_ids in new_edges.items():
            for from_id in from_ids:
                dag.add_edge(from_id, to_id)
        dag.validate()
        context.record_decision(
            stage="engine",
            summary=f"Replanned DAG: added {[n.id for n in new_nodes]}",
            rationale=reason,
        )
        self.event_sink.emit("dag_replanned", added_nodes=[n.id for n in new_nodes], reason=reason)
