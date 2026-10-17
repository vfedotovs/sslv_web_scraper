# M7 — WS Architecture Assessment: Extreme Inefficiencies Blocking Scale Above 3000 Ads/Day

**Scope:** Only problems with extreme, measurable negative impact on scaling the `ws` scraping pipeline
(`src/ws/app/main.py` + `src/ws/app/wsmodules/`) above 3000 ads/day.
Correctness bugs, style issues, and nice-to-haves are excluded unless they directly block scale.
No code is proposed here — this is an assessment only.

**Baseline reality check:** 3000 detail fetches/day is ~2 requests/minute if spread over 24h.
The bottleneck is not raw throughput — it is that the current design multiplies the work by
~4× per ad, refetches ads it already knows about, and serializes everything.

---

## Problem List

### Problem 1 — Every discovered ad is re-scraped daily, even if already in `listed_ads`

**Where:** `web_scraper.py:scrape_website()` → `extract_data_from_url()`; diff happens only later in `db_worker.py:compare_df_to_db_hashes()`.

**What happens:** The scraper fetches the detail page of *every* URL found on the list pages, writes the raw report, and only afterwards (in `db_worker`) compares hashes against the DB. Daily listing turnover is typically 2–5%, so **~95%+ of all detail-page fetches retrieve data the DB already has**. The only value extracted from re-fetching a known ad is a possible price change and the `days_listed` update — and `days_listed` doesn't need fetching at all (see Problem 3). The URL hash is available from the list page itself, so the new/known split could happen *before* any detail fetch.

- **Negative impact: CRITICAL.** At 3000 ads/day this is ~2850 wasted detail fetches daily (×4 requests each, see Problem 2 → ~11,400 wasted HTTP requests/day). It inflates run time from minutes to many hours, and is the single largest ban-risk factor with ss.lv. This is the primary hard blocker for scaling ad volume or city count.
- **Effort to resolve: MEDIUM.** Requires reordering the pipeline (extract hashes from list pages → diff against DB → fetch details only for new hashes) and giving the downstream formatter/cleaner a way to handle a "new ads only" dataset while still-listed/removed sets come from the diff. Touches `web_scraper`, `main.py` orchestration, and `db_worker` input contract. No schema change required. Estimated 2–4 focused days including tests.

---

### Problem 2 — Each ad detail page is downloaded 4 times, plus ~6s hardcoded sleep per ad

**Where:** `web_scraper.py:extract_data_from_url()` calls `get_msg_table_data()` four times per URL (`ads_opt_name`, `ads_opt`, `ads_price`, `msg_footer`) — each call does its own `requests.get()` of the **same page** and re-parses it with BeautifulSoup. Between calls there are hardcoded `time.sleep(1)` ×3 and `time.sleep(3)` — the configurable `SCRAPE_DELAY_SEC` is defined (line 78) but never actually used in this loop. Additionally, `get_msg_table_data()` calls `requests.get(msg_url)` with **no timeout** and retries only on `ConnectionError` (a hung socket or HTTP 5xx/403 is not handled), and it bypasses the polite `session` (User-Agent, connection reuse) used for list pages.

- **Negative impact: CRITICAL.** 4× the necessary request volume: 3000 ads → 12,000 detail requests/day instead of 3000. Fixed sleeps alone cost 6s × 3000 = **5 hours of pure sleeping** per run; total run time lands around 8–12 hours for one city. A single hung request (no timeout) can stall the entire daily run indefinitely. Combined with Problem 1, actual useful work is under 1% of traffic sent to ss.lv.
- **Effort to resolve: LOW.** Fetch each detail page once, parse all four sections from the single BeautifulSoup object, reuse the existing session, add a timeout, and apply one configurable delay per ad. Localized to `web_scraper.py`. Estimated 0.5–1 day including tests.

---

### Problem 3 — `days_listed` is stored as a mutable value and re-updated in the DB every day

**Where:** `db_worker.py:extract_to_increment_msg_data()`, `update_dlv_in_db_table()`, `update_single_column_value()`.

**What happens:** `days_listed` is a value fully derivable from `list_date` and today's date, yet it is stored per row and "corrected" daily: the code fetches the entire `listed_ads` table, matches still-listed hashes in Python, recalculates the value per ad, and issues **one UPDATE statement per ad — each opening and closing its own PostgreSQL connection** (`update_single_column_value`). At 3000 still-listed ads that is up to ~3000 connections + 3000 single-row transactions per city per day, to maintain a number that a report-time subtraction (`today − list_date`) produces for free. The date math itself is also done by string-parsing `str(timedelta)` (`calc_valid_dlv`), which silently returns 0 for ads listed >999 days.

- **Negative impact: HIGH.** The whole `extract_to_increment_msg_data` + `update_dlv_in_db_table` stage — the most DB-expensive stage of the daily run — exists only to maintain redundant data. It scales linearly in connections and transactions with ad count and is pure waste. It also makes runs non-idempotent (skipping a day leaves stale values everywhere).
- **Effort to resolve: LOW–MEDIUM.** Compute `days_listed` at read time (reporting/analytics and at removal time when copying to `removed_ads`) and delete the daily increment stage entirely. Analytics, PDF and mailer read paths need to pick up the derived value. Estimated 1–2 days.

---

### Problem 4 — Per-row SQL with a new connection per operation; full-table scans loaded into Python

**Where:** `db_worker.py` throughout: `insert_data_to_listed_table()` and `insert_data_to_removed_table()` loop `cur.execute` per row; `delete_db_listed_table_rows()` executes one DELETE per hash (built by string concatenation — also an SQL-injection surface); `extract_to_remove_msg_data()` and `extract_to_increment_msg_data()` each do `SELECT * FROM listed_ads` and `fetchall()` the entire table, then match rows in nested Python loops; `save_table_row_counts()` re-reads the full hash list twice per run just to log row counts.

- **Negative impact: HIGH.** The daily DB workload is O(rows × operations) with connection/commit overhead per statement instead of a handful of set-based bulk statements per run. At 3000 ads this means the full table is pulled into Python memory 4–5 times per run and thousands of individual statements are executed. It compounds directly with Problem 3. At 10 cities × 3000 ads the DB stage becomes minutes-to-hours of avoidable load and a growing failure surface (partial-run states, since there is no single transaction).
- **Effort to resolve: LOW.** Standard batching: one connection per run, `WHERE url_hash IN (...)` / `executemany` / bulk insert-select for the listed→removed move, one transaction per city run. Confined to `db_worker.py`. Estimated 1 day including tests.

---

### Problem 5 — O(N²) diffing and data extraction in Python

**Where:** `db_worker.py:compare_df_to_db_hashes()` (list-membership checks: `df_hash in db_hashes` over lists → O(N×M)); `extract_new_msg_data()` (for **each** new hash it iterates the **entire** DataFrame with `df.iterrows()`, recomputing `extract_hash` per row → O(new × N)); the nested hash-matching loops in `extract_to_remove_msg_data()` and `extract_to_increment_msg_data()` (O(N×M) over full-table fetches).

- **Negative impact: MEDIUM–HIGH.** At today's ~100 ads/city this is invisible; at 3000 ads it is tens of millions of comparisons and hundreds of thousands of `iterrows` passes per run — minutes of CPU and memory bloat; at 10,000+ ads it becomes the dominant in-process cost. It is a silent quadratic time bomb: nothing fails, runs just get progressively slower each month as `listed_ads` grows.
- **Effort to resolve: LOW.** Replace lists with sets for the three-way diff and index the DataFrame/DB rows by hash once (dict lookup). Pure in-module refactor with existing tests (`test_04_module_db_worker.py`) as a safety net. Estimated 0.5 day. Cheapest fix in this list relative to impact.

---

### Problem 6 — The entire pipeline runs synchronously inside an `async` FastAPI handler

**Where:** `main.py:run_long_task()` — declared `async` but calls the whole blocking chain (`scrape_website` → formatter → cleaner → `db_worker` → analytics → mailer) inline.

- **Negative impact: HIGH.** The event loop is blocked for the full run duration (currently hours — see Problems 1–2). While one city runs, the `ws` container answers nothing: health checks on `/docs` fail (Docker may mark the container unhealthy and restart it mid-run), the `ts` scheduler's HTTP GET times out with no way to know if the job succeeded, and a second `/run-task/{city}` call is impossible. This is why multi-city currently requires a full container set per city. Even after Problems 1–2 shrink run time to minutes, any growth in cities or volume re-hits this wall; there are no retries, no run status, no protection against overlapping runs beyond a filesystem marker file (`check_lst_run_state`).
- **Effort to resolve: MEDIUM.** Move the pipeline execution off the request path (background execution with a run-status record), make the endpoint enqueue-and-return, and give `ts` a way to query run status. Estimated 2–3 days. A full job-queue system is *not* required at this scale — but the request path must stop blocking.

---

### Problem 7 — Fixed, shared intermediate filenames make stages collide across cities

**Where:** Hand-off files between stages are hardcoded and not city-scoped: `pandas_df.csv` (`data_format_changer.py`), `cleaned-sorted-df.csv` (`df_cleaner.py`, `db_worker.py`, `analytics.py`), `basic_price_stats.txt` (`analytics.py` → `pdf_creator.py`), `scraped_and_removed.txt` (`db_worker.py`, append-only forever). Only the raw report got a city prefix in M6; everything downstream still funnels through the same filenames in the container working directory. File copies are made via `os.system("cp ...")`.

- **Negative impact: MEDIUM–HIGH.** Two city runs in the same container would silently overwrite each other's data mid-pipeline — which is exactly why the current workaround is one full Docker stack (db+ws+ts+backup) per city. That workaround multiplies memory/CPU/infra cost linearly with city count and caps horizontal scale. The filesystem is also acting as the pipeline's state store (run markers, debug counters, hand-off files), which prevents any concurrency and makes runs unreproducible.
- **Effort to resolve: MEDIUM.** Thread the city slug through every stage's input/output filenames (the pattern already exists for the raw report), or pass DataFrames in memory between stages instead of via disk. Touches every wsmodule but each change is mechanical. Estimated 2–3 days including tests.

---

### Problem 8 — No city dimension in the database schema

**Where:** `db_worker.py:ensure_tables_exist()` — `listed_ads` and `removed_ads` have no `city` column and no primary key/index on `url_hash`. The diff logic is only correct because each city gets its own dedicated PostgreSQL container.

- **Negative impact: MEDIUM.** This is the root cause that forces the one-DB-per-city deployment model (each with its own backup container, volume, S3 bucket wiring, and restore procedure). Scaling from 3 to 10 cities means 10× the infrastructure instead of one shared DB. It also makes cross-city analytics (the propertydata.lv portal) impossible without stitching databases together. Missing key/index additionally means every hash lookup is a sequential scan — compounding Problems 4–5 as tables grow.
- **Effort to resolve: MEDIUM–HIGH.** Add `city` to both tables (and to every query's WHERE clause), add a primary key on `(city, url_hash)`, migrate existing per-city data into one DB, and update deploy/backup/restore scripts. The code change is moderate; the migration and ops change is the larger half. Estimated 3–5 days. High payoff but should come after the pipeline itself is efficient.

---

### Problem 9 — Full-dataset logging on every run

**Where:** `db_worker.py` logs complete hash lists and every row's data at INFO level (`extract_url_hashes_from_db` logs the whole list twice, `extract_new_msg_data`/`extract_to_increment_msg_data`/insert functions log every ad row); `compare_df_to_db_hashes` logs all three full hash lists; `web_scraper.py` logs per-URL progress lines for every ad.

- **Negative impact: LOW–MEDIUM.** At ~100 ads it's noise; at 3000 ads each run writes tens of thousands of log lines including multi-hundred-KB single lines (full list dumps), churning the 5 MB rotating handlers several times per run and making the logs useless for actual debugging. Pure overhead with no reader.
- **Effort to resolve: LOW.** Log counts and samples at INFO, full dumps at DEBUG or not at all. A few hours.

---

## Recommended Resolution Order

Ordered by return on effort — request-volume reductions first (they unblock everything else and reduce ban risk immediately), then DB efficiency, then concurrency/architecture:

| Order | Problem | Why this position |
|-------|---------|-------------------|
| 1 | **P2** — 4× fetch + hardcoded sleeps | Lowest effort, immediately cuts request volume 75% and run time by hours. No pipeline redesign needed. Prerequisite for safely testing at higher volumes. |
| 2 | **P5** — O(N²) diff/extraction | Half a day, removes the quadratic time bomb before tables grow. Makes P1's diff-first reorder cheap to build on. |
| 3 | **P1** — re-scraping known ads | The big one: ~95%+ request reduction. Do after P2/P5 so the reordered pipeline lands on efficient primitives. After P1+P2, 3000 ads/day ≈ 60–150 detail fetches/day. |
| 4 | **P4** — per-row SQL, connection churn | Batch the DB stage while its input contract is already being touched by P1. |
| 5 | **P3** — stored `days_listed` daily updates | Deletes an entire pipeline stage; simplest once P4's bulk patterns exist. |
| 6 | **P6** — blocking async endpoint | With runs now taking minutes not hours, background execution + run status makes multi-city safe and health checks honest. |
| 7 | **P7** — shared intermediate filenames | Enables multiple cities per container; needed before consolidating infrastructure. |
| 8 | **P8** — no city column in schema | The consolidation step: one DB for all cities. Do last among the majors — it depends on P7 and carries migration/ops risk. |
| 9 | **P9** — full-dataset logging | Trivial cleanup; fold into whichever of the above touches each module, or do as a final sweep. |

**Combined effect of P1 + P2 alone:** daily traffic to ss.lv for a 3000-ad city drops from ~12,000 requests + 5h of sleeps to roughly 10–20 list-page fetches plus ~60–150 detail fetches — about a **99% reduction** — and the run completes in minutes. Everything after that is about making the system safe to operate at 10+ cities, not about raw capacity.
