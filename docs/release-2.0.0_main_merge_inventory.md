# Release 2.0.0 — `main` → `release-2.0.0` merge inventory

**Item:** B-1 in [`staging_review_dev-1.7.9.23.md`](staging_review_dev-1.7.9.23.md), which is I-1 and M-3 in [`RELEASE_2.0.0_action_plan.md`](RELEASE_2.0.0_action_plan.md).
**Branch:** `release-2.0.0`, created from `dev-1.7.9.23` (`43796a4`), with `origin/main` (`0f598b3`) merged in.
**Fork point:** `d775826` (2025-09-29). `main` had 49 commits of real work since then, plus 3 Dependabot bumps.
**Date:** 2026-10-11.

Every `main` commit is listed below with what happened to it in the merge:

- **Kept:** in the result as it was on `main`.
- **Ported:** `main`'s intent re-applied to the multi-city code.
- **Superseded:** the multi-city chain already does this differently.
- **Dropped:** deliberately not carried over, with the reason.

---

## 1. Must-preserve fixes (V-4 re-check list)

| Commit | What | Result | Where |
|---|---|---|---|
| `ce41b58` | `validate_list_lengths` raises `ValueError` again (silent data loss) | **Kept** | `data_format_changer.py` |
| `cee3b32` | `del df` + `gc.collect()` after each DataFrame use | **Ported** | `data_format_changer.py`, `df_cleaner.py`, `db_worker.py` |
| `92221dc` `8debdfa` | `gc.collect()` + RSS log after every pipeline module | **Ported** | `main.run_pipeline_stages`: after every stage, also on failure (`finally`) |
| `9b9b9e6` | `file_downloader` per-request S3 client, list cleanup | **Kept** | `file_downloader.py` (auto-merged) |
| `6e30879` | close logging handlers at exit (fd leak) | **Kept** | `main.py` (auto-merged) |
| `68f15d2` | `avg_price` = mean, not (min+max)/2; all room segments | **Kept** + **Superseded** | mean in `analytics.py`. Segments: the chain's `7a91f2d` already lists 1–4 always plus any larger count |
| `c959e56` | month label fix; duplicate DB print; readable labels | **Kept** / **Superseded** | month label in `df_cleaner.py`. DB print and labels were in `scraped_and_removed.txt`, which `scrape_runs` replaced |
| `3f1fc7a` | report header (date), total count, `[NEW]` marker | **Ported** | `create_email_body`. Header titled per city via `EMAIL_CITY_TITLE` (was "Ogre") |
| `810e49f` | `EUR` labels; DD.MM.YYYY; street abbreviations | **Ported + fixed** | labels kept. `normalise_street`'s patterns never matched "pr. 12" (trailing `\b` after the dot), so that is fixed |
| `948566a` | DQ-2 street counts, CODE-2 `shutil`, CODE-3/4 `__main__` guards, UX-5 `tabulate` rows | **Kept** / n/a | `shutil` + guards present. DQ-2 and UX-5 are **not on `main`'s tip either**, despite the commit message: nothing to carry |
| `16ecc33` `49916ca` `630ff13` | dynamic `RELEASE_VERSION` + `APP_ENV` | **Ported** | `aws_mailer.gen_subject_title`: per-city title + version + env (the chain hard-coded `"1.6.0"` and repeated the title). `APP_ENV` in compose; CI injection in `main.yml`/`staging.yml` |
| `2277520` `9cc8efc` | pin AWS calls to `eu-west-1` | **Kept** + **Ported** | `load_secrets.sh`/`set_s3_env_from_aws_sm.sh` auto-merged. `get_last_s3_file.sh` (rewritten per city on the chain) now pins all 3 calls via `AWS_RES_REGION` |
| `0bbc231` `63e2f6a` | `python:3.11-slim-bookworm` for `ws` and `ts` | **Kept** | closes **B-2**. Both images build and import on 3.11.17 |
| `b3d98d8` | `SENDGRID_API_KEY` removed | **Kept** | `sendgrid` also dropped from `requirements.txt` (no imports left) |

## 2. Runtime / deployment

| Commit | What | Result | Why |
|---|---|---|---|
| `48641b4` `03db23c` `3aa9a0a` `69a8683` | uvicorn `--workers 2 --limit-max-requests 30→1000`, healthcheck 60 s | **Dropped** (workers/limit), **Ported** (`/health`) | The chain runs the pipeline in a daemon thread behind an in-process `threading.Lock`. A second worker has its own lock, so runs could overlap. A max-requests recycle would kill a run mid-way and leave it `running`. The memory growth those flags worked around is handled by per-stage gc. Healthcheck uses `/health` at 30 s: `ts` waits on it, and 60 s would add up to a minute per city to every deploy |
| `abcad44` | `ws`/`ts` health checks | **Kept** / **Superseded** | `/health` on ws kept. `ts` already had the same server. `ts` port `8080:8080` **not** published: six cities would clash on the host port |
| `52c2079` `8a68e10` | `cron` service (Docker socket, single-city backup) | **Dropped** from compose | Replaced by the per-city `backup` service. Without a profile it would start in all six city projects with the Docker socket. **`src/cron/` files are kept but unused**: delete, or adopt its stats scripts, as a follow-up |
| `ce9fcd8` | remove PDF generation | **Superseded** | the chain removed it too (`8eea050`) |
| `0ab93c2` `b336259` `5bfcafa` | Docker Compose v2 / auto-detect | **Ported** | `Makefile` `COMPOSE ?=` (detection fixed: `main` used `command -v docker compose`, which passes on `docker` alone). `build`/`up`/`down` use it. `logs` target restored |
| `6ed7496` `cd45e7a` `5fd7cf6` `33c1cff` `16feaf7` | `Makefile` precheck/setup/test/venv targets | **Superseded** | The chain's `Makefile` is reorganised: `dev-setup`, `test`, `test-cov`, `_setup-precheck`, kebab-case `fetch-*`. `main`-only `ec2_precheck`, `setup-venv`, `test-venv`, `install-dev`, `venv-info` are not carried. `docs/TESTING_SETUP.md` still names them: update in M-7 |

## 3. CI/CD

| Commit | What | Result | Notes |
|---|---|---|---|
| `2dbb0bf` | consolidate to `main.yml` + `staging.yml` | **Kept** | The 7 old workflows are deleted. The chain's only change to them (`httpx` for `TestClient`, `73b2123`) is ported into both new workflows |
| `fdca561` `3fcdf93` + Dependabot | Node 24 actions, `dependabot.yml`, action bumps | **Kept** | |
| `16ecc33` (CI part) | version from git tags → `.env.prod` | **Kept** | but see blocker R-0 below |

## 4. Docs and scripts (kept as-is)

`docs/ROLLBACK_*.md`, `scripts/rollback/` (`4749daf`), `docs/TESTING_SETUP.md`, `docs/git_recommended_workflow.md`, `docs/github_workflows_todo.md`, `docs/test_diagrams.md`, `docs/roadmap/s3_env_strategy_todo.md`, `memory_leak_fix_todo.md`, `todo_dynamic_versioning.md`, `setup_ec2_arm_instance.sh`, `scripts/deploy_arm_ec2_instance.sh`, `scripts/list_ec2_instances.sh`, `scripts/load_secrets_v2.sh`, README badges (`f0f7a77`, `8549965`).

All of these describe the **single-city** deployment. The rollback guide is the starting point for I-5, but it must be rewritten for per-city projects and the `scrape_runs` table.

---

## 5. New blockers found during the merge

- [ ] **R-0 — `main.yml` would deploy single-city code to production on the first push after R-1.** It triggers on every push to `main`. It force-removes **all** containers **and images** on the production host, clones `main`, and runs `make setup && make build && make up`, the single-project stack. Merging `release-2.0.0` into `main` as-is would replace production with a one-city deployment. Before R-1, either make `Deploy` `workflow_dispatch`-only, or rewrite it around `deploy-multi-city-ws.sh` with per-city rollout (R-5). Its `Test` job also runs pytest with `continue-on-error: true` on Python 3.9, so tests never gate the deploy: set it to 3.11 and let failures fail.
- [ ] **README (M-7):** the top half, auto-merged from `main`, still describes the single-city `make setup/build/up` flow. The multi-city sections below it are current.

## 6. Verification on the merge result

- Full suite: **392 passed** (384 existing + 8 in `tests/test_33_release_2_0_0_merge.py` for the combined subject, report header, `[NEW]`/`EUR` rows, street normaliser, and per-stage gc).
- `docker compose config` valid. `make help`, `make -n build up down logs` OK.
- `ws` and `ts` images build on `python:3.11-slim-bookworm`. All ws modules and `ts` import on 3.11.17, and `ws` answers `/health`.
- **Not done yet:** staging deploy of `release-2.0.0` and the 3-night soak (V-2, V-3, V-6), memory check on 3.11 (V-7), and backup image B-3 (separate branch `bugfix/backup-python-3.11`, stashed).
