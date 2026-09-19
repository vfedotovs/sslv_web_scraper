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

### P0 — Delivery plumbing  ✅ implemented on `dev-1.7.9.1`
- [x] Staging topic: `https://ntfy.sh/staging-sslv-mc-alerts` (default of `NTFY_TOPIC_URL` in the Makefile). **Note:** this name is guessable — see the security section; move to a random name or token-protected topic before prod.
- [ ] Prod topic: create one and pass it explicitly (`make watchdog-install M6_ENV=prod NTFY_TOPIC_URL=...`; the Makefile refuses to install a non-staging env on the staging topic).
- [x] `send_ntfy()` in `scripts/fleet_watchdog.py` (stdlib `urllib`), plus `--ntfy-mode {problems,always,never}`, `--ntfy-url` (`$NTFY_TOPIC_URL`), `--ntfy-token` (`$NTFY_TOKEN`).
- [x] De-duplication: `--state-file` (default `~/.local/state/sslv-watchdog/state.json`) remembers the last pushed problem set; numbers are masked so "27h old" → "28h old" is not a new alert. Pushes on change (alert / partial recovery / resolved) plus a reminder every `--ntfy-reminder-hours` (default 6). State is saved only after a successful push, so a failed push is retried next run.
- [x] Priorities: `urgent` for last-run and backup problems (#1, #2), `high` for everything else; `low` for the heartbeat.
- [x] systemd timers (`scripts/systemd/`, installed by `make watchdog-install M6_ENV=staging`): `sslv-watchdog.timer` every 15 min (`--ntfy-mode problems`, no email), `sslv-watchdog-heartbeat.timer` daily 06:35 UTC (`--ntfy-mode always`, SES email on problems only). Config in `/etc/sslv-watchdog.env`.
- [x] `make watchdog-test-ntfy`, `make watchdog-status`, `make watchdog-uninstall`.

**On the host:**
```bash
make watchdog-test-ntfy M6_ENV=staging     # phone should get a low-priority test push
make watchdog-install  M6_ENV=staging      # needs sudo; enables both timers
make watchdog-status                       # timers + last run output
```
The 15-minute cadence covers today's checks (containers, runs, backups). P1's host checks (#3, #4) will run on the same timer; tighten to 5 min only if needed.

### P1 — Metrics not monitored today  ✅ implemented on `dev-1.7.9.2`
All run on the 15-minute `sslv-watchdog.timer` as a `host` line in the report; host problems are keyed `host`, the cross-city one `fleet`.
- [x] **#3 Memory:** `MemAvailable` (not `MemFree`) + swap from `/proc/meminfo`; `memory low` below `--min-mem-available-mib` (150) → **high**. Kernel OOM kills since the previous run from `journalctl -k` → `OOM kill: …` **urgent**. (Docker's `OOMKilled` flag resets when `restart: always` restarts the container, so the kernel log plus #5's restart delta is what catches it.)
- [x] **#4 Disk:** `shutil.disk_usage('/')`; `disk low` below `--disk-warn-free-pct` (20) → **high**, `disk critical` below `--disk-crit-free-pct` (10) → **urgent**.
- [x] **#5 Count + restarts:** running compose containers vs 4 × cities (`ctr:24/24`), flags leftover containers not in `cities.yaml`; restart count delta per container vs the previous run → **high**. A container recreated by a deploy (new Id) resets its baseline instead of alerting.
- [x] **#6 Cross-city collapse:** `zero URLs discovered` per city when a `success` run has `urls_discovered == 0` → **high**; ≥ `--collapse-min-cities` (3) such cities → `fleet: scraper collapse` **urgent**.
- [x] **#7 Heartbeat:** the daily 06:35 UTC push now includes the host line (mem, OOM, disk, containers); optional `HEARTBEAT_PING_URL` (e.g. healthchecks.io) is pinged after every timer run — `make watchdog-install M6_ENV=staging HEARTBEAT_PING_URL=https://hc-ping.com/<uuid>`.
- Restart/OOM baselines live in the state file next to the ntfy state. `--ntfy-mode never` (`make fleet-status`) is **read-only**, so manual runs never consume an event the timer should alert on.
- Host requirement: the timer user must be able to read the kernel journal (membership of `systemd-journal` or `adm`; check with `id`, fix with `sudo usermod -aG systemd-journal ec2-user`). If not, the report shows `oom:?` rather than failing.

### P2 — Tighten existing checks  ✅ implemented on `dev-1.7.9.3`
- [x] **#1 stuck runs:** a last run still `running` after `--max-running-hours` (3) → `last run stuck in 'running'` **urgent** (the ws-OOM-mid-pipeline case). `src/ts/ts.py`'s 01:40 verification still ignores `running` (M6 A2); the watchdog now covers it from outside.
- [x] **#1 last success:** age of the newest `status = 'success'` row per city, read with psql in the `db` container (`/status` only returns the newest run of any status). `last successful run is Xh old` > 26 h → **urgent**; `none recorded` when a city has never succeeded. Not repeated when the scheduler-dead alert already fired. Report shows `ok:Xh ago`.
- [x] **#2 backup size:** newest object below `--min-backup-size-kb` (default `$MIN_BACKUP_SIZE_KB`, else 10) → `newest backup is only X KB` **urgent**, checked from S3 rather than trusting the backup container.
- [x] Every `fleet_watchdog.py` problem goes through ntfy as well as SES — true since P0: `notify_ntfy()` pushes the full problem set, and the 06:35 heartbeat run still sends the SES email on problems.

### P3 — Verify the alerts actually fire  🛠 tooling on `dev-1.7.9.4`, run pending on staging
`scripts/watchdog_drill.py` (`make watchdog-drill M6_ENV=staging`) fires each alert once through the **real** watchdog and ntfy, then removes the condition and checks the recovery push lists it under "Resolved:". Pushes are titled `[DRILL] …`, each drill uses a throwaway state file, and the Makefile pauses `sslv-watchdog.timer` for the duration so the real timer does not alert on the drill.

| Drill | How the condition is induced | Expected alert |
|---|---|---|
| `memory` (#3) | threshold raised above total RAM | `memory low` ≥ high |
| `disk` (#4) | warn threshold set to 100% — **nothing is filled** (replaces the `fallocate` idea: same alert path, zero risk to Postgres) | `disk low` ≥ high |
| `backup` (#2) | min size raised above any real backup — S3 untouched (replaces the empty test bucket, which would only give "could not list") | `newest backup is only` urgent |
| `oom` (#3) | kernel OOM log faked in-process (a real OOM kill is not safe) | `OOM kill` urgent |
| `stuck-run` (#1) | `/status` faked: one city `running` for 4 h | `stuck in 'running'` urgent |
| `collapse` (#6) | `/status` faked: every city 0 URLs | `scraper collapse` urgent |
| `container` (#5) | **real** `docker stop <city>-ts-1`, then start + wait healthy; refused within 20 min of 00:40/01:40 UTC unless `--force` | `container … is exited` ≥ high |
| `heartbeat` (#7) | `--ntfy-mode always` | `fleet OK` low (healthy fleet) |

- [ ] Run on staging: `make watchdog-drill M6_ENV=staging` (or `DRILL=memory,container` to limit) — expect 8 × PASS.
- [ ] Confirm on the phone that every `[DRILL]` push arrived (the script only sees that ntfy accepted them) — alert + recovery per drill, 15 in total on a healthy fleet.
- [ ] Stop the heartbeat timer for a day (`sudo systemctl stop sslv-watchdog-heartbeat.timer`) and confirm the missing 06:35 push is noticed — or the dead-man's-switch alert fires if `HEARTBEAT_PING_URL` is set (then also stop `sslv-watchdog.timer`, which does the pinging). Restart both afterwards.

### Related, not monitoring (reduces how often these alerts fire)
- [ ] Add 2 GB swap on the host (memory headroom; see #3).
- [ ] Stagger `TASK_TIME` per city and make the backup cron time configurable.
- [ ] Set Docker log rotation (`max-size: 10m`, `max-file: 3`) — biggest driver of #4.
- [ ] Merge the M8 pandas removal from `dev-1.8.5` — largest avoidable memory consumer.
