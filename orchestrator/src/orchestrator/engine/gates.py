"""Reusable entry/exit gate builders that plug into Node.entry_gate/exit_gate.

A gate is just `(node, context) -> GateResult`, so these are small factory
functions rather than a separate class hierarchy — easy to compose with
all_of() and easy to write ad-hoc ones inline for a specific stage.
"""
from __future__ import annotations

from typing import Callable, List

from orchestrator.engine.context import ExecutionContext
from orchestrator.engine.dag import GateFn, GateResult, Node
from orchestrator.engine.policy import PolicyContext, PolicyEngine


def require_outputs(*node_ids: str) -> GateFn:
    def _gate(node: Node, context: ExecutionContext) -> GateResult:
        missing = [n for n in node_ids if context.get_output(n) is None]
        if missing:
            return GateResult(passed=False, reason=f"missing required upstream output(s): {missing}")
        return GateResult(passed=True)

    return _gate


def require_output_keys(*keys: str) -> GateFn:
    """Exit gate: the node's own output (a dict) must contain these keys."""

    def _gate(node: Node, context: ExecutionContext) -> GateResult:
        output = node.result.output if node.result else None
        if not isinstance(output, dict):
            return GateResult(passed=False, reason="node output is not a dict; cannot check required keys")
        missing = [k for k in keys if k not in output]
        if missing:
            return GateResult(passed=False, reason=f"output missing required key(s): {missing}")
        return GateResult(passed=True)

    return _gate


def all_of(*gates: GateFn) -> GateFn:
    def _gate(node: Node, context: ExecutionContext) -> GateResult:
        for gate in gates:
            result = gate(node, context)
            if not result.passed:
                return result
        return GateResult(passed=True)

    return _gate


def policy_exit_gate(
    policy_engine: PolicyEngine,
    context_builder: Callable[[Node, ExecutionContext], PolicyContext],
) -> GateFn:
    """Exit gate that runs the PolicyEngine against facts extracted from the
    node's result. CRITICAL violations fail the gate; WARNINGs pass but are
    attached to the GateResult reason for the audit trail.
    """

    def _gate(node: Node, context: ExecutionContext) -> GateResult:
        ctx = context_builder(node, context)
        violations = policy_engine.evaluate(ctx)
        if PolicyEngine.has_critical(violations):
            messages = "; ".join(f"[{v.severity}] {v.rule}: {v.message}" for v in violations if v.severity == "CRITICAL")
            return GateResult(passed=False, reason=f"policy violation(s): {messages}")
        if violations:
            warnings = "; ".join(f"[{v.severity}] {v.rule}: {v.message}" for v in violations)
            return GateResult(passed=True, reason=f"passed with warnings: {warnings}")
        return GateResult(passed=True)

    return _gate
