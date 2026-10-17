"""staging.yml and main.yml deploy the tested commit into the host's ONE deploy dir.

The old job removed every container and image on the staging host, cloned a
new <time>-deploy folder per run and started the single-city stack. The new
one deploys the tested commit with `make deploy-staging` in a fixed dir, so a
second deployment cannot run next to the first.

The remote script is run here for real against throwaway git repos, with a
stub `make` that records the call.
"""
import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).parent.parent / ".github" / "workflows" / "staging.yml"


def load():
    workflow = yaml.safe_load(WORKFLOW.read_text())
    return workflow, workflow[True]   # PyYAML reads the bare `on:` key as True


# --- structure ---

def test_only_manual_and_confirmed():
    workflow, on = load()
    assert list(on) == ["workflow_dispatch"]
    assert on["workflow_dispatch"]["inputs"]["confirm"]["default"] == ""
    condition = workflow["jobs"]["Deploy"]["if"]
    assert "inputs.confirm == 'deploy-staging'" in condition


def test_deploy_needs_tests_and_image_build():
    workflow, _ = load()
    jobs = workflow["jobs"]
    assert jobs["Deploy"]["needs"] == ["Test", "Build"]
    assert not any(step.get("continue-on-error") for step in jobs["Test"]["steps"])
    build = "\n".join(step.get("run", "") for step in jobs["Build"]["steps"])
    assert "docker compose --profile backup build" in build


def test_no_single_city_steps_left():
    workflow, _ = load()
    runs = "\n".join(step.get("run", "") for job in workflow["jobs"].values()
                     for step in job["steps"])
    text = "\n".join(line for line in runs.splitlines() if not line.strip().startswith("#"))
    assert "make deploy-staging" in text
    for removed in ("docker rmi", "xargs docker rm", "make setup", "make build", "make up",
                    "load_secrets.sh", "-deploy\""):
        assert removed not in text, removed


# --- the remote deploy script of both workflows, run for real ---

WORKFLOWS = Path(__file__).parent.parent / ".github" / "workflows"
# name: (workflow file, deploy step, make target, extra args, what the stub make sees)
TARGETS = {
    "staging": ("staging.yml", "Deploy all cities to staging EC2", "deploy-staging", [],
                "rv= env="),
    "production": ("main.yml", "Deploy all cities to production EC2", "deploy-prod",
                   ["v2.0.1-rc"], "rv=v2.0.1-rc env=production"),
}


def remote_script(workflow_file, step_name):
    workflow = yaml.safe_load((WORKFLOWS / workflow_file).read_text())
    step = next(s for s in workflow["jobs"]["Deploy"]["steps"] if s.get("name") == step_name)
    match = re.search(r"<<'EOF'\n(.*?)\nEOF", step["run"], re.S)
    assert match, "heredoc not found"
    return match.group(1)


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                          text=True).stdout.strip()


@pytest.fixture(params=list(TARGETS))
def host(request, tmp_path):
    """origin repo with branch release-x (2 commits), a deploy-dir clone of it in
    $HOME on the older commit, and a stub make on PATH; once per workflow."""
    origin = tmp_path / "origin"
    origin.mkdir()
    git(origin, "init", "-q", "-b", "release-x")
    git(origin, "config", "user.email", "t@t")
    git(origin, "config", "user.name", "t")
    (origin / "Makefile").write_text("one\n")
    git(origin, "add", ".")
    git(origin, "commit", "-qm", "one")
    first = git(origin, "rev-parse", "HEAD")
    (origin / "Makefile").write_text("two\n")
    git(origin, "commit", "-qam", "two")
    home = tmp_path / "home"
    home.mkdir()
    git(home, "clone", "-q", str(origin), "deploy")
    git(home / "deploy", "checkout", "-q", "--detach", first)    # host is on an older commit
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "make").write_text(
        '#!/bin/bash\necho "make $* @ $(git rev-parse HEAD)'
        ' rv=${DEPLOY_RELEASE_VERSION:-} env=${DEPLOY_APP_ENV:-}" >> "$MAKE_CALLS"\n')
    (bin_dir / "make").chmod(0o755)
    env = {k: v for k, v in os.environ.items()
           if k not in ("DEPLOY_RELEASE_VERSION", "DEPLOY_APP_ENV")}
    env.update(HOME=str(home), PATH=f"{bin_dir}:{os.environ['PATH']}",
               MAKE_CALLS=str(tmp_path / "make_calls.txt"))
    return tmp_path, origin, home / "deploy", env, TARGETS[request.param]


def run_remote(host, ref, sha):
    tmp_path, _, _, env, (workflow_file, step_name, _, extra, _) = host
    result = subprocess.run(["bash", "-s", "--", ref, sha, "deploy", *extra],
                            input=remote_script(workflow_file, step_name),
                            capture_output=True, text=True, timeout=60, env=env)
    calls = tmp_path / "make_calls.txt"
    return result, calls.read_text().splitlines() if calls.exists() else []


def expected_call(host, sha):
    *_, (_, _, target, _, seen) = host
    return f"make {target} @ {sha} {seen}"


def test_deploys_the_tested_branch_tip_and_stays_on_the_branch(host):
    _, origin, deploy, _, _ = host
    tip = git(origin, "rev-parse", "HEAD")
    result, calls = run_remote(host, "release-x", tip)
    assert result.returncode == 0, result.stdout + result.stderr
    assert calls == [expected_call(host, tip)]
    assert git(deploy, "branch", "--show-current") == "release-x"   # git pull keeps working


def test_refuses_when_the_branch_moved_after_the_tests(host):
    _, origin, _, _, _ = host
    tested = git(origin, "rev-parse", "HEAD~1")
    result, calls = run_remote(host, "release-x", tested)
    assert result.returncode != 0
    assert "moved since the tests ran" in result.stderr
    assert calls == []


def test_refuses_to_deploy_over_local_changes(host):
    _, origin, deploy, _, _ = host
    (deploy / "Makefile").write_text("edited on the host\n")
    result, calls = run_remote(host, "release-x", git(origin, "rev-parse", "HEAD"))
    assert result.returncode != 0
    assert "uncommitted changes" in result.stderr
    assert calls == []


def test_a_commit_ref_is_deployed_detached(host):
    _, origin, deploy, _, _ = host
    first = git(origin, "rev-parse", "HEAD~1")
    result, calls = run_remote(host, first, first)
    assert result.returncode == 0, result.stdout + result.stderr
    assert calls == [expected_call(host, first)]
    assert git(deploy, "rev-parse", "HEAD") == first


def test_a_running_deploy_blocks_a_second_one(host):
    """Exactly the process make starts; mentioning the name elsewhere does not block."""
    tmp_path, origin, _, _, _ = host
    fake = tmp_path / "deploy-multi-city-ws.sh"
    fake.write_text("#!/bin/bash\nsleep 30\n")
    fake.chmod(0o755)
    proc = subprocess.Popen(["/bin/bash", "./deploy-multi-city-ws.sh"], cwd=tmp_path)
    try:
        result, calls = run_remote(host, "release-x", git(origin, "rev-parse", "HEAD"))
    finally:
        proc.kill()
    assert result.returncode != 0
    assert "already running" in result.stderr
    assert calls == []
