from orchestrator.engine.policy import (
    PolicyContext,
    PolicyEngine,
    no_destructive_git_without_approval,
    no_secrets_committed,
    no_writes_outside_repo,
    require_tests_for_new_endpoints,
)


def test_no_secrets_committed_flags_hardcoded_key():
    ctx = PolicyContext(file_contents={"app.yml": 'api_key: "sk-abcdef1234567890"'})
    violations = no_secrets_committed(ctx)
    assert len(violations) == 1
    assert violations[0].severity == "CRITICAL"


def test_no_secrets_committed_ignores_clean_file():
    ctx = PolicyContext(file_contents={"App.java": "public class App {}"})
    assert no_secrets_committed(ctx) == []


def test_no_writes_outside_repo_flags_escaping_path():
    ctx = PolicyContext(repo_root="/repo", touches_files=["src/Main.java", "../../etc/passwd"])
    violations = no_writes_outside_repo(ctx)
    assert len(violations) == 1
    assert "etc/passwd" in violations[0].message


def test_no_writes_outside_repo_allows_relative_paths_inside():
    ctx = PolicyContext(repo_root="/repo", touches_files=["src/main/java/App.java"])
    assert no_writes_outside_repo(ctx) == []


def test_require_tests_for_new_endpoints_flags_missing_tests():
    ctx = PolicyContext(new_endpoints=["GET /api/v1/urls/{code}/qrcode"], test_files_created=[])
    violations = require_tests_for_new_endpoints(ctx)
    assert len(violations) == 1
    assert violations[0].severity == "CRITICAL"


def test_require_tests_for_new_endpoints_passes_when_tests_exist():
    ctx = PolicyContext(new_endpoints=["GET /x"], test_files_created=["XControllerTest.java"])
    assert require_tests_for_new_endpoints(ctx) == []


def test_no_destructive_git_without_approval():
    ctx = PolicyContext(git_commands=["git push --force origin main"])
    violations = no_destructive_git_without_approval(ctx)
    assert len(violations) == 1


def test_policy_engine_aggregates_all_rules():
    engine = PolicyEngine.default()
    ctx = PolicyContext(
        file_contents={"a.yml": 'password: "hunter2hunter2"'},
        new_endpoints=["GET /x"],
        test_files_created=[],
    )
    violations = engine.evaluate(ctx)
    rule_names = {v.rule for v in violations}
    assert "no_secrets_committed" in rule_names
    assert "require_tests_for_new_endpoints" in rule_names
    assert PolicyEngine.has_critical(violations)


def test_policy_engine_with_custom_rules_only_runs_those():
    engine = PolicyEngine(rules=[no_secrets_committed])
    ctx = PolicyContext(new_endpoints=["GET /x"], test_files_created=[])
    assert engine.evaluate(ctx) == []
