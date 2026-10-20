# M6 — Production Monitoring Recommendations

**What to measure in production, how exactly to collect it, and what to do when it trips.**

Scope: the multi-city deployment (6 cities × 4 containers on one EC2 host). Successor to
`M6_monitoring_action_plan.md`, which defined *what to build* — Items 1–7 are shipped. This document
defines *what to watch* now that they exist.

Deliberately constrained to the existing toolchain: AWS SES email, host cron, `scripts/`, Makefile
targets, and SQL. No Prometheus, no Grafana, no CloudWatch tier — M6 Item 8 stays deferred.

---

## Why this document exists

Between 2026-07-22 and 2026-07-25 the nightly `pg_dump` failed in **every city**. Nobody found out
until the logs were read by hand four days later.

Each layer was reporting healthy:

- the `backup` container was `running`, and `fleet_watchdog.py:45` treats `running` as its healthy
  state because that service has no healthcheck;
- the SES failure alert in `backup.py` could not send — it needed the same missing environment that
  broke `pg_dump`;
- the 14:00 staleness check was blind for exactly the same reason;
- `docker ps` showed 24/24 containers up the entire time.

The lesson generalises past that one bug: **every signal in the deployment answered "is the process
alive?" and none answered "did the work succeed?"** The catalog below is organised around outcomes,
and each metric names the failure it would have caught.

> The `pg_dump` root cause is fixed on branch `dev-1.7.8.2` (commit `c9d4daf`). This document treats
> it as the worked example of a monitoring gap, not as an open bug.

---

## Part A — Review findings

Defects in `docker-compose.yml` and `deploy-multi-city-ws.sh` that make monitoring dishonest.
Ranked by whether they cause a **false healthy** (P1), threaten the **whole host** (P2), or leave
deploys **unverified** (P3). None are implemented here — this is a specification.

### P1 — False-healthy class

These make monitoring report success when work is failing. Fix these before trusting any metric
below.

| # | Location | Problem | Proposed change |
|---|---|---|---|
| A1 | `docker-compose.yml:113-142` | `backup` service defines **no healthcheck**. `fleet_watchdog.py:45` therefore accepts `running` as healthy. A container whose cron is dead, or whose job fails every night, is indistinguishable from a working one. **This is the 4-day outage.** | Healthcheck asserting both that cron is alive and that a success marker written by the backup job is newer than `BACKUP_MAX_AGE_HOURS`. Liveness alone is what failed here. |
| A2 | `src/ts/ts.py:200-223` | `evaluate_run_status` returns `(None, ...)` for `status == "running"` — explicitly *not* a problem. If `ws` is killed or OOMs mid-pipeline, the `scrape_runs` row stays `running` forever and the 01:40 verification stays **silent** for that day. | Treat `running` with `started_at` older than ~3h as a problem and alert. See metric **P-4**. |
| A3 | `docker-compose.yml:50-55` | `ws` healthcheck fetches `/docs`, proving only that FastAPI serves HTTP. It stays green when the DB is unreachable and every run fails. | Keep `/docs` as the *liveness* probe — do not make container restarts depend on the DB. Monitor `/status` (which already 503s on DB failure, `main.py:113-117`) as the separate *readiness* signal. Metric **C-2**. |
| A4 | `docker-compose.yml:82-87` | `ts` healthcheck probes port 8080, served by a **daemon thread** (`ts.py:289`). The scheduler loop at `ts.py:297-300` can be dead while the probe still returns 200 — no trigger fires, health stays green. | Scheduler updates a tick timestamp each loop; `/health` returns it and the probe fails when the tick is older than ~5 min. Metric **C-3**. |

### P2 — Host-stability class

One host runs all 6 cities. These are correlated-failure risks: they take down everything at once.

| # | Location | Problem | Proposed change |
|---|---|---|---|
| A5 | `docker-compose.yml` (all services) | No `logging:` options anywhere. 24 containers write unbounded `json-file` logs; `ws` logs verbosely per run. Disk-full stops all 6 cities **and** Postgres simultaneously. | `logging.options.max-size: "10m"`, `max-file: "3"` per service, or a daemon-wide default in `/etc/docker/daemon.json`. Pair with metric **H-1**. |
| A6 | `docker-compose.yml` (all services) | No memory limits, despite `M6_memory_usage_assesment.md` existing. An OOM kill during a run produces a zombie `running` row — which A2 then hides. | Per-service `mem_limit`, sized from that assessment. Monitor with **K-3**. |
| A7 | `deploy-multi-city-ws.sh:7` | `deploy-multi-city.log` grows unbounded and is never rotated. | Logrotate entry, or timestamped logs with retention. |

### P3 — Deploy-verification class

| # | Location | Problem | Proposed change |
|---|---|---|---|
| A8 | `deploy-multi-city-ws.sh:275` | `compose up -d` without `--wait`. It returns once containers are *created*, so `"Successfully deployed $city"` is logged for a city whose `ws` crash-loops 10 seconds later. `SUCCESS_COUNT` measures container creation, not working software. | `up -d --wait --wait-timeout 180`, so compose blocks until healthchecks pass and returns non-zero if they don't. Requires A1/A4 to be meaningful. |
| A9 | `deploy-multi-city-ws.sh:283-285` | The post-deploy trigger — the only real smoke test — sends output to `/dev/null` with `\|\| true`. It cannot fail the deploy or report anything. | Capture the response, assert HTTP 200 and a `run_id`, then poll `/status` and record the outcome in the summary. Metric **D-2**. |
| A10 | `deploy-multi-city-ws.sh:173` | `check_backup_age` takes `awk '{print $1}'` from `aws s3 ls --recursive` — that is the **date column**, not the key the comment on line 183 describes. `cut -d/ -f1-3 \| tr / _` is then a no-op, and `date -j -f "%Y_%m_%d"` cannot parse `2026-07-09`. It works only via the GNU `date -d` fallback on EC2; on macOS it always reports a bogus age. | Parse the key (`$4`), or use `aws s3api list-objects-v2` with `--query` as in metric **B-1**. |
| A11 | whole script | No deployment record is written anywhere: nothing captures which release each city runs or when it was last deployed, so an incident cannot be correlated with a deploy. | Append a line per city per deploy (timestamp, release, image digest, outcome) to a log or S3 object. Metrics **D-1**, **D-3**. |

---

## Part B — Metric catalog

Severity model used throughout:

| Severity | Meaning | Channel |
|---|---|---|
| **P1** | Data loss or total outage in progress | Immediate email |
| **P2** | Degraded; one city or one night affected | Next-morning digest |
| **P3** | Trend worth reviewing | Weekly review |

All commands assume the EC2 host. Containers are discovered **by compose label, never by name
substring** — the convention documented in `CLAUDE.md`, and the reason `collect_logs_v2.sh` was
retired:

```bash
# Resolve one city's container id for a given service
cid() { docker ps -q --filter "label=com.docker.compose.project=$1" \
                    --filter "label=com.docker.compose.service=$2"; }

CITIES="salaspils sigulda marupes_pag adazu_nov ogre jurmala"
```

### Layer H — Host / EC2

Single host, 6 cities. Highest-blast-radius layer.

| ID | Metric | Why it matters | How to collect | Threshold | Sev |
|---|---|---|---|---|---|
| **H-1** | Disk free on `/` and `/var/lib/docker` | Highest-risk metric in the deployment. Unbounded container logs (A5) plus 6 Postgres volumes fill the disk; Postgres then fails writes across all cities at once. | `df -h / /var/lib/docker` | warn <25% free, **P1** <10% | P1 |
| **H-2** | Inode usage | Many small log/report files exhaust inodes while `df -h` still looks fine — a failure that looks like a mystery. | `df -i /var/lib/docker` | warn >80% | P2 |
| **H-3** | Docker reclaimable space | Repeated builds of `sslv-ws:latest`/`sslv-backup:latest` leave dangling images. Quantifies H-1 headroom. | `docker system df` | review >10 GB reclaimable | P3 |
| **H-4** | Memory + swap | 24 containers, no limits (A6). Swap activity is the early warning before OOM kills. | `free -m` | warn >85% used, or any sustained swap | P2 |
| **H-5** | Load average vs vCPU | All 6 cities scrape near the same time; overlap shows as sustained load. | `uptime` | warn 1-min load > 2× vCPU | P3 |
| **H-6** | Largest container log files | Pinpoints *which* service is filling the disk before H-1 goes red. | `du -sh /var/lib/docker/containers/*/*-json.log \| sort -h \| tail -5` | any single file >1 GB | P2 |

### Layer K — Containers

| ID | Metric | Why it matters | How to collect | Threshold | Sev |
|---|---|---|---|---|---|
| **K-1** | Health state per city × service | Baseline "is it up". Already implemented in `fleet_watchdog.py`. Note it is **only trustworthy after A1/A4** — today `backup` and `ts` can be green while broken. | `make fleet-status` | any not `healthy` (`running` for `backup` until A1) | P1 |
| **K-2** | Restart count | A crash-looping container may still be seen "up" at sample time. Rising restarts are the signal a snapshot misses. | `docker inspect -f '{{.Name}} {{.RestartCount}}' $(docker ps -aq)` | any increase day-over-day | P2 |
| **K-3** | OOM-killed flag | Confirms A6 is biting, and explains zombie `running` rows (A2) that would otherwise look inexplicable. | `docker inspect -f '{{.State.OOMKilled}}' <cid>`; host-side `journalctl -k \| grep -i oom` | any `true` | P1 |
| **K-4** | Container uptime vs last deploy | An unexpectedly young container means an unnoticed restart. | `docker inspect -f '{{.State.StartedAt}}' <cid>` | younger than last deploy without a deploy event | P2 |
| **K-5** | Expected container count | Catches a city that silently never came up — 24 expected (6 × db/ws/ts/backup). | `docker ps --filter label=com.docker.compose.service --format '{{.Names}}' \| wc -l` | ≠ 24 | P1 |

### Layer G — PostgreSQL (6 independent instances)

Each city has its own database; there is no central instance, so these run per city.

```bash
psqlc() { docker exec "$(cid "$1" db)" psql -U new_docker_user -d new_docker_db -tAc "$2"; }
```

| ID | Metric | Why it matters | How to collect | Threshold | Sev |
|---|---|---|---|---|---|
| **G-1** | Database size + growth | Sizes the backup and predicts H-1. A sudden jump means duplicate inserts; a flat line means nothing is being written. | `psqlc $c "SELECT pg_database_size('new_docker_db');"` | growth >20%/week, or 0 growth for 7 days | P3 |
| **G-2** | `listed_ads` / `removed_ads` row counts | The core business state. `removed_ads` should grow monotonically; `listed_ads` should stay in a plausible band per city. | `psqlc $c "SELECT (SELECT count(*) FROM listed_ads), (SELECT count(*) FROM removed_ads);"` | `listed_ads` = 0, or ±40% day-over-day | P1 |
| **G-3** | Connection count vs `max_connections` | `scrape_runs` opens a fresh connection per call (`scrape_runs.py:63-66`); a leak surfaces here first. | `psqlc $c "SELECT count(*) FROM pg_stat_activity;"` vs `SHOW max_connections` | >70% of max | P2 |
| **G-4** | Longest running transaction | A stuck transaction blocks `pg_dump`, which is a plausible non-env cause of backup failure. | `psqlc $c "SELECT coalesce(max(extract(epoch from now()-xact_start)),0) FROM pg_stat_activity WHERE state <> 'idle';"` | >1800 s | P2 |
| **G-5** | Dead tuples / autovacuum recency | The daily insert-and-delete cycle generates bloat; no autovacuum means the DB and every backup keep growing. | `psqlc $c "SELECT relname, n_dead_tup, last_autovacuum FROM pg_stat_user_tables;"` | `n_dead_tup` >100k, or no autovacuum in 7 days | P3 |
| **G-6** | Connection failure from `ws` | Distinguishes "DB down" from "pipeline bug" without reading tracebacks. | `curl -s localhost:8000/status` → HTTP 503 (see `main.py:113-117`) | any 503 | P1 |

### Layer P — Pipeline and business outcomes

**The highest-value layer.** All of it reads the `scrape_runs` table that already exists
(`scrape_runs.py:75-91`) — no new instrumentation needed, only queries. Columns are exactly:
`run_id, city, started_at, finished_at, status, failed_stage, error, pages_fetched,
urls_discovered, new_ads, still_listed_ads, removed_ads, listed_table_rows, removed_table_rows`.

| ID | Metric | Why it matters | Threshold | Sev |
|---|---|---|---|---|
| **P-1** | Hours since last successful run, per city | The single best "is the product working" number. One query replaces reading 6 sets of logs. | >26 h | P1 |
| **P-2** | 7-day success rate per city | Distinguishes a one-night blip from steady degradation. | <85% | P2 |
| **P-3** | Run duration p50 / p95 | Duration drift is the earliest sign ss.lv is throttling, or that a city outgrew its schedule. | p95 >2× 30-day p50 | P2 |
| **P-4** | Zombie `running` rows | **Closes the A2 hole.** A run whose container died mid-pipeline is invisible today. | any `running` older than 3 h | P1 |
| **P-5** | Failure distribution by `failed_stage` | Points at the broken component immediately — `web_scraper` means site/blocking, `db_worker` means DB, `aws_mailer` means SES. | any stage ≥3 failures in 7 days | P2 |
| **P-6** | `urls_discovered` per run | Zero means the parser broke or the scraper is blocked. Already alerted live by `alert_mailer.py:127-133`; tracked here as a trend. | 0, or <50% of 7-day median | P1 |
| **P-7** | Removed-ads percentage | A removal spike is nearly always failed discovery, not real delistings. Live threshold `ALERT_REMOVED_PCT` (default 30, `alert_mailer.py:57`). | >30% of pre-run rows | P1 |
| **P-8** | Zero-new-ads streak | Silent breakage in diffing looks exactly like a quiet market. `ALERT_ZERO_NEW_RUNS` default 3 (`alert_mailer.py:58`). | ≥3 consecutive successful runs | P2 |
| **P-9** | `pages_fetched` vs expectation | Detects pagination regressions after the M6 dynamic page-count work. | drops while `urls_discovered` also drops | P2 |

Queries — run against any one city's DB, or per city and aggregate:

```sql
-- P-1  Hours since last success, per city
SELECT city,
       round(extract(epoch FROM now() - max(started_at)) / 3600, 1) AS hours_since_success
FROM scrape_runs WHERE status = 'success' GROUP BY city ORDER BY 2 DESC;

-- P-2  7-day success rate
SELECT city, count(*) AS runs,
       round(100.0 * count(*) FILTER (WHERE status = 'success') / count(*), 1) AS success_pct
FROM scrape_runs WHERE started_at > now() - interval '7 days' GROUP BY city ORDER BY 3;

-- P-3  Duration percentiles over 30 days
SELECT city,
       round(percentile_cont(0.5) WITHIN GROUP (
             ORDER BY extract(epoch FROM finished_at - started_at))) AS p50_sec,
       round(percentile_cont(0.95) WITHIN GROUP (
             ORDER BY extract(epoch FROM finished_at - started_at))) AS p95_sec
FROM scrape_runs
WHERE status = 'success' AND finished_at IS NOT NULL
  AND started_at > now() - interval '30 days'
GROUP BY city;

-- P-4  Zombie runs (the A2 blind spot)
SELECT run_id, city, started_at,
       round(extract(epoch FROM now() - started_at) / 3600, 1) AS hours_stuck
FROM scrape_runs
WHERE status = 'running' AND started_at < now() - interval '3 hours'
ORDER BY started_at;

-- P-5  Failure distribution by stage, last 7 days
SELECT city, failed_stage, count(*) AS failures, max(started_at) AS latest
FROM scrape_runs
WHERE status = 'failed' AND started_at > now() - interval '7 days'
GROUP BY city, failed_stage ORDER BY failures DESC;

-- P-6 / P-9  Discovery trend, last 14 runs
SELECT started_at::date AS day, city, pages_fetched, urls_discovered,
       new_ads, removed_ads, listed_table_rows
FROM scrape_runs
WHERE status = 'success' ORDER BY started_at DESC LIMIT 14;
```

### Layer S — Scraper vs ss.lv (external dependency)

**Currently unmonitored, and the most likely cause of a future outage.** ss.lv is a third party that
can change layout or start blocking without notice. Layer P detects the *consequence* a day later;
these detect the *cause* as it happens.

| ID | Metric | Why it matters | How to collect | Threshold | Sev |
|---|---|---|---|---|---|
| **S-1** | HTTP 403 / 429 rate from ss.lv | The signature of being blocked or rate-limited. Distinguishes "we are blocked" from "our parser broke" — different fixes entirely. | Count status codes in `ws` logs; better, have `web_scraper` count them into a run column | any 403/429 | P1 |
| **S-2** | URLs discovered per page | Parser-health proxy independent of market volume. A layout change makes this collapse while pages still fetch fine (HTTP 200, zero results). | `urls_discovered / pages_fetched` from `scrape_runs` | <50% of 30-day median | P1 |
| **S-3** | List-page response time | Rising latency usually precedes throttling. | Timed request from the scraper | p95 >3× baseline | P3 |
| **S-4** | Scrape politeness settings in effect | `SCRAPE_DELAY_SEC` / `SCRAPE_LIST_DELAY_SEC` (`docker-compose.yml:35-37`) are the main lever against being blocked; a `.env` regression silently removes it. | `docker exec <ws> printenv SCRAPE_DELAY_SEC` | differs from intended per-city value | P2 |
| **S-5** | Cross-city correlation | All 6 cities failing at once means blocking or a site-wide change (shared source IP); one city failing means that city's config or URL. | Compare P-6 across cities for the same night | ≥3 cities degraded same night | P1 |

S-5 is worth building explicitly: a single-host deployment shares one egress IP, so a block hits all
cities simultaneously. That correlation is the fastest available diagnosis.

### Layer B — Backup and restore

The layer that failed for 4 days. Note that **backup success is not the goal — restorability is**,
so B-5 matters as much as B-1.

| ID | Metric | Why it matters | How to collect | Threshold | Sev |
|---|---|---|---|---|---|
| **B-1** | Age of newest object per city bucket | The metric that would have caught the outage on night one. Independent of container self-reporting — checked from outside. | `aws s3api list-objects-v2 --bucket sslv-prod-$c-db-backups --prefix db-backups/ --query 'sort_by(Contents,&LastModified)[-1].[Key,LastModified,Size]' --output text` | >26 h (`BACKUP_MAX_AGE_HOURS`, `docker-compose.yml:137`) | P1 |
| **B-2** | Newest object size | A dump that ran against an empty DB still uploads successfully. Enforced in-process by `MIN_BACKUP_SIZE_KB` (default 10, `docker-compose.yml:136`). | same query, `Size` field | <10 KB | P1 |
| **B-3** | Size delta vs previous day | Catches partial dumps that pass the absolute floor — a 60% shrink means truncation, not a quiet day. | compare two newest objects | ±50% | P2 |
| **B-4** | Object count vs retention | Confirms the 90-day lifecycle policy is actually applied; unbounded growth is a silent cost leak. | `aws s3 ls s3://sslv-prod-$c-db-backups/db-backups/ --recursive \| wc -l` | ≫ 90 | P3 |
| **B-5** | Restore rehearsal outcome | An untested backup is a hypothesis. This is the only metric that proves recoverability. | `make e2e-backup-restore` (and `make test-restore`) | any failure; run monthly | P1 |
| **B-6** | Backup job exit code | `backup.py` exit codes distinguish dump / upload / verify failure by step. Requires A1 to be visible externally. | container log + healthcheck marker | non-zero | P1 |

**B-1 and B-2 must be collected from outside the backup container.** The outage proved that a
component cannot be trusted to report its own failure — the alert path shared the broken dependency.
`fleet_watchdog.py` already does this correctly.

### Layer D — Deployment

| ID | Metric | Why it matters | How to collect | Threshold | Sev |
|---|---|---|---|---|---|
| **D-1** | Deploy outcome per city | Today's `SUCCESS_COUNT` counts container creation, not health (A8). | `up -d --wait` exit code per city | any failure | P1 |
| **D-2** | Post-deploy smoke-test result | Currently discarded (A9). The one end-to-end check that the new build actually works. | assert 200 + `run_id` from `/run-task/{city}`, then poll `/status` | non-200, or run not `success` within 1 h | P1 |
| **D-3** | Running release version per city | Without it you cannot answer "what changed?" during an incident. `RELEASE_VERSION` is already passed to `ws` (`docker-compose.yml:29`). | `docker exec <ws> printenv RELEASE_VERSION`; also image digest | differs across cities unintentionally | P2 |
| **D-4** | Time to healthy after deploy | Rising settle time signals resource pressure on the shared host. | duration of `up -d --wait` | >180 s | P3 |
| **D-5** | Config drift | `.env.*` on disk can diverge from the S3 copy (the script reuses whatever is already there, `deploy-multi-city-ws.sh:101-104`), so a redeploy silently keeps stale config. | checksum local `.env.$c` vs `s3://$CICD_FILES_BUCKET/.env.$c` | mismatch | P2 |
| **D-6** | Deploy frequency + failure rate | Standard change-failure signal; needs the deploy record from A11. | deploy log | change-failure rate >20% | P3 |

### Layer E — Email / SES deliverability

**Every alert in this document depends on this layer.** If SES degrades, the whole system goes
silent — which is indistinguishable from everything being fine. This layer must be checked
independently, and it is the one place where "no news" genuinely is bad news.

| ID | Metric | Why it matters | How to collect | Threshold | Sev |
|---|---|---|---|---|---|
| **E-1** | Daily report emails sent vs expected | 6 cities = 6 reports/day. A shortfall is the cheapest end-to-end proof the pipeline worked. | `aws ses get-send-statistics` | <6/day | P2 |
| **E-2** | Bounce rate | AWS suspends sending above ~5%. Suspension silences every alert channel at once. | `aws ses get-send-statistics` | >2% warn, >5% **P1** | P1 |
| **E-3** | Complaint rate | Same suspension risk. | `aws ses get-send-statistics` | >0.1% | P2 |
| **E-4** | Sending quota headroom | Cheap to check, and quota exhaustion is a silent-failure mode. | `aws ses get-send-quota` | >70% of 24 h quota | P3 |
| **E-5** | Alert-path liveness | Proves the alert channel itself still works. Without it, silence is ambiguous. | weekly synthetic test alert | no test email received | P1 |

E-5 is the direct lesson of the outage: the failure alert could not send, so silence was read as
health. A weekly heartbeat email makes silence *mean* something.

---

## Part C — Alert routing and noise budget

| Severity | Routing | Contents |
|---|---|---|
| **P1** | Immediate email, subject prefixed `SSLV ALERT:` | H-1(<10%), K-1, K-3, K-5, G-2, G-6, P-1, P-4, P-6, P-7, S-1, S-2, S-5, B-1, B-2, B-5, D-1, D-2, E-2, E-5 |
| **P2** | Next-morning digest, one email for the whole fleet | H-1(<25%), H-2, H-4, H-6, K-2, K-4, G-3, G-4, P-2, P-3, P-5, P-8, P-9, S-4, B-3, D-3, D-5, E-1, E-3 |
| **P3** | Weekly review, terminal only (`make fleet-status`) | H-3, H-5, G-1, G-5, S-3, B-4, D-4, D-6, E-4 |

**Noise budget: at most one P1 email per week under normal operation.** This is a hard design
constraint, not an aspiration. A channel that fires daily gets filtered, and a filtered channel is
how a 4-day outage goes unnoticed. Concretely:

- Deduplicate: one email per city per issue per day, not one per check cycle.
- Suppress dependents: when `db` is down, do not also alert on G-2 through G-6 for that city.
- Send the P2 digest **even when everything is healthy** — a digest that only appears on failure is
  indistinguishable from a broken digest. This is the same reasoning as E-5.
- Review P3 monthly and delete any check that has never fired usefully. An unused check is noise
  with extra steps.

---

## Part D — The ten golden signals

If nothing else here is adopted, these ten catch the realistic failures. Ranked by expected value.

| # | Signal | Metric | Threshold | Catches |
|---|---|---|---|---|
| 1 | Backup age per city | B-1 | >26 h | The 2026-07 outage, on night one |
| 2 | Hours since last successful run | P-1 | >26 h | Any pipeline failure, from any cause |
| 3 | Host disk free | H-1 | <10% | Correlated failure of all 6 cities |
| 4 | Zombie `running` runs | P-4 | >3 h | Mid-run container death (today invisible) |
| 5 | `listed_ads` row count | G-2 | 0 or ±40% | Data destruction and silent write failure |
| 6 | URLs discovered per page | S-2 | <50% of median | ss.lv layout change or blocking |
| 7 | Container health + count | K-1, K-5 | any unhealthy, ≠24 | A city that never came up |
| 8 | Backup size + delta | B-2, B-3 | <10 KB, ±50% | Backups that upload but are useless |
| 9 | SES bounce rate | E-2 | >5% | Loss of the entire alert channel |
| 10 | Restore rehearsal | B-5 | any failure, monthly | Backups that exist but cannot restore |

Signals 1, 4, 6, 8 and 10 have **no coverage today**. Signals 2, 5 and 7 are partly covered by
`fleet_watchdog.py`. Signals 3 and 9 are entirely unmonitored.

---

## Part E — Phased adoption

Each phase extends something that already exists. No new services.

### Phase 0 — Stop the lying (prerequisite)

Nothing below is trustworthy until these land: **A1** (backup healthcheck), **A2** (zombie-run
alert), **A4** (ts scheduler heartbeat). Until then `make fleet-status` reports healthy for a fleet
that is not.

### Phase 1 — Host safety

**A5** (log rotation) and **H-1/H-2** in `fleet_watchdog.py`. Cheapest prevention of a
whole-deployment outage. Add **A7** while touching it.

### Phase 2 — Business metrics

Add the Layer P queries to `fleet_watchdog.py`, which already opens per-city DB access. Start with
**P-1**, **P-4**, **P-5**. This is the largest visibility gain per hour spent: the table exists,
only the queries are missing.

### Phase 3 — External dependency and alert-path integrity

**S-1/S-2/S-5** (needs `web_scraper` to record status codes into `scrape_runs` — the one place new
instrumentation is genuinely required) and **E-2/E-5**.

### Phase 4 — Deploy verification

**A8**, **A9**, **A11** — `--wait`, a real smoke test, and a deploy record.

### Ongoing

**B-5** monthly via `make e2e-backup-restore`. Put it in the calendar; it is the only proof that any
of the backup metrics mean anything.

---

## Part F — Runbook

First three commands per alert. Assumes the `cid()` helper from Part B.

| Alert | 1 | 2 | 3 |
|---|---|---|---|
| **B-1** backup stale | `docker logs $(cid $CITY backup) --tail 100` | `docker exec $(cid $CITY backup) /app/run-job.sh` | `aws s3 ls s3://sslv-prod-$CITY-db-backups/db-backups/ --recursive \| tail -5` |
| **P-1** no successful run | `curl -s localhost:8000/status \| jq .` (or via `docker exec`) | `docker logs $(cid $CITY ws) --tail 200` | `make collect-logs CITY=$CITY` |
| **P-4** zombie run | `docker inspect -f '{{.State.OOMKilled}} {{.RestartCount}}' $(cid $CITY ws)` | `docker logs $(cid $CITY ws) --tail 200` | check H-4 host memory |
| **H-1** disk full | `df -h /var/lib/docker` | `du -sh /var/lib/docker/containers/*/*-json.log \| sort -h \| tail` | `docker system prune -f` (images only; **never** `-a --volumes`) |
| **G-2** row count anomaly | `psqlc $CITY "SELECT count(*) FROM listed_ads;"` | `SELECT * FROM scrape_runs ORDER BY started_at DESC LIMIT 5;` | compare against last backup before restoring |
| **S-2 / S-5** scraper degraded | `docker logs $(cid $CITY ws) \| grep -iE '403\|429\|blocked'` | compare P-6 across all 6 cities | verify `CITY_MAIN_URL` still resolves and renders |
| **K-1** container unhealthy | `docker inspect --format='{{json .State.Health}}' $(cid $CITY $SVC) \| jq` | `docker logs $(cid $CITY $SVC) --tail 100` | `make collect-logs CITY=$CITY` |
| **E-2** bounce rate | `aws ses get-send-statistics` | verify `DEST_EMAIL` / `SRC_EMAIL` in `.env.*` | check SES suspension notices in the AWS console |

`make collect-logs CITY=<city>` is the general escalation: it bundles rotated logs, `docker logs`,
inspect/health/config state and city-scoped artifacts, with secrets masked bundle-wide. Read
`SUMMARY.txt` first.

---

## Deliberate exclusions

- **CloudWatch / SNS** (M6 Item 8) — email suffices at 6 cities; revisit past ~10, or when a second
  host appears.
- **Prometheus / Grafana / exporters** — three more containers on a host that already lacks memory
  limits would add the failure mode being monitored for.
- **APM / tracing** — a daily batch pipeline with an 8-stage sequence does not need distributed
  tracing; `failed_stage` in `scrape_runs` already localises failures.
- **Uptime/SLA metrics for propertydata.lv** — out of scope for this deployment; worth a separate
  external check.

## Related documents

| Document | Relationship |
|---|---|
| `M6_monitoring_action_plan.md` | Defined Items 1–7 (shipped). This document is what to watch now that they exist. |
| `M6_memory_usage_assesment.md` | Should supply the limits for A6. |
| `M6_phase_1_backup_restore_service_plan.md` | Backup/restore design behind Layer B. |
| `plan_new_collect_logs_v3.md` | The log-collection tooling used throughout Part F. |
| `M7_ws_scaling_blocker_problems.md` | Scaling constraints that will change Layer P thresholds. |
