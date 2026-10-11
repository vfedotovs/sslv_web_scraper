#!/usr/bin/env bash
# shellcheck disable=SC2034  # PDV_* return codes are used by the sourcing script
# scripts/lib/post_deploy.sh — trigger a scrape right after deploy and wait for it.
#
# Replaces the old one-liner in deploy-multi-city-ws.sh, which passed the image
# name `curlimages/curl` to `compose run` (it needs a service name) and hid the
# resulting error behind `> /dev/null 2>&1 || true`. Every deploy logged
# "Triggering immediate /run-task" and nothing ran (staging, 2026-10-02).
#
# The HTTP calls run inside the city's ws container (`compose exec -T ws python`),
# which already has Python for its healthcheck: no extra image, and no guessing
# the compose network name. Sourced, not executed.
#
# Usage:
#   source "${SCRIPT_DIR}/scripts/lib/post_deploy.sh"
#   msg=$(post_deploy_verify "$city" docker compose --project-name "$city" ...)
#   rc=$?
#
# Return codes (msg is one line describing the outcome):
#   0   PDV_OK       the triggered run finished with status 'success'
#   10  PDV_SKIPPED  today's run had already succeeded, so ws refused a new one;
#                    this build is first exercised at the next TASK_TIME
#   11  PDV_FAILED   the run finished with status 'failed'
#   12  PDV_TIMEOUT  no answer from ws, or the run still not finished in time
#   other            `compose exec` itself failed (ws not running, etc.)
#
# Tunables (environment):
#   POST_DEPLOY_VERIFY_TIMEOUT   seconds to wait for the run (default 1200).
#                                A fresh volume fetches every ad at
#                                SCRAPE_DELAY_SEC each, so a large city's
#                                first run can need more.
#   POST_DEPLOY_VERIFY_INTERVAL  seconds between /status polls (default 10)

# Guard against double-sourcing.
if [[ -n "${_SSLV_POST_DEPLOY_LIB_LOADED:-}" ]]; then
    return 0
fi
_SSLV_POST_DEPLOY_LIB_LOADED=1

PDV_OK=0
PDV_SKIPPED=10
PDV_FAILED=11
PDV_TIMEOUT=12

# Runs inside the ws container (Python 3.8+, stdlib only).
# argv: city timeout_sec interval_sec
_PDV_PY='
import json, os, sys, time, urllib.error, urllib.request

city, timeout, interval = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
# PDV_BASE_URL is a test seam; inside the container ws listens on :8000.
BASE = os.environ.get("PDV_BASE_URL", "http://localhost:8000")
deadline = time.time() + timeout


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=30) as resp:
        return json.load(resp)


def done(code, msg):
    print(msg)
    sys.exit(code)


# 1. Trigger. Retry until ws answers: it may still be starting up.
run_id, busy, last_err = None, False, ""
while True:
    try:
        body = get("/run-task/" + city)
        run_id = body.get("run_id")
        break
    except urllib.error.HTTPError as exc:
        if exc.code == 409:  # a run is already in progress: wait for that one
            busy = True
            break
        last_err = "HTTP %s" % exc.code
    except Exception as exc:
        last_err = str(exc)
    if time.time() > deadline:
        done(12, "could not trigger /run-task/%s within %ss: %s" % (city, timeout, last_err))
    time.sleep(interval)

if run_id is None and not busy:
    # ws only skips when a run already succeeded today (has_succeeded_today).
    try:
        run = get("/status").get("cities", {}).get(city) or {}
    except Exception:
        run = {}
    done(10, "skipped: run %s already succeeded today at %s, before this deploy; "
             "this build first runs at the next scheduled TASK_TIME"
             % (run.get("run_id", "?"), run.get("finished_at", "?")))

# 2. Wait for the run to finish.
while True:
    run = None
    try:
        run = get("/status").get("cities", {}).get(city)
    except Exception as exc:
        last_err = str(exc)
    if run and (run_id is None or run.get("run_id") == run_id) \
            and run.get("status") != "running":
        summary = ("run %s %s in %ss: new:%s removed:%s listed rows:%s"
                   % (run.get("run_id"), run.get("status"), run.get("duration_seconds"),
                      run.get("new_ads"), run.get("removed_ads"), run.get("listed_table_rows")))
        if run.get("status") == "success":
            done(0, summary)
        done(11, "%s (failed_stage=%s error=%s)"
                 % (summary, run.get("failed_stage"), run.get("error")))
    if time.time() > deadline:
        done(12, "run %s for %s not finished after %ss (last status: %s)"
                 % (run_id if run_id is not None else "in progress", city, timeout,
                    run.get("status") if run else last_err or "unknown"))
    time.sleep(interval)
'

# post_deploy_verify <city> <compose command and project args...>
#
# Example:
#   post_deploy_verify ogre docker compose --project-name ogre --env-file .env.ogre
post_deploy_verify() {
    local city="$1"
    shift
    local timeout="${POST_DEPLOY_VERIFY_TIMEOUT:-1200}"
    local interval="${POST_DEPLOY_VERIFY_INTERVAL:-10}"
    local out rc=0

    out=$("$@" exec -T ws python -c "$_PDV_PY" "$city" "$timeout" "$interval" 2>&1) || rc=$?
    # A failed `compose exec` can print several lines; keep the message to one.
    echo "${out//$'\n'/ | }"
    return "$rc"
}
