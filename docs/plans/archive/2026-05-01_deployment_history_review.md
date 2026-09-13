# Deployment History Review
Generated: 2026-05-01

---

## How deployments work

**Production** (`main.yml`): Auto-triggered on every `push` to `main` that touches `.py`, `Dockerfile`, `docker-compose.yml`, `Makefile`, or `src/**`. Also triggerable manually (`workflow_dispatch`). Deploys to the production EC2 instance (secret: `PROD_M5_EC2_IP`). Always deploys the `main` branch — no branch selection.

**Staging** (`staging.yml`): Manual only (`workflow_dispatch`). Takes a branch name as input, so any branch can be tested. Deploys to a separate staging EC2 (secret: `DEV_EC2_IP`). Runs tests + a full Docker build-verify cycle (downloads real DB backup from S3, starts all containers, tears them down) before SSH-deploying.

---

## Production — Last Successful Deployment

**Date**: 2026-03-22 at 19:04 UTC  
**Trigger**: Auto-push when PR #400 was merged into `main`  
**Commit deployed**: `09a7e3b` — "Merge PR #400 from vfedotovs/dev-1.5.11 into main"

### What was in this deployment (all commits from dev-1.5.11):

| Commit | What it did |
|--------|-------------|
| `b336259` | `(cicd)` Auto-detect `docker compose` vs `docker-compose` in Makefile — fixes cross-platform compatibility |
| `8a68e10` | `(cicd)` Use `S3_BUCKET` env var in cron upload script instead of hardcoded bucket name |
| `3fcdf93` | `(cicd)` Bump GitHub Actions to Node.js 24 compatible versions |
| `abcad44` | `FEAT` Implement health checks for `ws` and `ts` containers (Docker `HEALTHCHECK` directive + `/health` endpoint in `ts.py`) |
| `63e2f6a` | `(cicd)` Bump base image from Python 3.8-slim-buster → 3.10-slim-bookworm in both `ts` and `ws` Dockerfiles |
| `f0f7a77` | `(docs)` Update README with current badges and setup instructions |

**Reasoning**: This was the culmination of the dev-1.5.11 sprint. The core feature was adding container health checks (Issue #371) so Docker knows whether the `ws` and `ts` services are actually responding before marking them healthy. The Python base image bump was bundled in (3.8 was EOL). The CI/CD fixes resolved a cross-platform `docker-compose`/`docker compose` ambiguity that had been causing local Makefile failures on macOS.

---

## Production — Deployment After That (docs-only, no code trigger)

**Date**: 2026-03-22 at 19:30 UTC  
**Trigger**: PR #401 merged — "Remove staging badge from README"  
**Commit**: `c1659ec`  
**Note**: This merged only `README.md` (1 line deleted — the staging badge). The `main.yml` path filter does NOT include `README.md`, so **this did NOT trigger a production deploy**. The production EC2 still runs the `09a7e3b` deployment from 19:04.

---

## Staging — Last Successful Deployment

**Date**: 2026-03-24 at 20:33 UTC  
**Trigger**: Manual `workflow_dispatch` on `main`  
**Commit deployed**: `c1659ec` — "Merge pull request #401 from vfedotovs/bugfix/401-remove-staging-badge"  
**Branch**: `main`

**Reasoning**: Two days after the production deploy, staging was re-deployed from `main` to verify the full stack (including the README-only PR #401 state) was clean. This was likely a smoke-test or baseline reset of the staging environment after the dev-1.5.11 work.

### The cancelled staging run just before it:
At 20:27 UTC on 2026-03-24, a staging deploy was dispatched for branch `feature/tune-healthcheck-limits` (commit `69a8683`) — this is PR #403 (increase `--limit-max-requests` 30→1000 and health check interval 30s→60s). It was **cancelled** before completing. The successful `main` deploy at 20:33 replaced it. **PR #403 was never fully deployed to staging and validated** — this is why it remains open.

---

## Production — Failed Attempts Before the Successful One

### 2026-03-21 16:46 UTC — Manual trigger, `07ee492`
**Failed with SSH exit code 255** — could not connect to the production EC2 instance at all. The SSH step printed the usage/help text for the `ssh` command, which means the `PROD_M5_EC2_IP` secret was empty or the key was invalid at that moment. This was likely the first attempt after workflows were restructured (PR #398 had just been merged, which consolidated `main.yml` + `staging.yml`).

### 2026-03-21 16:45 UTC — Also SSH exit code 255
Same issue, second attempt within 1 minute. Likely a repeat trigger or rapid retry.

### 2026-03-22 17:37 UTC — Auto-push trigger, `53c2963` (PR #399)
**Failed with SSH exit code 255** — same SSH connection failure. This was the auto-deploy triggered when PR #399 landed. The EC2 was likely stopped or the secret was still wrong.

---

## Staging — The dev-1.5.11 Validation Session (2026-03-22)

Between 17:40 and 18:45 UTC on 2026-03-22, there were 7 staging runs against `dev-1.5.11`:

| Time (UTC) | SHA | Result | Notes |
|------------|-----|--------|-------|
| 17:40 | `e64a88f` | Failure | SSH exit code 255 — staging EC2 also unreachable |
| 17:42 | `e64a88f` | Failure | Same issue |
| 17:50 | `main` branch | Failure | Tried main, still SSH failure |
| 17:55 | `b336259` | **Success** | EC2 back up, first successful staging run |
| 18:27 | `b336259` | **Success** | Repeat validation |
| 18:31 | `b336259` | **Success** | Third validation pass |
| 18:41 | `b336259` | Failure | One failure in between (likely transient) |
| 18:45 | `b336259` | **Success** | Final staging green — proceeded to merge PR #400 to main |

**Reasoning**: The early failures at 17:40–17:50 were an SSH connectivity problem (same as production). Once the EC2 became reachable at ~17:55, staging was run repeatedly to build confidence in the health check and Docker image bump changes before merging to production. Three consecutive successes triggered the production merge.

---

## Earlier Production History

### 2025-06-29 — Last production deploy before the 2026 work
**Commit**: `160b66c` — "Merge pull request #369 from vfedotovs/vfedotovs-patch-1"  
Between this and the 2026-03-22 deploy, the following major work was done but **only ever reached CICD-dev-1.5.* branch testing**, never production:
- OOM/memory leak hotfixes (gc, `--limit-max-requests 30`, remove pdf_creator, memory logging)
- Migration from SendGrid → AWS SES mailer
- New cron docker service
- Rollback documentation and scripts

These were all merged through `dev-1.5.10` → `main` via PR #380 and then the dev-2026.01.31 branch → PR #398. They eventually landed in the 2026-03-22 production deploy via PR #399 and PR #400.

---

## Summary Table

| Date | Environment | Branch/Commit | Result | What was deployed |
|------|-------------|---------------|--------|-------------------|
| 2026-03-24 | **Staging** | `main` @ `c1659ec` | ✅ Success | README-only state; baseline smoke test |
| 2026-03-22 | **Production** | `main` @ `09a7e3b` | ✅ Success | Health checks, Python 3.10 base, CI/CD fixes |
| 2026-03-22 | Staging | `dev-1.5.11` (×4) | ✅ Success | Pre-merge validation of dev-1.5.11 |
| 2026-03-22 | Staging | `dev-1.5.11` (×3) | ❌ Failed | SSH connectivity (EC2 unreachable) |
| 2026-03-21 | Production | `main` @ `07ee492` | ❌ Failed | SSH connectivity (EC2 unreachable) |
| 2025-06-29 | Production | `main` @ `160b66c` | ✅ Success | Previous production baseline |

---

## What is NOT yet in production

PR #403 (`feature/tune-healthcheck-limits`) was never successfully deployed to staging and never merged. Its changes — raising `--limit-max-requests` from 30 to 1000 and increasing health check interval to 60s — are the primary remaining fix for the memory leak situation. **Deploying this is the highest-priority next action.**
