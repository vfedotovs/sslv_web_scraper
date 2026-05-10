# Next Session Action Items
Generated: 2026-05-01

## Current State Summary

- **Active branch**: `dev-1.5.11` (on par with `main`, no divergent commits)
- **Latest merged**: PR #401 (remove staging badge from README), dev-1.5.11 → main (PR #400)
- **Open PRs**: 3 (all documentation/config, none merged yet)
- **Open issues**: 30+ tracked in GitHub

---

## Priority 1 — Open PRs (merge or close)

| PR | Title | Action |
|----|-------|--------|
| #403 | Tune health check interval and request limit | **Review & merge** — increases `--limit-max-requests` 30→1000, health check 30s→60s. Staging test checklist incomplete. |
| #404 | Add S3 env strategy roadmap for multi-env and multi-city | **Review & merge** — docs only, no code changes |
| #402 | Add integration and E2E test diagrams | **Review & merge** — docs only, no code changes |

---

## Priority 2 — Active Bug: Memory Leak (Issue #394)

Tracked in `memory_leak_fix_todo.md`. Partial fixes already shipped (OOM hotfix branch, `--limit-max-requests 30`, gc calls). Remaining work:

- [ ] **Merge PR #403** — raise `--limit-max-requests` from 30 to 1000 (health checks were triggering restarts 48×/day unnecessarily)
- [ ] **Audit wsmodules for DataFrame leaks** — `data_format_changer.py`, `df_cleaner.py`, `db_worker.py` all have unreleased DataFrames (see issue #394 root cause analysis)
- [ ] **Fix logging handler accumulation** — 8 modules × 2 handlers each, never closed; add `atexit` cleanup (step 5 in `memory_leak_fix_todo.md`)
- [ ] **Add `/health` memory stats endpoint** — already specced in `memory_leak_fix_todo.md`, not yet implemented
- [ ] **Set CloudWatch alarms** for memory > 1.5 GB and container restarts

---

## Priority 3 — Milestone 6 Remaining Tasks (Issue #383)

- [ ] Review `docker-compose.yml` for security and best practices
- [ ] Review code test state and implement more tests (see PR #402 test diagrams as design reference)

---

## Priority 4 — Dependency Upgrades (Issues #395, #396)

- [ ] **Bump Python 3.8 → 3.11** in `ts` and `ws` container Dockerfiles (Issue #396 — 3.8 is EOL)
- [ ] **Bump GitHub Actions checkout v4 → v6** (Issue #395)

---

## Priority 5 — Feature Work (backlog)

| Issue | Title | Notes |
|-------|-------|-------|
| #393 | Dynamic email title based on env variable | Medium priority |
| #391 | Refactor report email body sections | Medium priority |
| #389 | New GitHub Action for dev-1.6 branch | Needed before 1.6 dev starts |
| #387 | Monitoring docker container (no cron dependency) | Architectural improvement |
| #386 | DB backup docker service (no cron dependency) | Architectural improvement |
| #385 | Multi-city scrape + multi-bucket backup | Major feature |
| #365 | Email report: new listed ads per date category | Feature improvement |
| #352 | Implement Traceback capture in app log files | Observability |
| #347 | Feature flags implementation | Platform feature |
| #349 | Multi-city deploy without port conflicts | Infrastructure |

---

## Priority 6 — Known Bugs (backlog)

| Issue | Title | Notes |
|-------|-------|-------|
| #392 | GH Actions fail when dev branch merges into main | CI/CD reliability |
| #353 | DeprecationWarning in bs4 method (`web_scraper.py`) | Low risk but will break on future bs4 update |
| #348 | Skip email flag via API gateway as default | Behavioral bug |
| #344 | FastAPI Response: None | Investigate |
| #346 | S3 botocore AuthorizationHeaderMalformed | Auth/credential issue |

---

## Suggested Next Session Order

1. Merge PR #403, #404, #402 (quick wins, already written)
2. Fix memory leak DataFrame cleanup in `data_format_changer.py`, `df_cleaner.py`, `db_worker.py`
3. Fix logging handler accumulation (atexit cleanup)
4. Bump Python 3.8 → 3.11 in Dockerfiles
5. Bump GH Actions checkout to v6
6. Review `docker-compose.yml` security (Milestone 6 checkpoint)
