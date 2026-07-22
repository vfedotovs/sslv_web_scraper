#!/usr/bin/env bash
#
# collect_logs_v3.sh — multi-city aware log & artifact collector.
#
# Replaces collect_logs_v2.sh, which was written for the single-city era and
# is unusable under the current multi-city deployment (it matches every city's
# containers at once and collects them all into one CWD).
#
# See plan_new_collect_logs_v3.md for the full design and phase breakdown.
#
# IMPLEMENTED: Phase 1 — foundation (CLI, logging, preflight, bundle scaffold).
#              Phase 2 — label-based container discovery + MANIFEST status table.
#              Phase 3 — log file + docker logs collection.
#              Phase 4 — pipeline artifacts + stage hand-off directories.
#              Phase 5 — opt-in debug DB dump.
#              Phase 6 — host + container state capture, incl. env redaction
#                        (the masking half of Phase 7, pulled forward because
#                        inspect.json would otherwise hold every secret).
# PENDING:     Phase 7 (whole-bundle redaction + self-test), Phase 8 (packaging).
#
# The script discovers each city's containers and collects their logs, docker
# logs, pipeline artifacts, host/container state and (opt-in) a debug DB dump
# into a per-city bundle tree. Container env and inspect output are redacted;
# log and artifact CONTENT is not yet scanned (Phase 7), so review a bundle
# before sending it outside the team. The tar.gz lands in Phase 8.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONFIG_FILE="${REPO_ROOT}/config/cities.yaml"

SCRIPT_VERSION="3.0.0-phase6"

# Exit codes (plan item 8.4)
EXIT_OK=0        # everything requested was collected
EXIT_PARTIAL=1   # some cities/services could not be collected
EXIT_FATAL=2     # preflight or usage failure — nothing was collected

# Shared cities.yaml parser (provides parse_cities)
source "${SCRIPT_DIR}/lib/cities.sh"

# --- Logging (plan item 1.2) ------------------------------------------------
# Format matches deploy-multi-city-ws.sh. Tees into the bundle's collect.log
# once the bundle directory exists; before that, console only.
#
# Diagnostics go to STDERR, not stdout. Several collect_* helpers echo a short
# detail string on stdout that the caller captures with $(...); if log() wrote
# there too, any warning raised inside one of them would be swallowed into that
# string and end up in the MANIFEST's COLLECTED column instead of the console.

BUNDLE_LOG=""

log() {
    local level="$1"
    shift
    local timestamp
    timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    local line="[$timestamp] [$level] $*"
    if [[ -n "$BUNDLE_LOG" ]]; then
        echo "$line" | tee -a "$BUNDLE_LOG" >&2
    else
        echo "$line" >&2
    fi
}

log_info() { log "INFO" "$@"; }
log_warn() { log "WARN" "$@"; }
log_error() { log "ERROR" "$@"; }

# --- Defaults ---------------------------------------------------------------
# Defined before usage() so the help text can quote them.

DEFAULT_SINCE="72h"
DEFAULT_OUTPUT_DIR="${REPO_ROOT}/log-bundles"
VALID_SERVICES="ws ts db backup"

REQUESTED_CITIES=()
COLLECT_ALL=false
RUNNING_ONLY=false
SERVICES="ws,ts,db,backup"
SINCE="$DEFAULT_SINCE"
WITH_DB_DUMP=false
WITH_DATA_DIRS=false
REDACT=true
OUTPUT_DIR="$DEFAULT_OUTPUT_DIR"
ARCHIVE=true

# --- Usage (plan item 1.4) --------------------------------------------------

usage() {
    cat << EOF
Usage: $0 [OPTIONS]

Collects logs, artifacts and container state from the multi-city deployment
into a single timestamped bundle, one isolated directory per city.

Options:
  --city CITY          Collect one city (repeatable). Default: all cities.
  --all                Collect every city in config/cities.yaml (default)
  --running-only       Only cities that currently have containers up
  --services LIST      Comma-separated: ws,ts,db,backup (default: all)
  --since DURATION     docker logs time window (default: ${DEFAULT_SINCE})
  --with-db-dump       Include a pg_dump per city (default: off)
  --with-data-dirs     Include /data + /local_lambda_raw_scraped_data
                       (default: off — these grow without bound)
  --no-redact          Skip secret scrubbing (default: redaction ON)
  --output-dir DIR     Destination root (default: ${DEFAULT_OUTPUT_DIR})
  --no-archive         Leave the bundle unpacked, skip the tar.gz
  -h, --help           Show this help

Examples:
  $0                                   # every city, logs only
  $0 --city jurmala --city ogre        # two cities
  $0 --running-only --since 24h        # whatever is up, last 24h
  $0 --city ogre --with-db-dump        # include a debug DB dump

Note: --with-db-dump produces a DEBUG dump only; it is not uploaded to S3.
For real backups use scripts/backup_db_city.sh, and to restore use
scripts/restore_db_city.sh.

Exit codes: ${EXIT_OK}=complete, ${EXIT_PARTIAL}=partial, ${EXIT_FATAL}=fatal (nothing collected)
EOF
}

# --- Helpers ----------------------------------------------------------------

# in_list <needle> <space-separated haystack>
in_list() {
    local needle="$1"
    local item
    for item in $2; do
        [[ "$item" == "$needle" ]] && return 0
    done
    return 1
}

# require_value <flag> <value> — guards flags that take an argument, so that
# "--city --all" fails loudly instead of swallowing the next flag.
require_value() {
    if [[ -z "${2:-}" || "${2:-}" == -* ]]; then
        log_error "Option $1 requires a value"
        usage
        exit "$EXIT_FATAL"
    fi
}

# --- Container discovery (plan items 2.1, 2.2) ------------------------------
#
# Containers are matched on the compose labels, never on a name substring.
# deploy-multi-city-ws.sh runs `compose --project-name <city>`, so
# com.docker.compose.project is the city and com.docker.compose.service is one
# of ws/ts/db/backup. Substring matching on "ws" would hit all six cities at
# once — the root defect of collect_logs_v2.sh (D1/D3).

# find_container <city> <service> — echoes the container name, empty if none.
# Uses `docker ps -a` deliberately: a stopped or crashed container is exactly
# the one whose logs are worth having.
find_container() {
    local city="$1"
    local service="$2"
    docker ps -a \
        --filter "label=com.docker.compose.project=${city}" \
        --filter "label=com.docker.compose.service=${service}" \
        --format '{{.Names}}' 2>/dev/null | head -n1
}

# container_state <container> — running | exited | created | paused | dead | unknown
container_state() {
    docker inspect --format '{{.State.Status}}' "$1" 2>/dev/null || echo "unknown"
}

# discover_running_projects — distinct compose project names with a running
# container. Used to narrow the city list under --running-only (item 2.2).
discover_running_projects() {
    docker ps \
        --filter "label=com.docker.compose.project" \
        --format '{{.Label "com.docker.compose.project"}}' 2>/dev/null \
        | sort -u
}

# --- Secret redaction (plan items 7.1, 7.2 — pulled forward) ----------------
#
# Phase 6 captures `docker inspect`, whose .Config.Env is a verbatim dump of
# every secret in docker-compose.yml: AWS keys, POSTGRES_PASSWORD, the lot.
# Writing that unmasked would produce a bundle that looks shareable and is not,
# so the masking half of Phase 7 lands here with the capture that needs it.
#
# Still pending in Phase 7: applying this across every collected file, the
# .env/database.ini presence-only rule, and the whole-bundle self-test.

SECRET_KEYS="AWS_SECRET_ACCESS_KEY|AWS_ACCESS_KEY_ID|POSTGRES_PASSWORD|DB_PASSWORD|PGPASSWORD|SENDGRID_API_KEY|SENDGRID_API"

# redact_stream — filter for stdin→stdout. A no-op under --no-redact.
# Values are terminated by a quote, comma or whitespace, which covers both the
# JSON of docker inspect and plain KEY=value text.
redact_stream() {
    if [[ "$REDACT" != true ]]; then
        cat
        return 0
    fi
    sed -E \
        -e "s/((${SECRET_KEYS})=)[^\"',[:space:]]*/\1***REDACTED***/g" \
        -e 's/AKIA[0-9A-Z]{16}/***REDACTED-AKID***/g'
}

# --- Log inventory (plan items 3.1, 3.4, 3.5) -------------------------------
#
# Paths verified against the source. src/ws/Dockerfile sets no WORKDIR, so the
# ws logs land in "/"; src/ts/Dockerfile uses /app; the backup service writes
# to /var/log.
#
# The globs end in .log* so RotatingFileHandler's .log.1 … .log.9 rotations
# come along too — v2 collected only the live .log (item 3.2).

WS_LOG_DIR="/"
WS_LOG_GLOB="*.log*"

# Explicit ws log names, used only for the stopped-container fallback below
# (docker cp cannot glob). aws_mailer.log is the one v2 missed while still
# collecting the retired sendgrid_mailer.log (C1); alert_mailer.py writes here
# too. sendgrid_mailer.log is kept as best-effort legacy.
WS_LOGS="ws_main.log web_scraper.log raw_data_report_formatter.log \
dataframe_sanitizer.log dbworker.log analytics.log aws_mailer.log \
s3_file_downloader.log sendgrid_mailer.log"

TS_LOG_DIR="/app"
TS_LOG_GLOB="*.log*"
TS_LOGS="task_scheduler.log"

# The backup service is absent from v2 entirely (C2), yet backup.log is the
# only record of whether the nightly per-city DB backup actually ran.
BACKUP_LOG_DIR="/var/log"
BACKUP_LOG_GLOB="backup.log* cron.log"
BACKUP_LOGS="backup.log cron.log"

# db (postgres) keeps no log files inside the container — everything goes to
# stdout, so it is covered by collect_stdout() alone.

# Cap on docker logs, so one long-running stack cannot balloon the bundle (3.7)
DOCKER_LOG_TAIL=50000

# --- Artifact inventory (plan items 4.1, 4.2) -------------------------------
#
# The pipeline hands data between stages through files in the ws working
# directory ("/", since src/ws/Dockerfile sets no WORKDIR). Since M7 P7 those
# names are city-scoped through city_file() — jurmala-pandas_df.csv, not
# pandas_df.csv — so v2's hardcoded un-prefixed names matched nothing (C3).
#
# Rather than guessing prefixes, the running-container path globs by extension
# in the ws root. One ws container serves exactly one city, so everything there
# belongs to that city; this picks up both the city-scoped and the legacy names
# and keeps working when a new stage file is added.
WS_ARTIFACT_DIR="/"
WS_ARTIFACT_GLOB="*.csv *.txt *.png *.pdf"

# Explicit names for the stopped-container fallback, which cannot glob.
# Mirrors get_data_files_to_remove() in aws_mailer.py and file_remover.py.
# Each of these is tried both city-scoped and bare (4.1).
WS_ARTIFACT_BASES="pandas_df.csv cleaned-sorted-df.csv email_body_txt_m4.txt \
basic_price_stats.txt email_body_add_dates_table.txt discovered-urls.txt \
raw-data-report.txt"

# Never city-scoped by the pipeline.
WS_ARTIFACT_PLAIN="Mailer_report.txt 1_rooms_tmp.txt mrv2.txt \
scraped_and_removed.txt 1-4_rooms.png 1_rooms.png 2_rooms.png test.png"

# Stage hand-off directories. Unbounded growth, so they are opt-in (4.3).
DATA_DIRS="/data /local_lambda_raw_scraped_data"

# ws_artifact_names <city> — space-separated candidate names for docker cp.
ws_artifact_names() {
    local city="$1"
    local n
    for n in $WS_ARTIFACT_BASES; do
        printf '%s-%s %s ' "$city" "$n" "$n"
    done
    printf '%s ' $WS_ARTIFACT_PLAIN
    # Legacy Ogre report name predates city_file() (4.2)
    printf 'Ogre-raw-data-report.txt %s_city_report.pdf' "$city"
}

# --- Artifact + data dir collection (plan items 4.3, 4.4) -------------------

# copy_dir <container> <dir_in_container> <dest_dir>
#   0 = copied, 2 = directory absent/empty, 1 = error
# Streams the whole directory as tar, rather than globbing `ls` output the way
# v2 did — no ARG_MAX ceiling and no dependence on bash (fixes D8).
copy_dir() {
    local container="$1"
    local src="$2"
    local dest="$3"
    local tmp_tar

    tmp_tar="$(mktemp "${TMPDIR:-/tmp}/sslv-collect.XXXXXX")"

    docker exec "$container" sh -c "
        cd '${src}' 2>/dev/null || exit 0
        tar cf - . 2>/dev/null
    " > "$tmp_tar" 2>/dev/null || true

    if [[ ! -s "$tmp_tar" ]]; then
        rm -f "$tmp_tar"
        return 2
    fi

    mkdir -p "$dest"
    if ! tar xf "$tmp_tar" -C "$dest" 2>/dev/null; then
        rm -f "$tmp_tar"
        return 1
    fi

    rm -f "$tmp_tar"
    return 0
}

# list_dir <container> <dir_in_container> <out_file>
# Cheap alternative to copying a data dir: file count, size and listing. Enough
# to diagnose "no input file found" without hauling the contents along (4.4).
list_dir() {
    local container="$1"
    local src="$2"
    local out="$3"

    docker exec "$container" sh -c "
        d='${src}'
        if [ -d \"\$d\" ]; then
            echo \"# \$d\"
            echo \"# files: \$(find \"\$d\" -type f 2>/dev/null | wc -l | tr -d ' ')\"
            echo \"# size:  \$(du -sh \"\$d\" 2>/dev/null | cut -f1)\"
            echo
            ls -la \"\$d\"
        else
            echo \"# \$d - not present in container\"
        fi
    " > "$out" 2>/dev/null || return 1
    return 0
}

# collect_artifacts <city> <container> <state> <dest_dir>
# Echoes a detail string for the MANIFEST; returns 1 on error.
collect_artifacts() {
    local city="$1"
    local container="$2"
    local state="$3"
    local dest="$4"
    local rc=0 names

    if [[ "$state" == "running" ]]; then
        copy_glob_files "$container" "$WS_ARTIFACT_DIR" "$WS_ARTIFACT_GLOB" \
            "${dest}/artifacts" || rc=$?
    else
        names="$(ws_artifact_names "$city")"
        copy_named_files "$container" "$WS_ARTIFACT_DIR" "$names" \
            "${dest}/artifacts" || rc=$?
    fi

    case "$rc" in
        0) echo "artifacts=$(count_files "${dest}/artifacts")" ;;
        2) echo "artifacts=0" ;;
        *) echo "artifacts=ERROR"; return 1 ;;
    esac
    return 0
}

# --- Host + container state (plan items 6.1-6.6) ----------------------------

# collect_host_state <dest_dir> — host-wide facts, captured once per run.
collect_host_state() {
    local dest="$1"
    mkdir -p "$dest"

    docker ps -a > "${dest}/docker-ps.txt" 2>&1 || true
    docker images > "${dest}/docker-images.txt" 2>&1 || true
    docker system df -v > "${dest}/docker-system-df.txt" 2>&1 || true
    $COMPOSE_CMD ls --all > "${dest}/docker-compose-ls.txt" 2>&1 || true
    df -h > "${dest}/df-h.txt" 2>&1 || true

    {
        uname -a
        echo
        echo "# docker"
        docker version 2>&1 || true
        echo
        echo "# compose"
        $COMPOSE_CMD version 2>&1 || true
    } > "${dest}/uname.txt" 2>&1 || true

    # The deploy log is the first thing to read when a city never came up (6.2).
    local f
    for f in deploy-multi-city.log undeploy-multi-city.log; do
        if [[ -f "${REPO_ROOT}/${f}" ]]; then
            redact_stream < "${REPO_ROOT}/${f}" > "${dest}/${f}" 2>/dev/null || true
        fi
    done

    # Presence only — never the contents (7.3). Knowing whether .env.<city>
    # exists and when it changed is usually the whole question.
    {
        echo "# Secret files on the host — presence and mtime only, never contents."
        for f in "${REPO_ROOT}"/.env.* "${REPO_ROOT}"/database.ini; do
            [[ -e "$f" ]] || continue
            printf '%s  %s\n' \
                "$(date -u -r "$f" '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || echo '?')" \
                "$(basename "$f")"
        done
    } > "${dest}/secret-files.txt" 2>/dev/null || true
}

# collect_container_state <container> <dest_dir> — inspect, health, config.
collect_container_state() {
    local container="$1"
    local dest="$2"

    # .Config.Env carries every compose secret, hence redact_stream (6.3, 7.2).
    docker inspect "$container" 2>/dev/null \
        | redact_stream > "${dest}/inspect.json" || return 1

    # Health-check failure history is the fastest route to "why is ws
    # unhealthy". Renders as "null" when the service defines no healthcheck.
    docker inspect --format '{{json .State.Health}}' "$container" \
        > "${dest}/health.json" 2>/dev/null || echo 'null' > "${dest}/health.json"

    # Image digest + RELEASE_VERSION correlate a bug with a deployed build
    # (6.4); the SCRAPE_*/TASK_TIME values are the usual behaviour suspects
    # (6.5). Dumping the whole env through the redactor beats an allowlist —
    # it cannot silently miss a variable that was added later.
    {
        echo "# container:     ${container}"
        docker inspect --format '# image:         {{.Config.Image}}' "$container"
        docker inspect --format '# image_id:      {{.Image}}' "$container"
        docker inspect --format '# created:       {{.Created}}' "$container"
        docker inspect --format '# started_at:    {{.State.StartedAt}}' "$container"
        docker inspect --format '# restart_count: {{.RestartCount}}' "$container"
        echo
        echo "# environment (secrets redacted)"
        docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$container"
    } 2>/dev/null | redact_stream > "${dest}/config.txt" || true

    return 0
}

# probe_ws_status <container> <dest_dir> — GET /status from inside the network.
#
# The plan suggested a throwaway curlimages/curl container via compose run.
# Exec'ing the ws container's own Python is better: no image pull, no need for
# the compose file or per-city .env on this host, and it is exactly what the
# healthcheck in docker-compose.yml already does.
probe_ws_status() {
    local container="$1"
    local dest="$2"

    docker exec "$container" python -c "
import urllib.request
print(urllib.request.urlopen('http://localhost:8000/status', timeout=10).read().decode())
" > "${dest}/status.json" 2>/dev/null && [[ -s "${dest}/status.json" ]] && return 0

    rm -f "${dest}/status.json"
    return 1
}

# --- DB dump (plan items 5.1-5.5) -------------------------------------------

# Below this many compressed bytes the dump is almost certainly an empty
# database rather than real data — same spirit as MIN_BACKUP_SIZE_KB in
# src/backup-svc/backup.py.
MIN_DUMP_BYTES=1024

# collect_db_dump <city> <container> <state> <dest_dir>
# Echoes a detail string for the MANIFEST; returns 1 on error.
#
# This is a DEBUG dump: it never goes to S3 and is not a backup. The real
# nightly backup is src/backup-svc + scripts/backup_db_city.sh (5.5).
collect_db_dump() {
    local city="$1"
    local container="$2"
    local state="$3"
    local dest="$4"
    local ts out err size

    # Opt-in only: dumping six databases on every log collection would be slow,
    # huge, and a data-exfil footgun for a tool that says "collect logs" (5.1).
    if [[ "$WITH_DB_DUMP" != true ]]; then
        echo "db-dump=off"
        return 0
    fi

    if [[ "$state" != "running" ]]; then
        log_warn "  [$city/db] skipping pg_dump — container is ${state}"
        echo "db-dump=skipped (container ${state})"
        return 0
    fi

    ts="$(date -u '+%Y-%m-%dT%H%M%SZ')"     # no colons — see D6
    out="${dest}/pg_backup_${city}_${ts}.sql.gz"
    err="$(mktemp "${TMPDIR:-/tmp}/sslv-collect.XXXXXX")"
    mkdir -p "$dest"

    # No -t. A TTY turns every \n into \r\n inside the SQL stream, producing a
    # dump that silently fails to restore (D5) — v2's bug.
    #
    # Credentials are expanded by the shell *inside* the container, reading the
    # env postgres already has, so the password never reaches this process,
    # this script's argv, or the logs.
    if docker exec "$container" sh -c '
        PGPASSWORD="$POSTGRES_PASSWORD" exec pg_dump \
            -U "${POSTGRES_USER:-new_docker_user}" \
            -d "${POSTGRES_DB:-new_docker_db}"
    ' 2>"$err" | gzip -9 > "$out"; then
        :
    else
        log_warn "  [$city/db] pg_dump failed: $(head -n1 "$err" 2>/dev/null)"
        # Keep the error text in the bundle — it is the diagnosis.
        mv "$err" "${dest}/pg_dump-error.txt" 2>/dev/null || rm -f "$err"
        rm -f "$out"
        echo "db-dump=ERROR"
        return 1
    fi
    rm -f "$err"

    if ! gzip -t "$out" 2>/dev/null; then
        log_warn "  [$city/db] dump failed gzip integrity check — discarding"
        rm -f "$out"
        echo "db-dump=ERROR (corrupt)"
        return 1
    fi

    size=$(wc -c < "$out" | tr -d ' ')
    if [[ "$size" -lt "$MIN_DUMP_BYTES" ]]; then
        log_warn "  [$city/db] dump is only ${size} bytes — empty database?"
        echo "db-dump=$(du -h "$out" | awk '{print $1}') (SUSPICIOUSLY SMALL)"
        return 0
    fi

    echo "db-dump=$(du -h "$out" | awk '{print $1}')"
    return 0
}

# collect_data_dirs <container> <state> <dest_dir>
# Copies /data and /local_lambda_raw_scraped_data under --with-data-dirs,
# otherwise records only a listing of each.
collect_data_dirs() {
    local container="$1"
    local state="$2"
    local dest="$3"
    local dir base rc copied=0

    # Both paths need docker exec, so a stopped container can offer neither.
    if [[ "$state" != "running" ]]; then
        echo "data-dirs=skipped (container ${state})"
        return 0
    fi

    for dir in $DATA_DIRS; do
        base="$(basename "$dir")"

        if [[ "$WITH_DATA_DIRS" == true ]]; then
            rc=0
            copy_dir "$container" "$dir" "${dest}/data-dirs/${base}" || rc=$?
            [[ "$rc" -eq 0 ]] && copied=$((copied + 1))
        else
            mkdir -p "${dest}/listings"
            list_dir "$container" "$dir" "${dest}/listings/${base}.txt" || true
        fi
    done

    if [[ "$WITH_DATA_DIRS" == true ]]; then
        echo "data-dirs=$(count_files "${dest}/data-dirs") files"
    else
        echo "data-dirs=listed only (--with-data-dirs to copy)"
    fi
    return 0
}

# --- Log collection (plan items 3.2, 3.3, 3.6) ------------------------------

# collect_stdout <container> <dest_dir> — docker logs to stdout.log.
# This is the ONLY place uvicorn tracebacks, container crash output and
# Postgres startup errors appear; none of it is ever written to a file inside
# the container (C5). Works on stopped containers too.
collect_stdout() {
    local container="$1"
    local dest="$2"
    # Container stderr and stdout are interleaved into one file, as emitted.
    if docker logs --since "$SINCE" --timestamps --tail "$DOCKER_LOG_TAIL" \
        "$container" > "${dest}/stdout.log" 2>&1; then
        return 0
    fi
    return 1
}

# copy_glob_files <container> <dir_in_container> <glob> <dest_dir>
#   0 = files collected, 2 = nothing matched, 1 = error
#
# One streamed tar per service rather than v2's per-file `docker cp` loop:
# a single exec, globs handled container-side, and missing files cause no
# noise (item 3.3, fixes D8).
#
# The container-side program is POSIX sh, never bash — python:3.8-slim-buster
# and the postgres images are not guaranteed to have bash. It filters the glob
# down to entries that actually exist, so a partial match (e.g. backup.log
# present but cron.log absent) still produces a valid archive.
copy_glob_files() {
    local container="$1"
    local src_dir="$2"
    local glob="$3"
    local dest="$4"
    local tmp_tar rc=0

    tmp_tar="$(mktemp "${TMPDIR:-/tmp}/sslv-collect.XXXXXX")"

    docker exec "$container" sh -c "
        cd '${src_dir}' 2>/dev/null || exit 0
        list=''
        for f in ${glob}; do
            [ -e \"\$f\" ] && list=\"\$list \$f\"
        done
        [ -n \"\$list\" ] || exit 0
        tar cf - \$list 2>/dev/null
    " > "$tmp_tar" 2>/dev/null || rc=$?

    # Decide on the archive itself rather than the exit status: tar can warn
    # about a vanished file mid-stream yet still produce a usable archive.
    if [[ ! -s "$tmp_tar" ]]; then
        rm -f "$tmp_tar"
        return 2
    fi

    mkdir -p "$dest"
    if ! tar xf "$tmp_tar" -C "$dest" 2>/dev/null; then
        rm -f "$tmp_tar"
        return 1
    fi

    rm -f "$tmp_tar"
    return 0
}

# copy_named_files <container> <dir_in_container> <names> <dest_dir>
#   0 = files collected, 2 = nothing matched, 1 = error
#
# docker exec needs a running container, but docker cp does not. For an exited
# or crashed container — exactly the case `docker ps -a` was used for in
# Phase 2 — fall back to copying the known log names one by one. Rotations
# cannot be recovered this way, since docker cp has no globbing.
copy_named_files() {
    local container="$1"
    local src_dir="$2"
    local names="$3"
    local dest="$4"
    local name copied=0

    mkdir -p "$dest"
    for name in $names; do
        if docker cp "${container}:${src_dir%/}/${name}" "${dest}/${name}" \
            >/dev/null 2>&1; then
            copied=$((copied + 1))
        fi
    done

    [[ $copied -eq 0 ]] && return 2
    return 0
}

# count_files <dir> — number of regular files collected under dir
count_files() {
    [[ -d "$1" ]] || { echo 0; return 0; }
    find "$1" -type f | wc -l | tr -d ' '
}

# collect_service_logs <service> <container> <state> <dest_dir>
# Routes a service to its log directory/glob and picks the running vs stopped
# strategy. Echoes a short detail string for the MANIFEST; returns 1 on error.
collect_service_logs() {
    local service="$1"
    local container="$2"
    local state="$3"
    local dest="$4"
    local log_dir glob names rc detail

    case "$service" in
        ws)     log_dir="$WS_LOG_DIR";     glob="$WS_LOG_GLOB";     names="$WS_LOGS" ;;
        ts)     log_dir="$TS_LOG_DIR";     glob="$TS_LOG_GLOB";     names="$TS_LOGS" ;;
        backup) log_dir="$BACKUP_LOG_DIR"; glob="$BACKUP_LOG_GLOB"; names="$BACKUP_LOGS" ;;
        db)     echo "stdout only (postgres logs to stdout)"; return 0 ;;
        *)      echo "no log inventory"; return 0 ;;
    esac

    rc=0
    if [[ "$state" == "running" ]]; then
        copy_glob_files "$container" "$log_dir" "$glob" "${dest}/logs" || rc=$?
    else
        copy_named_files "$container" "$log_dir" "$names" "${dest}/logs" || rc=$?
    fi

    case "$rc" in
        0)
            detail="logs=$(count_files "${dest}/logs")"
            [[ "$state" != "running" ]] && detail="${detail} (no rotations: container ${state})"
            echo "$detail"
            return 0
            ;;
        2)
            echo "logs=0 (none present)"
            return 0
            ;;
        *)
            echo "logs=ERROR"
            return 1
            ;;
    esac
}

# --- Argument parsing (plan item 1.4) ---------------------------------------

while [[ $# -gt 0 ]]; do
    case "$1" in
        --city)
            require_value "$1" "${2:-}"
            REQUESTED_CITIES+=("$2")
            shift 2
            ;;
        --all)
            COLLECT_ALL=true
            shift
            ;;
        --running-only)
            RUNNING_ONLY=true
            shift
            ;;
        --services)
            require_value "$1" "${2:-}"
            SERVICES="$2"
            shift 2
            ;;
        --since)
            require_value "$1" "${2:-}"
            SINCE="$2"
            shift 2
            ;;
        --with-db-dump)
            WITH_DB_DUMP=true
            shift
            ;;
        --with-data-dirs)
            WITH_DATA_DIRS=true
            shift
            ;;
        --no-redact)
            REDACT=false
            shift
            ;;
        --output-dir)
            require_value "$1" "${2:-}"
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --no-archive)
            ARCHIVE=false
            shift
            ;;
        -h|--help)
            usage
            exit "$EXIT_OK"
            ;;
        *)
            log_error "Unknown option: $1"
            usage
            exit "$EXIT_FATAL"
            ;;
    esac
done

# --- Argument validation ----------------------------------------------------

if [[ "$COLLECT_ALL" == true && ${#REQUESTED_CITIES[@]} -gt 0 ]]; then
    log_error "--all and --city are mutually exclusive"
    exit "$EXIT_FATAL"
fi

# Validate --services against the known compose service names.
# Commas to spaces, then rely on default IFS word splitting (bash 3.2 safe).
SERVICE_LIST=()
for svc in ${SERVICES//,/ }; do
    if ! in_list "$svc" "$VALID_SERVICES"; then
        log_error "Unknown service '$svc' (valid: ${VALID_SERVICES// /, })"
        exit "$EXIT_FATAL"
    fi
    in_list "$svc" "${SERVICE_LIST[*]:-}" || SERVICE_LIST+=("$svc")
done

if [[ ${#SERVICE_LIST[@]} -eq 0 ]]; then
    log_error "--services resolved to an empty list"
    exit "$EXIT_FATAL"
fi

if [[ -z "$SINCE" ]]; then
    log_error "--since must not be empty"
    exit "$EXIT_FATAL"
fi

if [[ "$REDACT" == false ]]; then
    log_warn "==================================================================="
    log_warn "REDACTION DISABLED — the bundle will contain AWS keys and DB"
    log_warn "passwords in plaintext. Do not attach it to a ticket or share it."
    log_warn "==================================================================="
fi

# --- Preflight (plan item 1.6) ----------------------------------------------

if ! command -v docker >/dev/null 2>&1; then
    log_error "docker not found in PATH"
    exit "$EXIT_FATAL"
fi

if ! docker info >/dev/null 2>&1; then
    log_error "Cannot talk to the Docker daemon (is it running? do you have permission?)"
    exit "$EXIT_FATAL"
fi

if [[ ! -f "$CONFIG_FILE" ]]; then
    log_error "Cities configuration file not found: $CONFIG_FILE"
    exit "$EXIT_FATAL"
fi

# Detect docker compose command (plan item 1.5, mirrors deploy-multi-city-ws.sh)
if docker compose version >/dev/null 2>&1; then
    COMPOSE_CMD="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE_CMD="docker-compose"
else
    log_error "Neither 'docker compose' nor 'docker-compose' found"
    exit "$EXIT_FATAL"
fi

if ! mkdir -p "$OUTPUT_DIR" 2>/dev/null; then
    log_error "Cannot create output directory: $OUTPUT_DIR"
    exit "$EXIT_FATAL"
fi

if [[ ! -w "$OUTPUT_DIR" ]]; then
    log_error "Output directory is not writable: $OUTPUT_DIR"
    exit "$EXIT_FATAL"
fi

# --- Resolve the city list --------------------------------------------------

ALL_CITIES=()
while IFS= read -r _city; do
    [[ -n "$_city" ]] && ALL_CITIES+=("$_city")
done < <(parse_cities "$CONFIG_FILE")

if [[ ${#ALL_CITIES[@]} -eq 0 ]]; then
    log_error "No cities found in $CONFIG_FILE"
    exit "$EXIT_FATAL"
fi

CITIES=()
if [[ ${#REQUESTED_CITIES[@]} -eq 0 ]]; then
    CITIES=("${ALL_CITIES[@]}")
else
    for _city in "${REQUESTED_CITIES[@]}"; do
        if ! in_list "$_city" "${ALL_CITIES[*]}"; then
            log_error "Unknown city '$_city' (known: ${ALL_CITIES[*]})"
            exit "$EXIT_FATAL"
        fi
        # De-duplicate repeated --city flags.
        if ! in_list "$_city" "${CITIES[*]:-}"; then
            CITIES+=("$_city")
        fi
    done
fi

# --running-only: keep just the cities that currently have something up
# (plan item 2.2). Applied after validation so a typo still errors out.
if [[ "$RUNNING_ONLY" == true ]]; then
    RUNNING_PROJECTS="$(discover_running_projects | tr '\n' ' ')"
    log_info "Running compose projects: ${RUNNING_PROJECTS:-<none>}"

    _filtered=()
    for _city in "${CITIES[@]}"; do
        if in_list "$_city" "$RUNNING_PROJECTS"; then
            _filtered+=("$_city")
        else
            log_info "Skipping $_city — no running containers (--running-only)"
        fi
    done

    if [[ ${#_filtered[@]} -eq 0 ]]; then
        log_error "--running-only: none of the requested cities have running containers"
        log_error "Requested: ${CITIES[*]}"
        exit "$EXIT_FATAL"
    fi
    CITIES=("${_filtered[@]}")
fi

# --- Bundle scaffold --------------------------------------------------------

TIMESTAMP="$(date -u '+%Y-%m-%dT%H-%M-%SZ')"
BUNDLE_NAME="sslv-logs-${TIMESTAMP}"
BUNDLE_DIR="${OUTPUT_DIR}/${BUNDLE_NAME}"

mkdir -p "${BUNDLE_DIR}/host" "${BUNDLE_DIR}/cities"

# From here on, log() also tees into the bundle.
BUNDLE_LOG="${BUNDLE_DIR}/collect.log"

log_info "collect_logs_v3.sh ${SCRIPT_VERSION} starting"
log_info "Bundle: ${BUNDLE_DIR}"
log_info "Compose command: ${COMPOSE_CMD}"
log_info "Cities (${#CITIES[@]}): ${CITIES[*]}"
log_info "Services: ${SERVICE_LIST[*]}"
log_info "Options: since=${SINCE} running_only=${RUNNING_ONLY} db_dump=${WITH_DB_DUMP} data_dirs=${WITH_DATA_DIRS} redact=${REDACT} archive=${ARCHIVE}"

# Discovery results, one TSV row per (city, service). Kept on disk rather than
# in an associative array so this stays bash 3.2 (macOS) compatible, and so
# later phases can append to the same record.
STATUS_FILE="${BUNDLE_DIR}/.status.tsv"
: > "$STATUS_FILE"

# record_status <city> <service> <state> [container] [detail]
record_status() {
    printf '%s\t%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "${4:--}" "${5:-}" >> "$STATUS_FILE"
}

# --- Per-city collection (plan items 2.3, 2.4, 2.5) -------------------------

# collect_city <city> — discovers this city's containers and lays out its
# output tree. Never aborts the run: the caller treats a non-zero return as
# "this city had trouble", and every other city still gets collected (D4).
collect_city() {
    local city="$1"
    local city_dir="${BUNDLE_DIR}/cities/${city}"
    local found=0 failures=0
    local svc container state svc_dir detail stdout_note art_note data_note dump_note

    for svc in "${SERVICE_LIST[@]}"; do
        container="$(find_container "$city" "$svc")"

        if [[ -z "$container" ]]; then
            # Not deployed on this host — a normal state, not an error (2.3).
            record_status "$city" "$svc" "absent" "-" "not deployed"
            continue
        fi

        state="$(container_state "$container")"
        found=$((found + 1))

        # Per-city, per-service directory — no two cities can ever share an
        # output path, whatever their container names are (2.4, fixes D2).
        svc_dir="${city_dir}/${svc}"
        mkdir -p "$svc_dir"

        # stdout/stderr first: it works even on a crashed container (3.6)
        stdout_note="stdout=ok"
        if ! collect_stdout "$container" "$svc_dir"; then
            stdout_note="stdout=ERROR"
            failures=$((failures + 1))
        fi

        # inspect / health / config — also works on a crashed container (6.3-6.5)
        if ! collect_container_state "$container" "$svc_dir"; then
            log_warn "  [$city/$svc] could not capture container state"
            failures=$((failures + 1))
        fi

        # then the on-disk log files (3.1-3.5)
        if ! detail="$(collect_service_logs "$svc" "$container" "$state" "$svc_dir")"; then
            failures=$((failures + 1))
        fi

        # pipeline artifacts + stage hand-off dirs live only in ws (4.1-4.4)
        if [[ "$svc" == "ws" ]]; then
            if ! art_note="$(collect_artifacts "$city" "$container" "$state" "$svc_dir")"; then
                failures=$((failures + 1))
            fi
            data_note="$(collect_data_dirs "$container" "$state" "$svc_dir")"
            detail="${detail}, ${art_note}, ${data_note}"

            # live /status probe — best effort, never a failure (6.6)
            if [[ "$state" == "running" ]]; then
                if probe_ws_status "$container" "$svc_dir"; then
                    detail="${detail}, status=ok"
                else
                    detail="${detail}, status=unreachable"
                fi
            fi
        fi

        # opt-in debug DB dump (5.1-5.4)
        if [[ "$svc" == "db" ]]; then
            if ! dump_note="$(collect_db_dump "$city" "$container" "$state" "$svc_dir")"; then
                failures=$((failures + 1))
            fi
            detail="${detail}, ${dump_note}"
        fi

        record_status "$city" "$svc" "$state" "$container" "${detail}, ${stdout_note}"
        log_info "  [$city/$svc] $container ($state) — ${detail}, ${stdout_note}"
    done

    if [[ $found -eq 0 ]]; then
        log_warn "  [$city] no containers found — city not deployed on this host"
        return 0
    fi

    log_info "  [$city] $found container(s), $(count_files "$city_dir") file(s) collected"
    [[ $failures -gt 0 ]] && return 1
    return 0
}

log_info "Capturing host state ..."
collect_host_state "${BUNDLE_DIR}/host"
log_info "  host: $(count_files "${BUNDLE_DIR}/host") file(s)"

DISCOVERED_CITIES=0
TROUBLED_CITIES=()

for _city in "${CITIES[@]}"; do
    log_info "Discovering containers for $_city ..."
    # Failure isolation (2.5): one broken city must never abort the run.
    if collect_city "$_city"; then
        DISCOVERED_CITIES=$((DISCOVERED_CITIES + 1))
    else
        log_warn "Collection failed for $_city — continuing with the remaining cities"
        TROUBLED_CITIES+=("$_city")
    fi
done

# --- MANIFEST (discovery section; completed in Phase 8.1) -------------------

MANIFEST="${BUNDLE_DIR}/MANIFEST.txt"
{
    echo "SS.LV multi-city log bundle"
    echo "=========================================================="
    echo "Generated : $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
    echo "Host      : $(hostname)"
    echo "Script    : collect_logs_v3.sh ${SCRIPT_VERSION}"
    echo "Bundle    : ${BUNDLE_NAME}"
    if [[ "$REDACT" == true ]]; then
        echo "Redaction : ON for container env / inspect.json / deploy logs."
        echo "            Masked: ${SECRET_KEYS//|/, } and AKIA* key ids."
        echo "            NOT YET whole-bundle (Phase 7): log and artifact"
        echo "            content is passed through as-is, so review before"
        echo "            sharing outside the team."
    else
        echo "Redaction : *** DISABLED by --no-redact *** — this bundle"
        echo "            contains AWS keys and DB passwords in plaintext."
    fi
    echo
    echo "Options   : since=${SINCE} running_only=${RUNNING_ONLY}"
    echo "            db_dump=${WITH_DB_DUMP} data_dirs=${WITH_DATA_DIRS}"
    echo "            archive=${ARCHIVE} services=${SERVICE_LIST[*]}"
    echo
    echo "Container discovery"
    echo "----------------------------------------------------------"
    echo "Matched on compose labels com.docker.compose.project=<city>"
    echo "and com.docker.compose.service=<service>. 'absent' means the"
    echo "city/service is not deployed on this host — not an error."
    echo
    printf '%-14s %-8s %-10s %-18s %s\n' "CITY" "SERVICE" "STATE" "CONTAINER" "COLLECTED"
    printf '%-14s %-8s %-10s %-18s %s\n' "----" "-------" "-----" "---------" "---------"
    while IFS=$'\t' read -r m_city m_svc m_state m_container m_detail; do
        printf '%-14s %-8s %-10s %-18s %s\n' \
            "$m_city" "$m_svc" "$m_state" "$m_container" "$m_detail"
    done < "$STATUS_FILE"
    echo
    echo "Log sources"
    echo "----------------------------------------------------------"
    echo "  ws     ${WS_LOG_DIR}${WS_LOG_GLOB} (incl. .log.1-.9 rotations)"
    echo "  ts     ${TS_LOG_DIR}/${TS_LOG_GLOB}"
    echo "  backup ${BACKUP_LOG_DIR}/{backup.log*,cron.log}"
    echo "  db     stdout only (postgres does not log to a file)"
    echo "  all    stdout.log = docker logs --since ${SINCE} --tail ${DOCKER_LOG_TAIL}"
    echo
    echo "Stopped containers fall back to docker cp of the known log names;"
    echo "rotations cannot be recovered from a container that is not running."
    echo
    echo "Artifact sources (ws only)"
    echo "----------------------------------------------------------"
    echo "  artifacts/  ${WS_ARTIFACT_DIR}{${WS_ARTIFACT_GLOB// /,}}"
    echo "              City-scoped via city_file() since M7 P7, e.g."
    echo "              <city>-pandas_df.csv. Legacy bare names also taken."
    if [[ "$WITH_DATA_DIRS" == true ]]; then
        echo "  data-dirs/  ${DATA_DIRS// /, } (copied: --with-data-dirs)"
    else
        echo "  listings/   ${DATA_DIRS// /, } (listing only;"
        echo "              re-run with --with-data-dirs to copy the contents)"
    fi
    echo
    echo "Database dump (db only)"
    echo "----------------------------------------------------------"
    if [[ "$WITH_DB_DUMP" == true ]]; then
        echo "  Included: pg_backup_<city>_<UTC>.sql.gz per running db."
        echo
        echo "  THIS IS A DEBUG DUMP, NOT A BACKUP. It is never uploaded to"
        echo "  S3 and nothing prunes it. The real nightly per-city backup is"
        echo "  the {city}-backup-1 container (src/backup-svc); use"
        echo "    scripts/backup_db_city.sh   to take a real backup"
        echo "    scripts/restore_db_city.sh  to restore one"
    else
        echo "  Not included. Re-run with --with-db-dump if a dump is needed."
        echo "  For real backups use scripts/backup_db_city.sh instead."
    fi
    echo
    echo "State capture"
    echo "----------------------------------------------------------"
    echo "  host/       docker ps -a, images, system df, compose ls, df -h,"
    echo "              uname + docker/compose versions, deploy-multi-city.log,"
    echo "              secret-files.txt (presence + mtime only, never contents)"
    echo "  <svc>/      inspect.json  full docker inspect, env redacted"
    echo "              health.json   healthcheck history ('null' = none defined)"
    echo "              config.txt    image digest, RELEASE_VERSION, SCRAPE_*,"
    echo "                            TASK_TIME/VERIFY_TIME, env (redacted)"
    echo "  ws/         status.json   GET /status from inside the container"
    echo
    echo "NOTE: Phases 2-6 implemented (discovery, logs, artifacts, DB dump,"
    echo "      state). Whole-bundle redaction and packaging land in Phases"
    echo "      7-8; see plan_new_collect_logs_v3.md."
} > "$MANIFEST"

log_info "Wrote $MANIFEST"

# --- Summary ----------------------------------------------------------------

# awk (not `grep -vc`, which prints 0 *and* exits 1 on an empty file, so the
# `|| echo 0` fallback would double up).
TOTAL_FOUND=$(awk -F'\t' '$3 != "absent"' "$STATUS_FILE" | wc -l | tr -d ' ')
TOTAL_FILES=$(count_files "${BUNDLE_DIR}/cities")
BUNDLE_SIZE=$(du -sh "$BUNDLE_DIR" 2>/dev/null | awk '{print $1}')
log_info "Collected ${TOTAL_FILES} file(s) from ${TOTAL_FOUND} container(s) across ${#CITIES[@]} city/cities (${BUNDLE_SIZE:-?})"

log_warn "Phases 1-3 only: logs collected. Artifacts, DB dump, host/container"
log_warn "state, redaction and the tar.gz archive land in Phases 4-8."

log_info "Done. Bundle at: ${BUNDLE_DIR}"

if [[ ${#TROUBLED_CITIES[@]} -gt 0 ]]; then
    log_warn "Cities with collection trouble: ${TROUBLED_CITIES[*]}"
    exit "$EXIT_PARTIAL"
fi
exit "$EXIT_OK"
