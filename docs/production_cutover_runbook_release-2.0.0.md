# Production cutover runbook — `release-2.0.0` (v2.0.0)

**Items:** R-4 (migrate the single-city production instance) and R-5 (per-city rollout) of
[`RELEASE_2.0.0_action_plan.md`](RELEASE_2.0.0_action_plan.md). Rollback is I-5.
**Host:** `main-branch-production` (`i-01a2559301e9e65b4`, eu-west-1).
**Status:** draft, 2026-10-12. Step 0 inventory taken on the live host 2026-11-25 (below); host prepared the same day (disk, swap).
Step 0 collects the facts the later steps depend on.

The cutover runs **by hand on the host** in `~/sslv-prod`, the same directory `main.yml` deploys into
later. Once all six cities run, normal deploys go through `main.yml`.

Every manual `make deploy-prod` below passes `DEPLOY_APP_ENV=production`, the value `main.yml` uses, so the
report subjects end in `[production]` either way. Without it a manual deploy uses `M6_ENV` (`[prod]`). The
version comes from `git describe`: `v2.0.0` on the tag.

---

## What changes

| | Before (v1.5.12, single-city M5) | After (v2.0.0, multi-city) |
|---|---|---|
| Stack | One compose project, named after its deploy folder (`<time>-deploy`): `db`, `ws`, `ts`, maybe `cron` | Six projects, `<city>-{db,ws,ts,backup}-1` |
| Data | One DB, Ogre only: `listed_ads`, `removed_ads` | One DB per city, plus a `scrape_runs` table |
| DB volume | `<time>-deploy_db_data` | `<city>_db_data` |
| Backups | M5 path (`cron` service / `S3_BUCKET`) | `<city>-backup-1` at 02:00 → `sslv-prod-<city>-db-backups` |
| Config | `load_secrets.sh` + M5 bucket | `s3://sslv-prod-m6-cicd-files/` (`.env.prod`, `database.ini`, `.env.<city>`) |
| Monitoring | none | systemd watchdog + ntfy (prod topic) |
| Python | 3.11 (`main`) | 3.11 (ws, ts, backup) |

The two stacks use **different volumes and project names**. Starting the new stack does not touch the old one, and the old
one can be started again for rollback. The risks are both stacks scraping or emailing at once, and losing
Ogre's history. The steps below handle both.

## Prerequisites (go/no-go)

- [x] Staging sign-off complete: `docs/staging_signoff_release-2.0.0.md`, all items, including L-1. Rechecked 2026-11-25.
- [x] `release-2.0.0` merged into `main` (R-1, #431) and tagged `v2.0.0` (R-2, on `9bd3ea4`; GitHub release published 2026-11-25). The `main.yml` run on the merge: `Test` success, `Deploy` **skipped**.
- [x] **C-1: per-city deploy.** `DEPLOY_CITIES="ogre"` (space- or comma-separated) deploys only those cities, in `cities.yaml` order. A name not in `cities.yaml` stops the deploy before anything runs (`tests/test_32`). Works as an env prefix or as `make deploy-prod DEPLOY_CITIES=ogre`.
- [x] SSH access to the production host for the operator. The instance key pair is `dev-branch-16x-ec2-key-2026-jan-v1`. Used 2026-11-25; the instance role (`VF-Custom-S3-SecretsManager-access`) works.
- [ ] `s3://sslv-prod-m6-cicd-files/` holds `.env.prod`, `database.ini` and `.env.<city>` for all six cities. Each `.env.<city>` has `S3_BUCKET=sslv-prod-<city>-db-backups` and `CITY=<city>`. **2026-11-25: the bucket exists but is empty** (`head-object .env.prod` → 404). **Blocker.**
- [ ] All six `sslv-prod-<city>-db-backups` buckets exist (confirmed 2026-11-25). **Turn on versioning** on them with `aws s3api put-bucket-versioning` (loop in [#436](https://github.com/vfedotovs/sslv_web_scraper/issues/436)). `make create-s3-bucket` can't do it: it stops when the bucket already exists, and its 90-day expiry rule covers every object, including `pre-cutover-2.0.0/`. Prod buckets are not versioned today, so any accidental delete is permanent (S-5).
- [ ] A prod ntfy topic (`NTFY_TOPIC_URL`). `make` refuses the staging topic for `M6_ENV=prod`.
- [ ] A cutover window: start after 02:30 UTC and finish well before 00:40 UTC (the nightly run). Weekday morning recommended. The old `cron` service backs up at 03:05/03:07 UTC and sends reports until 04:12, so starting after 04:15 also gives a fresh old-format backup.
- [x] **Host capacity** (done 2026-11-25): root EBS volume grown 16 → 30 GiB (`growpart` + `xfs_growfs`; 16 GB free after), and a 2 GiB `/swapfile` added (in `/etc/fstab`). Staging needs ~5 GB of images and uses ~190 MB of swap with six cities; prod had no swap and 4.0 GB free.
- [x] **OS patched** (done 2026-11-25): Amazon Linux 2023 updated to `2023.12.20261120` (`dnf upgrade --releasever=latest`), kernel `6.1.190-237.442`, rebooted after an EBS snapshot. Swap and disk came back, and the old stack restarted by itself (`restart: always`): `db`/`ws`/`ts` healthy, `cron` up.

## Step 0 — Inventory (read-only, record the answers)

```bash
docker ps -a --format '{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Label "com.docker.compose.project"}}\t{{.Label "com.docker.compose.project.working_dir"}}'
docker compose ls -a
docker volume ls
ls -d ~/*/ ; ls ~/*/docker-compose.yml
crontab -l ; sudo ls /etc/cron.d ; systemctl list-units --all 'sslv*'
free -m ; df -h / ; nproc ; uname -m ; docker version --format '{{.Server.Version}}' ; docker compose version
aws sts get-caller-identity ; aws s3 ls s3://sslv-prod-m6-cicd-files/
for c in salaspils sigulda marupes-pag adazu-nov ogre jurmala; do
  echo "$c: $(aws s3 ls s3://sslv-prod-$c-db-backups/db-backups/ --recursive | sort | tail -1)"; done
```

Taken 2026-11-25 on `main-branch-production`:

| Fact | Value |
|---|---|
| Old project name (`OLD`) and its folder | `20260509-1750-deploy`, `~/20260509-1750-deploy` (deployed 2026-05-09) |
| Old containers (`$OLD-db-1`, `-ws-1`, `-ts-1`, `-cron-1`?) | `db`, `ws`, `ts` (healthy) and `cron`, all running. `$OLD-curl-1` is a one-shot job, exited (0) |
| Old DB volume | `20260509-1750-deploy_db_data`. 13 older deploy folders (2026-03-22 … 2026-05-08) each left a `db_data` + `backup_tmp` volume: 28 volumes, 637 MB reclaimable. Keep them until step 7 |
| Old DB: user / db name / row counts (`listed_ads`, `removed_ads`) | `new_docker_user` / `new_docker_db` (same as 2.0.0, so the dump's `OWNER TO` lines restore cleanly) / **40** / **2757**. Same column names as 2.0.0 (`listed_ads.list_date`, `removed_ads.listed_date`) |
| Old version (email subject or `RELEASE_VERSION`) | `v1.5.13-rc`, `APP_ENV=production` |
| Host RAM / free disk. Staging runs 6 cities on 1.8 GB RAM and needed ~5 GB of images | aarch64, 2 vCPU, 1846 MB RAM (~1130 MB available). Docker 25.0.16, Compose v5.1.1. Before: no swap, 16 GB disk 76% used (4.0 GB free). **After host prep:** 2 GiB swap, 30 GB disk 47% used (16 GB free). Docker: images 1.1 GB, build cache 2.75 GB (reclaimable) |
| Any host cron or other schedulers | Host crontab: one stale entry, `11 4 * * *` `docker stats 83adc7ac9aee \| grep hotfix` → `ntfy.sh/m5_arm_sslv_alerts` (that container is long gone). Remove it in step 7. `/etc/cron.d`: only the system `0hourly`. No `sslv*` systemd units |
| Old backups (the `cron` service) | **Yes, working.** 03:05 `pg_dump` inside `$OLD-db-1`, 03:07 upload to `s3://release-1422-pg-backups/pg_backup_YYYY_MM_DD.sql` (flat keys, uncompressed; 204 KB on 2026-11-25). Then ntfy reports 03:10–04:12. Step 3 stops it; `ogre-backup-1` takes over at 02:00 |
| CICD bucket files present | **No.** `sslv-prod-m6-cicd-files` exists and is empty. Blocker, see prerequisites |
| Newest backup per prod city bucket, and whether it is **prod** data | All six: 2026-09-22 18:34:01–18:34:23, 2.2–5.5 KB. Written within 22 s of each other and far smaller than prod Ogre: **staging data**, not prod (the caution below). Don't restore from them |

> **Caution:** on 2026-09-21 a staging run uploaded **staging** dumps into the `sslv-prod-*` buckets. Never
> restore prod from those buckets without checking the dump's origin. For Ogre, the source of truth is
> the **old production DB itself** (step 2).

## Step 1 — Safety copies

1. **EBS snapshot** of the root volume, tagged `pre-v2.0.0-cutover`. This is the full rollback point.
2. **Dump the old Ogre DB** with the server's own `pg_dump`:
   ```bash
   docker exec "$OLD-db-1" pg_dump --clean --if-exists -U new_docker_user -d new_docker_db | gzip > ~/pre-cutover-ogre-$(date -u +%Y%m%dT%H%MZ).sql.gz
   ```
3. Copy it **outside** `db-backups/`, so no retention or restore "latest" logic ever picks it up:
   `aws s3 cp ~/pre-cutover-ogre-*.sql.gz s3://sslv-prod-ogre-db-backups/pre-cutover-2.0.0/`
4. **Prove it restores** (throwaway container, strict):
   `./scripts/restore_db_city.sh --city ogre --env prod --file ~/pre-cutover-ogre-*.sql.gz --scratch`
   (run from `~/sslv-prod` after step 2 of the next section). Record the row counts.

## Step 2 — Prepare `~/sslv-prod`

```bash
git clone https://github.com/vfedotovs/sslv_web_scraper.git ~/sslv-prod
cd ~/sslv-prod && git checkout v2.0.0
make help >/dev/null && git describe --tags     # expect v2.0.0
```

## Step 3 — Stop the old stack (keep it, don't remove it)

Stop the scheduler first so it can't fire, then the rest. **Do not** `down` it, remove its volume, or prune images.
```bash
docker stop "$OLD-ts-1"  "$OLD-cron-1" 2>/dev/null || true
docker stop "$OLD-ws-1"  "$OLD-db-1"
docker update --restart=no "$OLD-ts-1" "$OLD-ws-1" "$OLD-db-1" "$OLD-cron-1" 2>/dev/null || true   # survive a reboot stopped
```
From here until step 4 finishes, production sends no report. That's fine inside the window.

## Step 4 — Ogre first (R-5)

1. Deploy only Ogre. The run check is skipped: its DB is empty until the restore.
   ```bash
   DEPLOY_CITIES=ogre POST_DEPLOY_VERIFY=false DEPLOY_APP_ENV=production make deploy-prod
   ```
2. Restore the old Ogre data into the new DB. Live, atomic, with a safety copy:
   ```bash
   ./scripts/restore_db_city.sh --city ogre --env prod --file ~/pre-cutover-ogre-*.sql.gz --yes
   ```
   Row counts must match step 1.4.
3. Fix prices of 1M+ stored as 1/1000 before `dev-1.7.9.23`: `make repair-prices CITY=ogre`, review the dry run, then `make repair-prices CITY=ogre APPLY=1`.
4. Run the pipeline once and wait for it. `scrape_runs` is new, so today counts as "not run yet":
   ```bash
   DEPLOY_CITIES=ogre DEPLOY_APP_ENV=production make deploy-prod      # post-deploy check: expect "[ogre] Post-deploy verification OK: run 1 success"
   ```
5. Check:
   - the report email arrived, with subject `… web_scraper_v2.0.0_… [production]` and the "New listings in this report" line;
   - `listed_ads` ≈ old count ± today's changes;
   - `make fleet-status M6_ENV=prod` is OK for ogre. The other five cities show as absent.
6. Install monitoring from **this** directory:
   ```bash
   make watchdog-install M6_ENV=prod NTFY_TOPIC_URL=<prod topic>
   make watchdog-test-ntfy NTFY_TOPIC_URL=<prod topic>
   ```

**Hold for one night.** Next morning: 00:40 run success, 01:40 check OK, 02:00 backup, then
`make test-restore CITY=ogre M6_ENV=prod` and `make fleet-status M6_ENV=prod`.

## Step 5 — The other five cities

New cities start with **empty** DBs and fetch every listed ad on their first run, at
`SCRAPE_DELAY_SEC`=5 s per ad. Jūrmala has ~300 ads (~25 min). Their first emails list everything.
Don't restore them from the prod buckets (see the caution in step 0).

```bash
DEPLOY_CITIES="salaspils sigulda marupes_pag adazu_nov jurmala" POST_DEPLOY_VERIFY_TIMEOUT=2400 DEPLOY_APP_ENV=production make deploy-prod
```
`check_backup_age` warns about the fresh volumes or old backups. That's expected; don't set `FAIL_ON_FRESH_VOLUME`.

Check: 6/6 cities deployed, each post-deploy run `success`, six emails, `make fleet-status M6_ENV=prod`
6/6 OK, and **24 containers**, one per city/service. The old `$OLD-*` containers stay **stopped**.

## Step 6 — Watch

- Night 1 of the full fleet: runs, emails, backups, `make test-restore M6_ENV=prod` (6/6), memory (`fleet-status`).
- Run `make collect-logs` after night 1 and keep the bundle as the cutover record.

## Step 7 — Clean up (after 7 clean days)

1. Final dump of the old DB volume into `s3://…/pre-cutover-2.0.0/`, if it differs from step 1.
2. `docker rm` the old containers, then `docker volume rm` the old DB volume, then remove its images.
3. Archive the old deploy folder(s) to `~/archive/` (as on staging), so `~/sslv-prod` is the only one.
4. Delete the EBS snapshot only after this.

## Rollback

| From | Do | Data |
|---|---|---|
| Steps 1–3 | `docker start "$OLD-db-1" "$OLD-ws-1" "$OLD-ts-1"`, then `docker update --restart=always` | Nothing lost |
| Step 4 (ogre on v2) | `make clean-containers CITIES=ogre` (keeps `ogre_db_data` and images), then start the old stack as above | Ogre runs since cutover are only in `ogre_db_data`. The old DB misses those days; next run re-detects them |
| Step 5+ | All: `make undeploy-prod` (keeps volumes), then start the old stack. Only the new five: `make clean-containers CITIES="salaspils sigulda marupes_pag adazu_nov jurmala"` | Five new cities: nothing to lose; their volumes are kept |
| Host broken | Restore the EBS snapshot from step 1.1 | Back to the moment before cutover |

After a rollback: `make watchdog-uninstall`, so the watchdog doesn't alert on the absent cities.

## Open questions

- ~~Does the old stack have a `cron` service writing backups somewhere that should keep running until step 7?~~ Yes: nightly to `s3://release-1422-pg-backups/` (Step 0). It stops in step 3, which is fine: from then on `ogre-backup-1` backs up Ogre. Keep that bucket as an archive of the v1.5.x backups.
- Which address receives production email, and should the five new cities' first full-listing emails go there?
- Prod bucket versioning and lifecycle: decide before step 1 (S-5 follow-up).
