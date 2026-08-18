import subprocess
from pathlib import Path

from orchestrator.scenarios.common import (
    FileChange,
    commit_all,
    create_and_checkout_branch,
    current_branch,
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
