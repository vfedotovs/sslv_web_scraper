"""The post-deploy trigger must really run the pipeline and report its result.

Regression tests for staging review item B-5 (2026-10-11): deploy-multi-city-ws.sh
ran `compose run --rm --no-deps curlimages/curl ...`. `compose run` takes a
service name, not an image, so the command failed, and `> /dev/null 2>&1 || true`
hid it. Every deploy logged "Triggering immediate /run-task" and nothing ran.

scripts/lib/post_deploy.sh now runs the HTTP calls inside the ws container. Here
a stub `docker` runs that same Python locally against a fake ws server, so
nothing talks to Docker or a real ws.
"""
import json
import os
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent
LIB = REPO / "scripts" / "lib" / "post_deploy.sh"
DEPLOY_SCRIPT = REPO / "deploy-multi-city-ws.sh"

# `docker compose ... exec -T ws python -c CODE ARGS` -> run CODE with local python3.
# Every call is recorded so tests can check the compose invocation.
DOCKER_STUB = """#!/bin/bash
echo "$@" >> "$DOCKER_CALLS"
[[ " $* " == *" up "* ]] && echo "up-env RELEASE_VERSION=${RELEASE_VERSION:-} APP_ENV=${APP_ENV:-}" >> "$DOCKER_CALLS"
[[ "$1 $2" == "compose version" ]] && exit 0
args=("$@")
for i in "${!args[@]}"; do
  if [[ "${args[$i]}" == exec ]]; then
    if [[ -n "${EXEC_FAIL:-}" ]]; then
      printf 'service "ws" is not running\\nsecond line\\n' >&2
      exit 1
    fi
    for j in "${!args[@]}"; do
      [[ "${args[$j]}" == python ]] && exec python3 "${args[@]:$((j+1))}"
    done
  fi
done
exit 0   # compose up -d etc.
"""

AWS_STUB = """#!/bin/bash
case "$1 $2" in
  "s3 cp") printf 'X=1\\n' > "$4"; exit 0 ;;
  "s3 ls") echo "2026/10/11/pg_backup.sql.gz"; exit 0 ;;
esac
exit 0
"""


def run_row(run_id, status, city="ogre"):
    return {"run_id": run_id, "city": city, "status": status,
            "finished_at": "2026-10-11T00:40:52", "duration_seconds": 5,
            "new_ads": 1, "removed_ads": 2, "listed_table_rows": 43,
            "failed_stage": "df_cleaner" if status == "failed" else None,
            "error": "boom" if status == "failed" else None}


class FakeWs:
    """Scripted ws: each endpoint answers from a list; the last answer repeats."""

    def __init__(self, run_task, status):
        self.run_task = list(run_task)   # [(http_code, body), ...]
        self.status = list(status)       # [{city: run_row} or None (-> 503), ...]
        self.calls = []

    @staticmethod
    def _next(seq):
        return seq.pop(0) if len(seq) > 1 else seq[0]

    def handler(self):
        ws = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):  # noqa: A002 - silence request logs
                pass

            def do_GET(self):
                ws.calls.append(self.path)
                if self.path.startswith("/run-task/"):
                    code, body = ws._next(ws.run_task)
                elif self.path == "/status":
                    cities = ws._next(ws.status)
                    code, body = (503, {"detail": "db down"}) if cities is None \
                        else (200, {"status": "ok", "cities": cities})
                else:
                    code, body = 404, {}
                payload = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        return Handler


@pytest.fixture
def stub_host(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("docker", DOCKER_STUB), ("aws", AWS_STUB)):
        path = bin_dir / name
        path.write_text(body)
        path.chmod(0o755)
    env = dict(
        os.environ,
        PATH=f"{bin_dir}:{os.environ['PATH']}",
        DOCKER_CALLS=str(tmp_path / "docker_calls.txt"),
        POST_DEPLOY_VERIFY_INTERVAL="0",
        POST_DEPLOY_VERIFY_TIMEOUT="3",
    )
    return tmp_path, env


@pytest.fixture
def serve():
    servers = []

    def start(fake):
        server = ThreadingHTTPServer(("127.0.0.1", 0), fake.handler())
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return f"http://127.0.0.1:{server.server_address[1]}"

    yield start
    for server in servers:
        server.shutdown()


def verify(stub_host, base_url, city="ogre", **extra_env):
    cwd, env = stub_host
    env = dict(env, PDV_BASE_URL=base_url, **extra_env)
    script = (f'source "{LIB}"; '
              f'post_deploy_verify {city} docker compose --project-name {city} --env-file .env.{city}')
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                          timeout=60, cwd=cwd, env=env)


# --- post_deploy_verify ---

def test_accepted_run_that_succeeds_returns_ok(stub_host, serve):
    fake = FakeWs(run_task=[(200, {"run_id": 23})],
                  status=[{"ogre": run_row(23, "running")}, {"ogre": run_row(23, "success")}])
    result = verify(stub_host, serve(fake))
    assert result.returncode == 0, result.stdout
    assert "run 23 success" in result.stdout
    assert fake.calls[0] == "/run-task/ogre"


def test_runs_inside_the_city_ws_container(stub_host, serve):
    fake = FakeWs(run_task=[(200, {"run_id": 23})], status=[{"ogre": run_row(23, "success")}])
    verify(stub_host, serve(fake))
    call = Path(stub_host[1]["DOCKER_CALLS"]).read_text()
    assert "compose --project-name ogre --env-file .env.ogre exec -T ws python -c" in call


def test_waits_for_its_own_run_not_last_nights(stub_host, serve):
    # /status still shows last night's success until the new run is recorded.
    fake = FakeWs(run_task=[(200, {"run_id": 23})],
                  status=[{"ogre": run_row(22, "success")}, {"ogre": run_row(23, "failed")}])
    result = verify(stub_host, serve(fake))
    assert result.returncode == 11
    assert "run 23 failed" in result.stdout
    assert "failed_stage=df_cleaner" in result.stdout


def test_already_succeeded_today_is_reported_as_skipped(stub_host, serve):
    fake = FakeWs(run_task=[(200, {"message": "Local scraper job already has run"})],
                  status=[{"ogre": run_row(22, "success")}])
    result = verify(stub_host, serve(fake))
    assert result.returncode == 10
    assert "skipped: run 22 already succeeded today" in result.stdout


def test_busy_waits_for_the_run_in_progress(stub_host, serve):
    fake = FakeWs(run_task=[(409, {"detail": "busy"})],
                  status=[{"ogre": run_row(23, "running")}, {"ogre": run_row(23, "success")}])
    result = verify(stub_host, serve(fake))
    assert result.returncode == 0
    assert "run 23 success" in result.stdout


def test_retries_trigger_while_ws_starts_up(stub_host, serve):
    fake = FakeWs(run_task=[(503, {}), (503, {}), (200, {"run_id": 23})],
                  status=[None, {"ogre": run_row(23, "success")}])
    result = verify(stub_host, serve(fake))
    assert result.returncode == 0
    assert fake.calls.count("/run-task/ogre") == 3


def test_ws_never_answers_times_out(stub_host, serve):
    fake = FakeWs(run_task=[(500, {})], status=[None])
    result = verify(stub_host, serve(fake), POST_DEPLOY_VERIFY_TIMEOUT="1")
    assert result.returncode == 12
    assert "could not trigger /run-task/ogre" in result.stdout


def test_run_stuck_in_running_times_out(stub_host, serve):
    fake = FakeWs(run_task=[(200, {"run_id": 23})], status=[{"ogre": run_row(23, "running")}])
    result = verify(stub_host, serve(fake), POST_DEPLOY_VERIFY_TIMEOUT="1")
    assert result.returncode == 12
    assert "not finished after 1s (last status: running)" in result.stdout


def test_exec_failure_is_not_hidden(stub_host, serve):
    result = verify(stub_host, "http://127.0.0.1:1", EXEC_FAIL="1")
    assert result.returncode == 1
    assert result.stdout.strip() == 'service "ws" is not running | second line'


# --- deploy-multi-city-ws.sh wiring ---

@pytest.fixture
def deploy_dir(tmp_path):
    """A copy of the deploy script with its libs and config, so its log file
    lands in tmp_path and not in the repo."""
    root = tmp_path / "deploy"
    (root / "scripts").mkdir(parents=True)
    shutil.copytree(REPO / "scripts" / "lib", root / "scripts" / "lib")
    shutil.copytree(REPO / "config", root / "config")
    shutil.copy(DEPLOY_SCRIPT, root)
    (root / "docker-compose.yml").write_text("services: {}\n")
    (root / "config" / "cities.yaml").write_text(
        "cities:\n  ogre:\n    display_name: Ogre\n  jurmala:\n    display_name: Jurmala\n")
    return root


def deploy(deploy_dir, stub_host, base_url, **extra_env):
    _, env = stub_host
    env = dict(env, PDV_BASE_URL=base_url, CICD_FILES_BUCKET="test-bucket", **extra_env)
    result = subprocess.run(["bash", str(deploy_dir / "deploy-multi-city-ws.sh")],
                            capture_output=True, text=True, timeout=120,
                            cwd=deploy_dir, env=env)
    return result, (deploy_dir / "deploy-multi-city.log").read_text()


def test_deploy_fails_when_post_deploy_run_fails(deploy_dir, stub_host, serve):
    fake = FakeWs(run_task=[(200, {"run_id": 5})],
                  status=[{"ogre": run_row(5, "failed"), "jurmala": run_row(5, "failed", "jurmala")}])
    result, log = deploy(deploy_dir, stub_host, serve(fake))
    assert result.returncode == 1
    assert "[ogre] Post-deploy run FAILED" in log
    assert "Successful:   0" in log
    assert "Failed cities: ogre jurmala" in log


def test_deploy_succeeds_when_runs_succeed_or_already_ran(deploy_dir, stub_host, serve):
    fake = FakeWs(run_task=[(200, {"run_id": 5}), (200, {"message": "already has run"})],
                  status=[{"ogre": run_row(5, "success"),
                           "jurmala": run_row(4, "success", "jurmala")}])
    result, log = deploy(deploy_dir, stub_host, serve(fake))
    assert result.returncode == 0, log
    assert "[ogre] Post-deploy verification OK: run 5 success" in log
    assert "[jurmala] Post-deploy verification skipped: run 4 already succeeded today" in log
    assert "Successful:   2" in log


def test_deploy_can_skip_verification(deploy_dir, stub_host, serve):
    fake = FakeWs(run_task=[(500, {})], status=[None])
    result, log = deploy(deploy_dir, stub_host, serve(fake), POST_DEPLOY_VERIFY="false")
    assert result.returncode == 0
    assert "Post-deploy verification skipped (POST_DEPLOY_VERIFY=false)" in log
    assert fake.calls == []


# --- RELEASE_VERSION / APP_ENV reach compose (R-0: set by main.yml) ---

def up_env_lines(stub_host):
    return [l for l in Path(stub_host[1]["DOCKER_CALLS"]).read_text().splitlines()
            if l.startswith("up-env ")]


def test_deploy_exports_ci_release_version_and_env(deploy_dir, stub_host, serve):
    fake = FakeWs(run_task=[(200, {"message": "already has run"})],
                  status=[{"ogre": run_row(4, "success"), "jurmala": run_row(4, "success", "jurmala")}])
    result, log = deploy(deploy_dir, stub_host, serve(fake),
                         DEPLOY_RELEASE_VERSION="v2.0.1-rc", DEPLOY_APP_ENV="production",
                         RELEASE_VERSION="v1.6.0", APP_ENV="stale")   # stale exports are replaced
    assert result.returncode == 0, log
    assert "Release version: v2.0.1-rc  App env: production" in log
    assert up_env_lines(stub_host) == ["up-env RELEASE_VERSION=v2.0.1-rc APP_ENV=production"] * 2


def test_deploy_without_ci_values_uses_m6_env(deploy_dir, stub_host, serve):
    fake = FakeWs(run_task=[(200, {"message": "already has run"})],
                  status=[{"ogre": run_row(4, "success"), "jurmala": run_row(4, "success", "jurmala")}])
    result, log = deploy(deploy_dir, stub_host, serve(fake), M6_ENV="staging")
    assert result.returncode == 0, log
    # deploy_dir is not a git checkout, so the version is left to the env files
    assert "Release version: <from env files>  App env: staging" in log
    assert up_env_lines(stub_host) == ["up-env RELEASE_VERSION= APP_ENV=staging"] * 2


# --- DEPLOY_CITIES: deploy a subset (C-1, per-city rollout in the cutover runbook) ---

def compose_up_projects(stub_host):
    calls_file = Path(stub_host[1]["DOCKER_CALLS"])
    calls = calls_file.read_text().splitlines() if calls_file.exists() else []   # no docker call at all
    return [c.split("--project-name ")[1].split()[0] for c in calls
            if c.startswith("compose ") and " up " in f" {c} "]


def ran_ok(stub_host, serve):
    return serve(FakeWs(run_task=[(200, {"message": "already has run"})],
                        status=[{"ogre": run_row(4, "success"),
                                 "jurmala": run_row(4, "success", "jurmala")}]))


def test_deploy_cities_deploys_only_those(deploy_dir, stub_host, serve):
    result, log = deploy(deploy_dir, stub_host, ran_ok(stub_host, serve), DEPLOY_CITIES="ogre")
    assert result.returncode == 0, log
    assert compose_up_projects(stub_host) == ["ogre"]
    assert "DEPLOY_CITIES: deploying 1 of 2 cities" in log
    assert "Total cities: 1" in log


def test_deploy_cities_keeps_cities_yaml_order(deploy_dir, stub_host, serve):
    result, log = deploy(deploy_dir, stub_host, ran_ok(stub_host, serve),
                         DEPLOY_CITIES="jurmala, ogre")
    assert result.returncode == 0, log
    assert compose_up_projects(stub_host) == ["ogre", "jurmala"]


@pytest.mark.parametrize("value, message", [
    ("jurmla", "'jurmla' is not in"),           # a typo must not deploy nothing and pass
    ("ogre riga", "'riga' is not in"),
    (" , ", "names no city"),
    ("   ", "names no city"),
])
def test_deploy_cities_refuses_unknown_names(deploy_dir, stub_host, serve, value, message):
    result, log = deploy(deploy_dir, stub_host, ran_ok(stub_host, serve), DEPLOY_CITIES=value)
    assert result.returncode == 1
    assert message in log
    assert compose_up_projects(stub_host) == []


def test_without_deploy_cities_every_city_is_deployed(deploy_dir, stub_host, serve):
    result, log = deploy(deploy_dir, stub_host, ran_ok(stub_host, serve))
    assert result.returncode == 0, log
    assert compose_up_projects(stub_host) == ["ogre", "jurmala"]
    assert "DEPLOY_CITIES" not in log
