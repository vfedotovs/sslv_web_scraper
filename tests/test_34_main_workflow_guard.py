"""main.yml must never deploy to production on its own (R-0).

Before release-2.0.0, its Deploy job ran on every push to main: it removed
every container and image on the production host, then started the
single-city stack (make setup/build/up). With multi-city code on main, that
would have replaced production with a one-city deployment. Deploys are now
manual, confirmed, and run `make deploy-prod` on the exact tested commit.
"""
from pathlib import Path

import yaml

WORKFLOW = Path(__file__).parent.parent / ".github" / "workflows" / "main.yml"


def load():
    workflow = yaml.safe_load(WORKFLOW.read_text())
    return workflow, workflow[True]   # PyYAML reads the bare `on:` key as True


def test_deploy_only_runs_when_dispatched_and_confirmed():
    workflow, _ = load()
    condition = workflow["jobs"]["Deploy"]["if"]
    assert "github.event_name == 'workflow_dispatch'" in condition
    assert "inputs.confirm == 'deploy-prod'" in condition


def test_dispatch_asks_for_ref_and_confirmation():
    _, on = load()
    inputs = on["workflow_dispatch"]["inputs"]
    assert inputs["confirm"]["required"] is True and inputs["confirm"]["default"] == ""
    assert "ref" in inputs


def test_deploy_needs_passing_tests_on_the_same_commit():
    workflow, _ = load()
    test, deploy = workflow["jobs"]["Test"], workflow["jobs"]["Deploy"]
    assert deploy["needs"] == "Test"
    assert not any(step.get("continue-on-error") for step in test["steps"])
    checkout = next(s for s in deploy["steps"] if str(s.get("uses", "")).startswith("actions/checkout"))
    assert checkout["with"]["ref"] == "${{ needs.Test.outputs.sha }}"


def test_deploy_uses_the_multi_city_target_not_the_single_city_stack():
    text = WORKFLOW.read_text()
    assert "make deploy-prod" in text
    for removed in ("docker rmi", "xargs docker rm", "make setup", "make build", "make up",
                    "load_secrets.sh"):
        assert removed not in text, removed


def test_tests_run_on_the_release_python():
    workflow, _ = load()
    setup = next(s for s in workflow["jobs"]["Test"]["steps"]
                 if str(s.get("uses", "")).startswith("actions/setup-python"))
    assert setup["with"]["python-version"] == "3.11"


def test_deploys_into_one_fixed_dir_not_a_new_clone_per_run():
    """A new <time>-<sha> folder per deploy left the watchdog and any manual
    `docker compose` pointing at an old copy (fixed on staging the same way)."""
    workflow, _ = load()
    step = next(s for s in workflow["jobs"]["Deploy"]["steps"]
                if s.get("name") == "Deploy all cities to production EC2")
    assert step["env"]["DEPLOY_DIR"] == "${{ vars.PROD_DEPLOY_DIR || 'sslv-prod' }}"
    assert "date -u +%Y%m%d" not in step["run"]
