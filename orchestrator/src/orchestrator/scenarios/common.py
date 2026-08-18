"""Shared infrastructure the three demo scenarios all need: writing real
files into the target repo, basic git operations, and running the target
app's actual test suite as a real validation step (not a simulated one).
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple


@dataclass
class FileChange:
    relative_path: str
    content: str


def write_files(repo_root: str, changes: List[FileChange]) -> List[str]:
    """Writes each change to repo_root/relative_path, creating parent dirs
    as needed. Returns the list of relative paths written, for use in a
    node's `touches_files` (rollback scope) and policy checks.
    """
    written = []
    for change in changes:
        path = Path(repo_root) / change.relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(change.content)
        written.append(change.relative_path)
    return written


def run_git(repo_root: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo_root, capture_output=True, text=True)


def current_branch(repo_root: str) -> str:
    result = run_git(repo_root, "rev-parse", "--abbrev-ref", "HEAD")
    return result.stdout.strip()


def create_and_checkout_branch(repo_root: str, branch_name: str, base: str = "main") -> None:
    run_git(repo_root, "checkout", base)
    result = run_git(repo_root, "checkout", "-b", branch_name)
    if result.returncode != 0:
        # Branch may already exist from a prior run attempt — reuse it.
        run_git(repo_root, "checkout", branch_name)


def commit_all(repo_root: str, message: str) -> subprocess.CompletedProcess:
    run_git(repo_root, "add", "-A")
    return run_git(repo_root, "commit", "-m", message)


def run_maven_test(repo_root: str, timeout: int = 300) -> Tuple[bool, str]:
    result = subprocess.run(
        ["./mvnw", "-q", "test"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    output = (result.stdout or "") + (result.stderr or "")
    return result.returncode == 0, output
