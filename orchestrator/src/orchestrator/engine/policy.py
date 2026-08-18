"""Policy guardrails: security, compliance, and change-control checks that
run at a node's exit gate. Each rule inspects a PolicyContext (facts about
what the node did) and returns violations; CRITICAL violations fail the
gate, WARNING violations pass but are recorded for the audit trail.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

# Requires the value to be a *quoted string literal*, not just optionally
# quoted — real hardcoded secrets in config/code look like `api_key: "sk-..."`.
# An unquoted match also fires on ordinary code like `ownerToken =
# UUID.randomUUID()`, since "token" is a substring match (camelCase has no
# regex word boundary between "owner" and "Token") and "UUID.randomUUID"
# alone satisfies the character-class length check — a real false positive
# found by actually running this against real Java test source, not a
# hypothetical.
SECRET_PATTERN = re.compile(
    r"(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*[\"'][A-Za-z0-9/+_\-\.]{8,}[\"']"
)

DESTRUCTIVE_GIT_COMMANDS = {"push --force", "push -f", "reset --hard", "clean -fdx", "branch -D"}


@dataclass
class PolicyContext:
    repo_root: Optional[str] = None
    file_contents: dict = field(default_factory=dict)  # path -> content, for changed/new files only
    touches_files: List[str] = field(default_factory=list)
    git_commands: List[str] = field(default_factory=list)
    new_endpoints: List[str] = field(default_factory=list)
    test_files_created: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class PolicyViolation:
    rule: str
    severity: str  # "CRITICAL" or "WARNING"
    message: str


PolicyRule = Callable[[PolicyContext], List[PolicyViolation]]


def no_secrets_committed(ctx: PolicyContext) -> List[PolicyViolation]:
    violations = []
    for path, content in ctx.file_contents.items():
        for match in SECRET_PATTERN.finditer(content):
            violations.append(PolicyViolation(
                rule="no_secrets_committed",
                severity="CRITICAL",
                message=f"Possible hardcoded secret in {path} near '{match.group(1)}'",
            ))
    return violations


def no_writes_outside_repo(ctx: PolicyContext) -> List[PolicyViolation]:
    if ctx.repo_root is None:
        return []
    root = Path(ctx.repo_root).resolve()
    violations = []
    for f in ctx.touches_files:
        resolved = (root / f).resolve() if not Path(f).is_absolute() else Path(f).resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            violations.append(PolicyViolation(
                rule="no_writes_outside_repo",
                severity="CRITICAL",
                message=f"Node touched a path outside the target repo: {f}",
            ))
    return violations


def require_tests_for_new_endpoints(ctx: PolicyContext) -> List[PolicyViolation]:
    if ctx.new_endpoints and not ctx.test_files_created:
        return [PolicyViolation(
            rule="require_tests_for_new_endpoints",
            severity="CRITICAL",
            message=f"New endpoint(s) {ctx.new_endpoints} introduced with no test files created",
        )]
    return []


def no_destructive_git_without_approval(ctx: PolicyContext) -> List[PolicyViolation]:
    violations = []
    for cmd in ctx.git_commands:
        if any(destructive in cmd for destructive in DESTRUCTIVE_GIT_COMMANDS):
            violations.append(PolicyViolation(
                rule="no_destructive_git_without_approval",
                severity="CRITICAL",
                message=f"Destructive git operation requires an explicit human-approved node: {cmd}",
            ))
    return violations


DEFAULT_RULES: List[PolicyRule] = [
    no_secrets_committed,
    no_writes_outside_repo,
    require_tests_for_new_endpoints,
    no_destructive_git_without_approval,
]


class PolicyEngine:
    def __init__(self, rules: Optional[List[PolicyRule]] = None):
        self.rules = rules if rules is not None else list(DEFAULT_RULES)

    @classmethod
    def default(cls) -> "PolicyEngine":
        return cls()

    def evaluate(self, ctx: PolicyContext) -> List[PolicyViolation]:
        violations: List[PolicyViolation] = []
        for rule in self.rules:
            violations.extend(rule(ctx))
        return violations

    @staticmethod
    def has_critical(violations: List[PolicyViolation]) -> bool:
        return any(v.severity == "CRITICAL" for v in violations)
