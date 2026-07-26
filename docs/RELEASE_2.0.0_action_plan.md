# Release 2.0.0 — Action Plan

**From single-city `v1.5.12` to the multi-city deployment.** Branch review, integration strategy,
and the actionable item list to get there.

Status: **planning**. Nothing in this document has been executed. No code changes were made in
producing it.

---

## 1. Why 2.0.0

`v1.5.12` (`630bcda`, 2026-05-01) is the current production release: **single city, one deployment**.
The work sitting in the `dev-1.6.x` → `dev-1.8.x` chain changes the shape of the product — 6 cities,
per-city compose projects, per-city databases, per-city S3 buckets, a dedicated backup service, run
bookkeeping, and a fleet watchdog. Deployment topology, operational commands, and the S3 bucket
convention all change.

That is a major-version change by any reasonable definition, so **2.0.0 is the right number**.

---

## 2. Branch review — what actually exists

### 2.1 The critical finding

**The multi-city chain forked from `main` before `v1.5.12` existed, and has never taken any `main`
work since.**

```
d775826  2025-09-29  Merge PR #380 (dev-1.5.10)   <-- fork point
   |
   |                                    main ─────────────────────────────► 9a2ded9
   |                                     ├── v1.5.11  (2026-05)
   |                                     ├── v1.5.12  (2026-05-01)  ← PRODUCTION
   |                                     └── 70 commits not in the dev chain
   |
   └── dev-1.6.0 ─ … ─ dev-1.6.9 ─ dev-1.7.1 ─ … ─ dev-1.7.8 (14c81e8)
                                                        ├── dev-1.8.1 … dev-1.8.5   (M8: pandas removal, 5 commits)
                                                        └── dev-1.7.8.1 … .3        (logs/backup/monitoring, 14 commits)
```

Verified facts:

| Check | Result |
|---|---|
| `v1.5.12` ancestor of `main`? | **Yes** |
| `v1.5.12` ancestor of `dev-1.7.8.3`? | **No** |
| Fork point | `d775826`, 2025-09-29 (PR #380) |
| `main` commits missing from the dev chain | **70** |
| Dev-chain commits missing from `main` | **78** (`dev-1.7.8.3`), 69 (`dev-1.8.5`) |
| Any `dev-1.6/1.7/1.8` branch merged to `main`? | **No — none** |
| Files modified on **both** sides since the fork | **14** (the conflict set) |

**Consequence:** shipping 2.0.0 from the dev chain as-is would silently revert ten months of `main`
work, including both released versions `v1.5.11` and `v1.5.12`. This is the single most important
constraint on the release, and Item **I-1** exists to address it.

### 2.2 What `main` has that the dev chain lacks

Sampled from the 70 commits — these are real regressions if lost:

| Area | Examples |
|---|---|
| **OOM / memory fixes** | gc after each module, `--limit-max-requests 30`, `file_downloader` memory optimisation, explicit DataFrame release, memory-usage logging |
| **Runtime bump** | `python:3.11-slim-bookworm` — the dev chain is still on **`python:3.8-slim-buster`** (both Python and Debian EOL) |
| **Resource leaks** | logging handlers closed on shutdown (fd leak) |
| **Data integrity** | `ValueError` raise restored in `validate_list_lengths` (prevented silent data loss) |
| **Email report** | avg_price correction, room segments, EUR labels, date format, `[NEW]` marker, report header |
| **Release plumbing** | dynamic `RELEASE_VERSION` + `APP_ENV` injection |
| **AWS correctness** | Secrets Manager and `get_last_s3_file.sh` pinned to `eu-west-1` |
| **CI/CD** | workflows consolidated to `main.yml` + `staging.yml`, Dependabot, Actions on Node 24 |

### 2.3 The conflict set (14 files changed on both sides)

```
docker-compose.yml                Makefile                    README.md
scripts/get_last_s3_file.sh       src/ts/Dockerfile           src/ts/ts.py
src/ws/app/main.py                src/ws/requirements.txt
src/ws/app/wsmodules/{analytics,aws_mailer,data_format_changer,db_worker,df_cleaner,file_downloader}.py
```

The five `wsmodules` files are the hard part: `main` modified them for memory-leak fixes while
`dev-1.8.x` **rewrote them to remove pandas entirely**. These conflicts cannot be auto-resolved and
must be reviewed line by line by someone who understands both intents.

| | `main` | `dev-1.7.8.3` | `dev-1.8.5` |
|---|---|---|---|
| pandas in `requirements.txt` | present | present | **removed** |
| ws base image | `3.11-slim-bookworm` | `3.8-slim-buster` | `3.8-slim-buster` |

### 2.4 Other unmerged branches

| Branch | Ahead/behind `main` | Assessment |
|---|---|---|
| `dev-1.5.13`, `feature/after-pr-427`, `feature/ws-extract-view-cnt`, `bugfix-wip-view-count-value-still-1` | 12–13 ahead, **0 behind** | The `view_count` extraction line, based on **current `main`**. Merges cleanly. Independent of multi-city — decide in/out (**D-2**). `bugfix-wip-view-count-value-still-1` is the tip and is marked WIP. |
| `chore/reorganize-plan-docs` | 3 ahead, 0 behind | Moves docs into `docs/`. **Overlaps** commit `6011e64` on `dev-1.7.8.3`, which just did the same thing. Reconcile or drop (**I-6**). |
| `chore/xargs-empty-input-cleanup` | 1 ahead, 3 behind | Small, safe. Merge or drop. |
| `refactor/aws-mailer-architectural-cleanup` | 3 ahead, 6 behind | Overlaps `aws_mailer.py`, already in the conflict set. Decide before integration starts. |
| `issue-378-awsmailer-docs` | 0 ahead, 72 behind | Dead. Delete. |

### 2.5 CI is not running on any of this

`CI.yml` on the dev chain triggers on `branches: ['dev-1.4*.*']` only. Every `dev-1.6.x`,
`dev-1.7.x` and `dev-1.8.x` branch has therefore **never run CI** — despite the chain having grown
to **25 test files** (`tests/test_08_module_scrape_runs.py` … `test_21_m7_p9_logging.py`,
`test_m6_backup_restore.py`). The dev chain also still carries 8 workflow files, including stale
`CICD-dev-1.5.3.yml`-era ones that `main` already consolidated away.

**No one has ever seen these 25 test files pass in CI.** Item **I-2** is therefore a hard gate: the
test suite must be proven green before the integration merge, not after.

---

## 3. Integration strategy

Three options were considered:

| Option | Approach | Verdict |
|---|---|---|
| **A** | Integration branch from the dev chain; merge `main` **into** it; resolve conflicts there; then one PR back to `main` | **Recommended** |
| B | Merge dev chain directly into `main` | Rejected — resolves 14-file conflicts on the release branch; `main` is unreleasable while in progress |
| C | Rebase 78 dev commits onto `main` | Rejected — re-resolving the same conflicts across 78 commits, and it rewrites published history on 14 shared branches |

**Option A**, concretely:

```
release-2.0.0  ← branch from dev-1.7.8.3
   1. merge origin/dev-1.8.5        (unite the two forks: M8 pandas + logs/backup/monitoring)
   2. merge origin/main             (recover the 70 commits — the conflict-heavy step)
   3. verify, test, deploy to staging
   4. single PR → main, tag v2.0.0
```

Rationale: multi-city is the future trunk, so it stays the base. `main` stays releasable for
hotfixes throughout. Conflicts are resolved exactly once, on a throwaway-able branch, with both
sides' history intact for `git log --follow`.

---

## 4. Actionable item list

Priority: **P0** blocks the release · **P1** required for 2.0.0 · **P2** should be in · **P3** defer.

### Phase 0 — Decisions (do first; they change everything downstream)

| ID | Item | Priority | Notes |
|---|---|---|---|
| **D-1** | Confirm integration direction (Option A above) | P0 | Everything else assumes it |
| **D-2** | Decide whether the `view_count` line (`dev-1.5.13`) is in 2.0.0 | P0 | It is `main`-based and merges cleanly, but its tip is WIP. Recommend: **defer to 2.1.0** — do not add a second large integration to an already conflict-heavy merge |
| **D-3** | Decide whether M8 pandas removal (`dev-1.8.5`) ships in 2.0.0 | P0 | Recommend **yes** — deferring means resolving the same `wsmodules` conflicts twice. But it materially enlarges the test surface |
| **D-4** | Confirm the Python 3.11 + bookworm base wins over the dev chain's 3.8/buster | P0 | Recommend **yes, unconditionally** — 3.8 and buster are both EOL. Requires the pandas-free code to be validated on 3.11 |
| **D-5** | Decide the fate of `refactor/aws-mailer-architectural-cleanup` and `chore/reorganize-plan-docs` | P1 | Both overlap files already in the conflict set |
| **D-6** | Freeze feature work on the dev chain for the duration of integration | P1 | New commits on `dev-1.7.8.x` during the merge will re-open resolved conflicts |

### Phase 1 — Pre-integration hardening (before any merge)

| ID | Item | Priority | Acceptance criteria |
|---|---|---|---|
| **I-1** | Write down the full inventory of the 70 `main` commits and classify each as *must-preserve* / *superseded by multi-city* / *irrelevant* | **P0** | A checklist table; every OOM, leak, data-integrity and email fix from §2.2 explicitly marked and later verified present in the merge result |
| **I-2** | Make CI run on the dev chain and get all 25 test files green | **P0** | `CI.yml` trigger covers `dev-1.*` and `release-*`; a green run recorded on `dev-1.7.8.3` **before** any merge, so failures after the merge are unambiguously merge-caused |
| **I-3** | Deploy the `pg_dump` cron fix (`c9d4daf`) to production | **P0** | Independent of the release. Backups have been failing since ≥2026-07-22; the fix is committed but **not deployed**. Rebuild with `--no-cache` (shared `sslv-backup:latest` + `cache_from`), then confirm fresh objects in all 6 buckets |
| **I-4** | Capture a verified pre-release backup of all 6 production databases and prove one restores | P0 | `make e2e-backup-restore` passes; depends on I-3 |
| **I-5** | Record a rollback plan to `v1.5.12` | **P0** | Written procedure covering DB state: 2.0.0 adds the `scrape_runs` table and changes bucket layout, so rollback is **not** just redeploying the old image. Must state explicitly whether rollback is even possible after first multi-city run |
| **I-6** | Reconcile the duplicate docs move (`chore/reorganize-plan-docs` vs `6011e64`) | P1 | One wins; the other is deleted before integration |
| **I-7** | Delete dead branches (`issue-378-awsmailer-docs`, and any `dev-1.6.x`/`dev-1.7.x` intermediate no longer needed) | P2 | 14 stale remote branches are a navigation hazard; keep the tips, drop the rest |

### Phase 2 — Integration

| ID | Item | Priority | Acceptance criteria |
|---|---|---|---|
| **M-1** | Create `release-2.0.0` from `dev-1.7.8.3` | P0 | Branch exists, pushed, CI green (I-2) |
| **M-2** | Merge `origin/dev-1.8.5` into it — unites the two forks off `dev-1.7.8` | P0 | Conflicts expected in the 5 pandas-touched `wsmodules`. Test suite green afterwards |
| **M-3** | Merge `origin/main` into it — the 70 commits | **P0, hardest step** | All 14 conflict-set files resolved with both intents preserved; I-1 checklist fully ticked; suite green |
| **M-4** | Reconcile `requirements.txt` and both Dockerfiles | P0 | Python 3.11 + bookworm (D-4), pandas absent if D-3 is yes, and the image actually builds |
| **M-5** | Reconcile `docker-compose.yml` | P0 | Multi-city structure retained, `main`'s healthcheck and worker-churn tuning preserved. Worth folding in the P1/P2 fixes from `docs/M6_production_monitoring_recommendations.md` (backup healthcheck, log rotation) while the file is already open |
| **M-6** | Consolidate workflows to `main.yml` + `staging.yml`, delete the 6 stale `CICD-*.yml` | P1 | Dev chain matches `main`'s CI layout; deploy pipeline is multi-city aware |
| **M-7** | Reconcile `README.md` + `CLAUDE.md` for multi-city as the default | P1 | No single-city-only instructions remain; bucket conventions and city onboarding documented |

### Phase 3 — Verification (the gate to release)

| ID | Item | Priority | Acceptance criteria |
|---|---|---|---|
| **V-1** | Full test suite green on `release-2.0.0` | **P0** | All 25 files, in CI, not just locally |
| **V-2** | Clean-host deploy rehearsal for all 6 cities | **P0** | `./deploy-multi-city-ws.sh` on a fresh EC2; 24/24 containers healthy. Note `up -d` currently returns before healthchecks pass (see A8 in the monitoring doc) — verify health explicitly, do not trust the script's success count |
| **V-3** | End-to-end pipeline run per city | **P0** | `/run-task/{city}` → `scrape_runs.status = 'success'`, non-zero `urls_discovered`, report email received, for all 6 |
| **V-4** | Confirm every I-1 *must-preserve* fix survived the merge | **P0** | Explicit re-check of the OOM, fd-leak, `validate_list_lengths`, and email-report fixes — these are the regressions a passing test suite is least likely to catch |
| **V-5** | Backup + restore proven on the release build | P0 | `make e2e-backup-restore` on the release image |
| **V-6** | 72-hour staging soak | P1 | 3 consecutive nightly cycles: 6 scrapes + 6 backups + 6 reports per night, no alerts |
| **V-7** | Memory check under 6-city load | P1 | Compare against `docs/M6_memory_usage_assesment.md`; the host has no container memory limits yet (A6) |

### Phase 4 — Release

| ID | Item | Priority | Acceptance criteria |
|---|---|---|---|
| **R-1** | One PR: `release-2.0.0` → `main` | P0 | Reviewed; CI green; description links this plan |
| **R-2** | Tag `v2.0.0` on `main` | P0 | Tag matches the deployed image; `RELEASE_VERSION` set accordingly |
| **R-3** | Write `CHANGELOG` / release notes covering `v1.5.12` → `2.0.0` | P1 | Breaking changes first: deployment topology, per-city buckets, new env vars, `scrape_runs` table, `collect_logs_v2` deprecation |
| **R-4** | Migration guide for the existing single-city production instance | **P0** | The one item most likely to be forgotten: how the current live deployment becomes city `ogre` without data loss. Covers volume/bucket naming and DB restore |
| **R-5** | Production cutover with per-city rollout | P0 | One city first, verify a full nightly cycle, then the rest. Not all 6 at once |
| **R-6** | Post-release: adopt Phase 0 of the monitoring plan | P1 | The false-healthy fixes from `docs/M6_production_monitoring_recommendations.md` — without them the new deployment reports healthy when it isn't, exactly as in the July backup outage |

---

## 5. Risk register

| Risk | Impact | Mitigation |
|---|---|---|
| Silent regression of `main`'s 70 commits | **High** — reintroduces fixed OOM crashes, fd leaks, data loss, email errors | I-1 inventory + V-4 explicit re-check. Do not rely on the test suite alone |
| `wsmodules` conflicts resolved wrongly (memory fixes vs pandas removal) | **High** — corrupted analytics with no loud failure | M-2/M-3 line-by-line review; golden-file harness from `da71a67` (M8 Phase 1) |
| 25 test files never run in CI | **High** — unknown baseline; post-merge failures ambiguous | I-2 as a hard gate before merging |
| Rollback may be impossible after first multi-city run | **High** | I-5 written up-front, before cutover, not during an incident |
| Python 3.8 → 3.11 with pandas removed simultaneously | Medium | D-4 + V-1; two large changes landing together, so keep them separately verifiable |
| Integration drags while dev branches keep moving | Medium | D-6 freeze |
| Backups still failing in production **right now** | **High** | I-3 — do this today; it does not need the release |

---

## 6. Recommended sequence

1. **Today, independent of the release:** I-3 (deploy the backup fix) and I-4 (verified backups).
   Production has had no working backup since 2026-07-22.
2. **Decisions:** D-1 … D-6.
3. **Gates:** I-1, I-2, I-5.
4. **Integration:** M-1 → M-7, keeping the suite green at each step.
5. **Verification:** V-1 … V-7.
6. **Release:** R-1 … R-6, one city at a time.

Deliberately *not* estimated in days — the M-3 conflict resolution dominates the schedule and its
size is not knowable until the 14-file conflict set is actually opened. Estimate after I-1.

---

## 7. Open questions for the maintainer

1. **D-2** — is the `view_count` work (`dev-1.5.13`, 12 commits, `main`-based) in 2.0.0 or 2.1.0?
   Its tip is explicitly WIP.
2. **D-3** — does M8 pandas removal ship in 2.0.0, or does 2.0.0 go out as multi-city only and M8
   becomes 2.1.0?
3. **R-4** — does the existing single-city production instance get migrated in place, or is 2.0.0 a
   clean deployment with a restore from backup?
4. Is there a staging environment able to run 6 cities, or does V-6's soak have to happen on the
   production host?

---

## 8. Related documents

| Document | Relevance |
|---|---|
| `docs/M6_production_monitoring_recommendations.md` | R-6, M-5; the false-healthy fixes to fold in |
| `docs/M6_MVP_problem_list.md` | Known multi-city risks; cross-check before release |
| `docs/m8_refactor_remove_pandas.md` | The `dev-1.8.x` work being integrated (D-3) |
| `docs/M7_ws_scaling_blocker_problems.md` | Scaling limits at 6 cities |
| `docs/M6_phase_1_backup_restore_service_plan.md` | I-4, V-5, R-4 backup/restore procedures |
| `docs/m6-dynamic-page-count-action-plan.md` | Multi-city scraping behaviour being released |
