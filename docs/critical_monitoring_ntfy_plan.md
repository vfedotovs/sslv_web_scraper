# Critical Monitoring via ntfy — Short List

**Branch:** `dev-1.7.9` · **Date:** 2026-09-19 · **Scope:** multi-city host (6 cities × db/ws/ts/backup = 24 containers, 2 GB EC2, no swap)

## Why this document exists

`docs/M6_production_monitoring_recommendations.md` catalogs ~45 metrics. That is the
reference; this is the **minimum set worth being woken up for**, delivered as push
notifications through ntfy (as the M5 host did with `ntfy.sh/m5_arm_sslv_alerts`).

Selection rule — a metric makes this list only if **all three** hold:

1. It signals **data loss, a total outage, or an outage about to happen** (not a trend).
2. It is **not already self-reported by the component that fails** (the 4-day backup
   outage proved a component cannot be trusted to report its own failure).
3. It is **actionable**: the alert text alone tells you where to look.

Metric IDs in brackets map back to the M6 catalog.

## Why ntfy in addition to SES email

All current alerting (`alert_mailer.py`, `fleet_watchdog.py`, backup staleness check)
goes through **AWS SES**. If SES breaks — suspended for bounces, IAM change, quota — every
alert goes silent at once, which looks exactly like "all healthy". ntfy is a **second,
independent channel** with an instant phone push, and it needs nothing but `curl`.

---

## The critical metrics (7)

| # | Metric | Threshold → ntfy priority | Check cadence |
|---|---|---|---|
| 1 | Hours since last **successful** scrape, per city (+ stuck `running` runs) | >26 h, or `running` >3 h → **urgent** | hourly |
| 2 | Backup freshness + size per city, read from **S3** | newest >26 h or < `MIN_BACKUP_SIZE_KB`, or no object → **urgent** | hourly |
| 3 | Host memory available + OOM kills | available <150 MiB → **high**; any OOM kill → **urgent** | every 5 min |
| 4 | Disk free on `/` | <20% → **high**; <10% → **urgent** | every 15 min |
| 5 | Container health + expected count + restarts | not healthy, count ≠ 24, or restart count increased → **high** | every 5 min |
| 6 | Scraper output collapse (`urls_discovered` = 0), cross-city | 1 city → **high**; ≥3 cities same night → **urgent** | after each run window |
| 7 | Heartbeat (alert-path liveness) | daily "all OK" message → **low**; its **absence** is the alert | daily |

### 1. Hours since last successful scrape  [P-1, P-4]

**Why:** This is the product. One number per city answers "is it working" without
reading 6 sets of logs. The stuck-`running` part closes a known blind spot: if `ws` is
OOM-killed mid-pipeline, the `scrape_runs` row stays `running` forever and
`ts.py`'s 01:40 verification treats `running` as "not a problem" — so the failure is
silent until the 26 h age check fires the *next* night. With 415 MiB available after
deploy (see #3), an OOM mid-run is the most likely way this happens.

**Today:** `fleet_watchdog.py` `check_last_run()` alerts on `failed` and on age >26 h,
but uses the last run of *any* status, and has no short threshold for `running`.

### 2. Backup freshness + size, checked from S3  [B-1, B-2]

**Why:** Data loss is the only failure here that cannot be fixed afterwards. The check
must read the **bucket**, not the backup container's own report — that is exactly what
failed for 4 days. Size matters as much as age: a dump of an empty or unreachable DB
still uploads "successfully".

**Today:** `fleet_watchdog.py` `check_backup()` checks age from S3, but not size and not
through ntfy. `MIN_BACKUP_SIZE_KB` is enforced only inside the container (self-report).

### 3. Host memory available + OOM kills  [H-4, K-3]

**Why:** Measured on staging after deploy: `free` 89 MiB, **`available` 415 MiB** of
1.8 GiB, **no swap**, no `mem_limit` on any container. All 6 cities scrape at 00:40 and
all 6 backups run at 02:00 — the peaks are synchronized. With no swap, exhausting
memory means the kernel kills a process immediately, possibly a Postgres container,
and nothing reports it. Use `available`, not `free` (page cache is reclaimable).

**Today:** not monitored.

### 4. Disk free on `/`  [H-1]

**Why:** Largest blast radius on the host. A full disk stops Postgres writes for **all 6
cities at once**. Container logs have no `max-size` (unbounded `json-file`), images are
rebuilt on the host each deploy, and the root volume is at 58% (9.2 of 16 GB) already.

**Today:** not monitored.

### 5. Container health, count and restarts  [K-1, K-2, K-5]

**Why:** Baseline "is it up". Count catches a city that silently never came up (the
deploy script counts container *creation* as success). Restart count catches a
crash-loop that looks "up" at sampling time. Caveat: `backup` and `ts` healthchecks can
be green while broken (M6 A1/A4) — which is why #1 and #2 check outcomes, not liveness.

**Today:** `fleet_watchdog.py` `check_containers()` checks per-container state; count and
restart delta are not checked.

### 6. Scraper output collapse, cross-city  [P-6, S-5]

**Why:** ss.lv is a third party that can change layout or block us without notice —
the most likely cause of a future outage. A run can finish `success` with **zero URLs**
(HTTP 200, parser finds nothing). All cities share one egress IP, so **≥3 cities
collapsing the same night means blocking or a site-wide change**, while one city means
that city's config — the correlation is the fastest diagnosis available.

**Today:** `alert_mailer.py` emails per city on 0 URLs (SES path only); no cross-city view.

### 7. Heartbeat — alert-path liveness  [E-5]

**Why:** Monitoring that has silently stopped is worse than none, because silence reads
as "healthy". A low-priority daily "fleet OK — 6/6 cities, 24/24 containers, mem X MiB,
disk Y%" message proves the host, the checker, the timer and ntfy all still work. If it
does not arrive by 07:00, something is broken. For a fully automatic check of *absence*,
pair it with a dead-man's-switch service (e.g. healthchecks.io ping); ntfy alone cannot
alert on a missing message.

---

## Deliberately left out (and why)

| Left out | Reason |
|---|---|
| CPU / load average | Scraping is I/O-bound; high load is a symptom already caught by #1 and #3. |
| DB size, dead tuples, connections | Trends for weekly review, not pages. |
| SES bounce/complaint rates | Important, but a daily digest item; #7 covers "alerts stopped arriving". |
| Deploy smoke test / version drift | Belongs in the deploy script (M6 A8/A9), not a continuous monitor. |
| Row-count and new-ads streaks | Already emailed by `alert_mailer.py`; lower urgency than #6. |

---

## ntfy security — read before enabling

- **Public ntfy.sh topics are open:** anyone who knows the topic name can **read** every
  alert and **publish** fake ones. `m5_arm_sslv_alerts` is guessable.
- Use a **random topic name** (e.g. `sslv-staging-alerts-<16 random chars>`), or a
  reserved topic with an access token (ntfy.sh paid tier), or self-hosted ntfy.
- Store it as `NTFY_TOPIC_URL` (and optional `NTFY_TOKEN`) in `.env.prod` in the CICD
  bucket — **never commit it**.
- Messages must never contain secrets, passwords, keys or DB contents. City name,
  metric, value and threshold are enough.
- Separate topics for staging and prod, so staging noise does not train you to ignore prod.

---

## Action items

### P0 — Delivery plumbing
- [ ] Create topics: `sslv-staging-alerts-<random>` and `sslv-prod-alerts-<random>`; subscribe in the ntfy phone app.
- [ ] Add `NTFY_TOPIC_URL` (+ optional `NTFY_TOKEN`) to `.env.prod` in each CICD bucket.
- [ ] Add a `send_ntfy(title, message, priority, tags)` helper to `scripts/fleet_watchdog.py` (stdlib `urllib`, like the rest of the script) and a `--ntfy-mode {problems,always,never}` flag next to `--email-mode`.
- [ ] De-duplicate: persist last-alerted state (e.g. `/var/lib/sslv-watchdog/state.json`) and push only on **state change** (OK→problem, problem→OK) plus one reminder per 6 h while still failing, so a 5-min timer does not spam.
- [ ] Schedule on the host with **systemd timers** (Amazon Linux 2023 has no cron by default): a 5-min timer for #3/#4/#5, an hourly timer for #1/#2/#6, a daily 06:30 UTC timer for #7.

### P1 — Metrics not monitored today
- [ ] **#3 Memory:** read `MemAvailable` from `/proc/meminfo`; count OOM kills from `journalctl -k --since -10min | grep -ci 'killed process'` and `docker inspect -f '{{.State.OOMKilled}}'`.
- [ ] **#4 Disk:** `shutil.disk_usage('/')`.
- [ ] **#5 Count + restarts:** expected = 4 × cities from `config/cities.yaml`; restart delta from `docker inspect -f '{{.RestartCount}}'` vs saved state.
- [ ] **#6 Cross-city collapse:** read `urls_discovered` from each city's `/status`; count cities with 0; escalate at ≥3.
- [ ] **#7 Heartbeat:** daily summary push at `low` priority; optional healthchecks.io ping URL as `HEARTBEAT_PING_URL`.

### P2 — Tighten existing checks
- [ ] **#1:** alert on `status == running` with `started_at` older than 3 h (the OOM-mid-run case); compute age from the last **successful** run.
- [ ] **#2:** add size check (`< MIN_BACKUP_SIZE_KB`: 10 KB on this branch, 1 KB after the `dev-1.8.5` change) to `check_backup()` using the `Size` already returned by `get_backup_freshness()`.
- [ ] Route every existing `fleet_watchdog.py` problem through ntfy as well as SES.

### P3 — Verify the alerts actually fire
- [ ] On staging, trigger each alert once: stop a `*-ts-1` container (#5); `fallocate` a large file to cross the disk threshold (#4); lower the memory threshold temporarily (#3); point #2 at an empty test bucket; set `urls_discovered` expectations against a stubbed `/status` (#6).
- [ ] Confirm the recovery ("resolved") push arrives for each.
- [ ] Stop the heartbeat timer for a day and confirm the missed heartbeat is noticed (#7).

### Related, not monitoring (reduces how often these alerts fire)
- [ ] Add 2 GB swap on the host (memory headroom; see #3).
- [ ] Stagger `TASK_TIME` per city and make the backup cron time configurable.
- [ ] Set Docker log rotation (`max-size: 10m`, `max-file: 3`) — biggest driver of #4.
- [ ] Merge the M8 pandas removal from `dev-1.8.5` — largest avoidable memory consumer.
