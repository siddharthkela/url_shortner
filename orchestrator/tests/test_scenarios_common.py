import subprocess
from pathlib import Path

from orchestrator.engine.context import ExecutionContext
from orchestrator.observability.metrics import compute_metrics
from orchestrator.scenarios.common import (
    FileChange,
    commit_all,
    create_and_checkout_branch,
    current_branch,
    render_run_summary,
    run_git,
    write_files,
)


def _init_repo(repo: Path) -> None:
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=repo, check=True)
    (repo / "README.md").write_text("init\n")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)


def test_write_files_creates_parent_dirs_and_returns_written_paths(tmp_path: Path):
    written = write_files(str(tmp_path), [
        FileChange(relative_path="a/b/c.txt", content="hello"),
        FileChange(relative_path="d.txt", content="world"),
    ])

    assert written == ["a/b/c.txt", "d.txt"]
    assert (tmp_path / "a/b/c.txt").read_text() == "hello"
    assert (tmp_path / "d.txt").read_text() == "world"


def test_current_branch_reports_the_checked_out_branch(tmp_path: Path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    assert current_branch(str(repo)) == "main"


def test_create_and_checkout_branch_creates_new_branch_from_base(tmp_path: Path):
    repo = tmp_path / "repo"
    _init_repo(repo)

    create_and_checkout_branch(str(repo), "feature/demo", base="main")

    assert current_branch(str(repo)) == "feature/demo"


def test_create_and_checkout_branch_reuses_existing_branch_without_erroring(tmp_path: Path):
    repo = tmp_path / "repo"
    _init_repo(repo)

    create_and_checkout_branch(str(repo), "feature/demo", base="main")
    run_git(str(repo), "checkout", "main")
    create_and_checkout_branch(str(repo), "feature/demo", base="main")  # should not fail on second call

    assert current_branch(str(repo)) == "feature/demo"


def test_commit_all_stages_and_commits_working_tree_changes(tmp_path: Path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "new_file.txt").write_text("new content")

    result = commit_all(str(repo), "add new_file")

    assert result.returncode == 0
    log = run_git(str(repo), "log", "--oneline", "-1")
    assert "add new_file" in log.stdout


def test_commit_all_with_no_changes_does_not_raise(tmp_path: Path):
    repo = tmp_path / "repo"
    _init_repo(repo)

    result = commit_all(str(repo), "nothing to commit")  # git exits non-zero; should not raise

    assert result.returncode != 0


def test_render_run_summary_includes_lineage_metrics_and_risks():
    context = ExecutionContext(run_id="sum1")
    context.record_decision(stage="design", summary="Chose token bucket", rationale="simplest correct option")
    metrics = compute_metrics([
        {"event_type": "node_succeeded", "node_id": "a", "timestamp": "2026-01-01T00:00:00+00:00"},
    ])

    markdown = render_run_summary(
        scenario_name="brownfield",
        requirement="Add rate limiting",
        branch_name="orchestrator-demo/brownfield-rate-limit",
        context=context,
        metrics=metrics,
        risks=["Token bucket state is in-memory and resets on restart"],
        assumptions=["Per-owner-token limiting is sufficient; no IP-based limiting"],
        limitations=["No distributed rate limiting across instances"],
    )

    assert "brownfield" in markdown
    assert "Chose token bucket" in markdown
    assert "simplest correct option" in markdown
    assert "Token bucket state is in-memory" in markdown
    assert "Per-owner-token limiting" in markdown
    assert "No distributed rate limiting" in markdown
    assert "100%" in markdown
