# M8 — Action Plan: Remove pandas From the ws Pipeline

**Date:** 2026-07-12 (branch dev-1.7.8)
**Motivation:** pandas (+ numpy) is the single largest avoidable memory
consumer in the `ws` container: ~150–280MB RSS at import time, paid by
*every* per-city container even while idle, plus slower cold starts and a
larger image. The pipeline's actual data volume is ≤ a few thousand rows
of short strings per run — stdlib `csv` + plain dicts/lists handle this
with a few MB.
**Scope:** Only the live pipeline modules. No behavior change, no new
dependencies (explicitly **not** switching to polars — same problem,
smaller). This is a plan only; no code here.

---

## 1. Current pandas usage inventory (what actually has to be replaced)

Live importers (called from `main.py` stage list) and their full pandas
API surface:

| Module | pandas usage | Replacement primitive |
|--------|--------------|----------------------|
| `data_format_changer.py` | `pd.DataFrame(dict_of_lists)` + `df.to_csv()` — no computation at all | `csv.writer` writing rows zipped from the same lists |
| `df_cleaner.py` | `pd.read_csv`, `df.replace(regex)` ×7 keywords, `.str.split` ×3 (sqm / price / eur-sqm columns), column create/drop, `sort_values(by='Price_in_eur')`, `to_csv`, re-`read_csv`, `.iterrows()` ×2 (email body), `.unique()`/`.tolist()` (pub dates, room counts), `dtype` check | `csv.DictReader` → list of dicts; per-row `str.replace`/`split`; `sorted(rows, key=lambda r: int(r[...]))`; `csv.DictWriter`; plain loops |
| `db_worker.py` | `pd.read_csv` (`load_csv_to_df`), `df.empty`, `df.iterrows()` (`extract_new_msg_data`), `df["URL"].tolist()` (`extract_url_hashes_from_df`), `pd.DataFrame(columns=...).to_csv` (`ensure_csv_exists` placeholder) | `csv.DictReader` → list of dicts; `len(rows) == 0`; plain loop; list comprehension; write header line with `csv.writer` |
| `analytics.py` | `pd.read_csv`, `.unique()` on Room_count, boolean-mask split by column value (`split_dataframe_by_column`), `.tolist()` per segment | `csv.DictReader`; `dict` grouping (`rows_by_room.setdefault(rc, []).append(price)`); `min`/`max`/len on lists |

Dead pandas importers (nothing in the live pipeline references them):

- `wsmodules/run_analisys.py`
- `wsmodules/next_features/DataAnalyser.py`
- (`wsmodules/pdf_creator.py` — already decommissioned, imports fpdf/matplotlib which are no longer installed)
- (`wsmodules/sendgrid_mailer.py`, `wsmodules/gen_report.py` — dead, not pandas but same cleanup batch)

Test helpers that import pandas: `tests/test_16_m7_p5_efficient_diff.py`
(`make_df`) and `tests/test_20_m7_p7_city_scoped_files.py` feed
DataFrames/CSVs into the modules. `tests/fixtures/` unknown — check
during Phase 5.

## 2. The data contract that must survive

The stages hand off via CSV files (M7 P7 made them city-scoped):

1. `{city}-pandas_df.csv` — columns `URL, Room_count, Size_sq_m, Floor,
   Street, Price, Pub_date`, **plus a leading unnamed pandas index
   column**.
2. `{city}-cleaned-sorted-df.csv` — columns `URL, Room_count, Floor,
   Street, Pub_date, Size_sqm, Price_in_eur, SQ_meter_price`, plus
   leading index column; rows sorted ascending by `Price_in_eur`.

Decisions to lock in before coding:

- **Keep the leading index column** in both files during the migration
  (write a running row number). It costs nothing and keeps every
  reader — including any ad-hoc scripts and the Streamlit explorer —
  byte-compatible. Drop it in a separate follow-up commit only after
  everything is off pandas.
- **Types become strings.** `csv` yields `str` where pandas auto-coerced
  to int64/float64. Every consumer that needs a number must cast
  explicitly: `Price_in_eur` → `int`, `SQ_meter_price` → `float`,
  `days_listed` math in `db_worker`. Postgres will still coerce
  parameterized text values on INSERT, but the code should cast anyway
  so comparisons/sorting are numeric, not lexicographic
  (`"9" > "10000"` is the classic bug to guard against).
- Row representation between functions inside a module: `list[dict]`
  keyed by the CSV header names (same names as today's DataFrame
  columns), so diffs of the refactor stay reviewable.

## 3. Phased plan (each phase = one branch/commit, suite green after each)

### Phase 0 — Baseline + dead-code deletion (0.5 day)
1. Measure and record: `docker stats` RSS of an idle `ws` container,
   container image size, and cold-start time (`docker compose up` →
   first successful `/` response).
2. Delete dead modules: `run_analisys.py`,
   `next_features/DataAnalyser.py`, `pdf_creator.py`,
   `sendgrid_mailer.py`, `gen_report.py` (git history preserves them).
   This removes 2 of 6 pandas importers without touching live code.
3. Record which tests exercise the four live modules (safety net:
   `test_02`, `test_03`, `test_16`, `test_17`, `test_18`, `test_20`).

### Phase 1 — Golden-file harness first (0.5 day, do before any rewrite)
1. Add a test fixture: one raw report file (`{city}-raw-data-report`)
   with ~10 ads covering the edge cases (price with thousands
   separators, floor `3/9/lifts`, missing date, >999-day-old pub date).
2. Add a "golden chain" test that runs
   `data_format_changer → df_cleaner → analytics` on the fixture and
   snapshots the three output files. Assert against committed golden
   copies. This is the contract keeper for every following phase —
   the M7 P7 test (`test_20`) already does a light version of this;
   extend it rather than duplicating.

### Phase 2 — `data_format_changer.py` (0.5 day, lowest risk)
- `create_oneline_report()` already builds seven plain Python lists; it
  only touches pandas in the last two lines (`pd.DataFrame` → return).
  Change it to return `list[dict]` and have the caller write the CSV
  with `csv.writer` (header + index column as decided above).
- Remove the module's pandas import. Golden test must stay green
  byte-for-byte.

### Phase 3 — `df_cleaner.py` (1–1.5 days, the bulk of the work)
- Replace `read_csv` with `csv.DictReader`.
- The seven `df.replace(regex)` keyword removals and three `.str.split`
  column derivations become one per-row cleanup function (pure string
  ops — trivially unit-testable in isolation; add direct tests for it).
- `sort_values` → `sorted(rows, key=lambda r: int(r["Price_in_eur"]))`.
- `to_csv` → `csv.DictWriter`; drop the pointless re-`read_csv` of the
  file it just wrote (use the in-memory rows for the email body).
- `iterrows()` email-body loops → plain loops over the row dicts; the
  `dtype == 'int64' / 'object'` branch in `create_email_body` collapses
  to one string comparison (everything is `str` now).
- Keep the `pandas_df_default.csv` empty-file fallback path behavior.

### Phase 4 — `analytics.py` + `db_worker.py` (1 day)
- `analytics.py`: `csv.DictReader`; `split_dataframe_by_column` becomes
  a `defaultdict(list)` grouping of prices by `Room_count`; min/max/avg
  math unchanged (cast to `int` at read). tabulate stays.
- `db_worker.py`: `load_csv_to_df` → `load_csv_rows` returning
  `list[dict]` (empty list replaces `df.empty`/`None` checks — update
  `db_worker_main` guard accordingly); `extract_new_msg_data` loop over
  dicts (it is already a single pass since M7 P5); `ensure_csv_exists`
  writes a header line with `csv.writer`. Cast `Room_count`, prices and
  sqm to numbers at the insert-dict build site (see §2).

### Phase 5 — Uninstall + measure + tests (0.5 day)
1. Update test helpers (`make_df` etc.) to write CSV fixtures with the
   `csv` module; remove pandas imports from tests.
2. Remove `pandas` from `src/ws/requirements.txt`; add a guard test
   that `grep`s the live wsmodules for `import pandas` (keeps it out).
3. Rebuild the image; repeat the Phase 0 measurements; record
   before/after in this file (expected: **~150–250MB RSS saved per
   city container**, smaller image, faster cold start).
4. Follow-up (optional, separate commit): drop the legacy index column
   from both hand-off CSVs and simplify readers.

## 4. Risks and mitigations

| Risk | Mitigation |
|------|------------|
| Numeric vs string comparison bugs (`sort`, `min/max`, price math) | Explicit casts at every read site (§2); golden-file test sorts are order-sensitive and will catch lexicographic sorting immediately |
| CSV shape drift breaks `db_worker`/Streamlit/ad-hoc readers | Keep index column + exact header names until Phase 5.4; golden files assert byte-identical output |
| Encoding (Latvian diacritics: `Platība`, `Stāvs`, `€`, `m²`) | All new open() calls use `encoding="utf-8"` explicitly, matching current writers; fixture ads include diacritics |
| Empty-input day (zero new ads since M7 P1) | Phase 1 fixture set must include an empty raw report case; `df.empty` guards map to `len(rows) == 0` |
| Hidden pandas dependence in tests/fixtures | Phase 5 grep-guard test; run full suite after each phase |

## 5. Explicit non-goals

- No polars/pyarrow/numpy replacement — the dataset is thousands of
  rows of short strings; stdlib is the right size.
- No change to the DB schema, the diff logic, or file naming (M7 P7
  contract stays).
- No lazy-import interim step for pandas in the live modules — the
  pipeline imports them on every run anyway, so laziness saves nothing
  once the real removal is this close; dead modules are deleted instead.

## 6. Effort summary

| Phase | Content | Effort |
|-------|---------|--------|
| 0 | Baseline metrics + delete dead modules | 0.5 day |
| 1 | Golden-file harness | 0.5 day |
| 2 | data_format_changer | 0.5 day |
| 3 | df_cleaner | 1–1.5 days |
| 4 | analytics + db_worker | 1 day |
| 5 | Uninstall pandas, measure, guard | 0.5 day |
| **Total** | | **~4–4.5 focused days** |
