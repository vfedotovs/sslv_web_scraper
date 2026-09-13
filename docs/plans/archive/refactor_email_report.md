# Email Report Refactor — Action Items
Generated: 2026-05-01

---

## Bug fixes (broken behaviour)

### BUG-1: "--- Month: ---" label shows no month name
**File**: `src/ws/app/wsmodules/df_cleaner.py:299`
**Problem**: The month separator line is hardcoded as `"\n--- Month: ---"`. The `month` variable is available in the loop but never interpolated into the string.
**Fix**: Replace with `f"\n--- Month: {month} ---"` so it renders as `--- Month: 04.2026 ---`.

### BUG-2: DB stats row printed twice before each comparison line
**File**: `src/ws/app/wsmodules/db_worker.py`
**Problem**: `save_table_row_counts()` is called twice in `db_worker_main()` — at line 75 (before processing) and again at line 98 (after processing). Both calls append to `scraped_and_removed.txt`, so the email shows each date's row counts twice before the comparison result.
**Fix**: Remove the first call at line 75 and keep only the call at line 98 (after all operations complete). The before-state is not useful in the email output.

### BUG-3: `load_csv_to_df()` called twice in `db_worker_main()`
**File**: `src/ws/app/wsmodules/db_worker.py:65,71`
**Problem**: `df = load_csv_to_df("cleaned-sorted-df.csv")` is called at line 65, then the None/empty guard runs, then it's called again at line 71 unconditionally. The second call overwrites the first and skips the guard's intent.
**Fix**: Remove the duplicate call at line 71.

### BUG-4: `avg_price` is calculated as `(min + max) / 2`, not a true average
**File**: `src/ws/app/wsmodules/analytics.py:130`
**Problem**: `avg_price = str((min(prices) + max(prices)) / 2)` is a midpoint, not the mean. For skewed distributions (like 3-room where Draudzības 6a dominates at high prices) this is significantly wrong.
**Fix**: Use `sum(prices) / len(prices)` or `statistics.mean(prices)`.

### BUG-5: Summary table shows 5-room segment with no corresponding detail rows
**Problem**: The price stats table includes a 5-room segment (2 ads, 144480–195000) but no 5-room entries appear in the apartment listing section above it. The detail rows are being filtered or dropped before the email body is assembled while the stats table uses the full DataFrame.
**Fix**: Ensure `create_email_body()` and `analytics_main()` operate on the same filtered DataFrame, or explicitly include 5-room rows in the listing section.

---

## Data quality issues

### DQ-1: Inconsistent address formatting prevents deduplication
**Problem**: The same street appears under multiple name variants in a single report:
- `Mālkalnes prospekts` / `Mālkalnes pr.` / `Malkalnes` (missing diacritics)
- `Nogāzes iela 2` / `Nogāzes 2`
- `Draudzības iela 6a` / `Draudzības 6a`
- `Skolas iela 16` / `Skolas 10`
- `Ausekļa prospekts 9` / `Ausekļa 5`

This is coming from the raw scrape source — the ss.lv listing owners enter addresses inconsistently. The `df_cleaner.py` module has no address normalisation step.
**Fix**: Add a normalisation pass in `df_cleaner.py` that: (1) expands common abbreviations (`pr.` → `prospekts`, `iela` always kept), (2) strips/restores Latvian diacritics to a canonical form for comparison purposes.

### DQ-2: Duplicate listings for the same property not flagged
**Problem**: The 3-room segment shows 8 listings for `Draudzības 6a` — a new development where the same developer lists individual units separately. These are legitimate distinct ads but visually dominate the report and skew the stats. The reader has no way to know they're from one building.
**Fix**: In `create_email_body()`, group or annotate listings where `Street` values normalise to the same address. Add a `(N listings at this address)` note next to repeated addresses.

---

## UX improvements

### UX-1: No report date header
**Problem**: The email has no title or date stamp. The reader has no immediate confirmation of which day's data they're looking at.
**File**: `src/ws/app/wsmodules/df_cleaner.py` — `create_email_body()`
**Fix**: Prepend a header line: `=== Ogre Apartment Report — {today's date} ===` before the segment listings.

### UX-2: No currency symbol on prices
**Problem**: All prices are bare integers (`14000`, `56900`). Without context a reader can't confirm currency.
**Fix**: Add `EUR` suffix in `create_email_body()` when formatting the price and SQM price columns.

### UX-3: No "new today" marker on listings
**Problem**: The `Pub_date` column is present but there is no visual distinction between ads published today vs ads that have been listed for weeks. The most actionable data point for a daily report is what is actually new.
**Fix**: In `create_email_body()`, compare `Pub_date` against today's date and append `[NEW]` marker to the row, or add a separate "New today" section at the top of each segment.

### UX-4: Technical DB stats section is in a user-facing email
**Problem**: The bottom section (`LA TBL rows`, `RA TBL rows`, `TSA [A]`, `AinB [C]`, `KLAT A notin B [D]`, etc.) is raw internal database operation output. The variable names are internal abbreviations that mean nothing to a user.
**File**: `src/ws/app/wsmodules/db_worker.py:258-265` and `save_table_row_counts()`
**Two options**:
- **Option A** (minimal): Replace the cryptic abbreviations with plain English in the format string. Example: `"2026-04-22: Scraped today [A]: 45, In DB [B]: 47, Unchanged [C]: 44, New ads [D]: 1, Removed [E]: 3"`.
- **Option B** (better UX): Move this section to a separate "operational summary" block at the bottom, clearly labelled `--- DB Sync Log (internal) ---`, or send it to a separate notification channel (ntfy.sh already exists for this) rather than the main email.

### UX-5: Column header format is inconsistent
**Problem**: The apartment listing sections use a plain text bracketed header `[Rooms, Floor, Size, Price, SQM Price, Apartment Street, Pub_date, URL]` while the price stats table at the bottom uses a proper formatted table (`tabulate` with `pretty` style). The two sections look like they come from different tools.
**Fix**: Either use `tabulate` for the listing sections too (replacing the manual string formatting in `create_email_body()`), or at minimum align the column header format.

### UX-6: Date format inconsistent between sections
**Problem**: Apartment listings use `DD.MM.YYYY` (e.g. `29.04.2026`), the DB sync log uses `YYYY-MM-DD` (e.g. `2026-04-29`), and the "Month:" sections use `MM.YYYY`. Three different formats in one email.
**Fix**: Pick one format (`DD.MM.YYYY` is the most readable for a Latvian audience) and apply it consistently across all sections.

### UX-7: Total ad count missing from report header
**Problem**: The reader must mentally sum the per-segment counts from the price stats table to understand the total market size. The current active listing count is buried in the DB stats (`LA TBL rows: 44`).
**Fix**: Add a one-line summary at the very top: `Active listings: 44 | New today: 1 | Removed: 1 | Total in DB: 2487`.

---

## Code quality / maintainability

### CODE-1: `validate_list_lengths` raises but the raise is commented out
**File**: `src/ws/app/wsmodules/data_format_changer.py:285`
**Problem**: When list lengths mismatch (a parsing error), the error is logged but `# raise ValueError(...)` is commented out. Execution continues with `trim_lists_to_min_length()`, which silently drops data. This is how scraped ads disappear without any visible error.
**Fix**: Uncomment the `raise` or at minimum surface the mismatch count in the email report so data loss is visible.

### CODE-2: `create_file_copy()` uses `os.system()` for a file copy
**File**: `src/ws/app/wsmodules/data_format_changer.py:335`
**Problem**: `os.system('cp pandas_df.csv data/' + dest_file)` is a shell injection risk and a portability issue (breaks on Windows, fails silently if cp is not in PATH).
**Fix**: Replace with `shutil.copy2('pandas_df.csv', dest_path)`.

### CODE-3: `run_analisys.py` executes at import time
**File**: `src/ws/app/wsmodules/run_analisys.py:5,44`
**Problem**: `data_frame = pd.read_csv('cleaned-sorted-df.csv')` and `run_analisys()` execute at module import, not inside a guard. If this module is ever imported elsewhere it will read files and run analysis immediately.
**Fix**: Wrap in `if __name__ == "__main__":`.

### CODE-4: `gen_report.py` executes at import time
**File**: `src/ws/app/wsmodules/gen_report.py:36`
**Problem**: Same pattern — `gen_report(...)` is called at module level.
**Fix**: Wrap in `if __name__ == "__main__":`.

---

## Implementation priority

### Done

| Priority | Item | PR | Merged |
|----------|------|----|--------|
| 1 | BUG-1: Fix month label | #407 | ✅ |
| 2 | BUG-2: Remove duplicate DB row print | #407 | ✅ |
| 3 | BUG-3: Remove duplicate `load_csv_to_df` call | #407 | ✅ |
| 4 | UX-4 Option A: Replace cryptic DB abbreviations | #407 | ✅ |
| 5 | UX-1: Add report date header | #408 | ✅ |
| 6 | UX-7: Add total ad count summary line | #408 | ✅ |
| 7 | UX-3: Mark new-today listings | #408 | ✅ |
| 8 | BUG-4: Fix avg_price calculation | #409 | ✅ |
| 9 | BUG-5: Fix 5-room missing from detail | #409 | ✅ |
| 10 | CODE-1: Restore ValueError raise | #410 | ✅ |
| 11 | UX-2: Add EUR currency label | #413 | ⏳ open PR |
| 12 | UX-6: Unify date format | #413 | ⏳ open PR |
| 13 | DQ-1: Address normalisation | #413 | ⏳ open PR |

### Remaining

| Priority | Item | Effort | Impact |
|----------|------|--------|--------|
| 14 | DQ-2: Flag repeated addresses | `create_email_body` | Medium |
| 15 | CODE-2: Replace `os.system` with `shutil` | 1 line | Low — correctness |
| 16 | CODE-3/4: Add `__main__` guards | 2 files | Low — maintenance |
| 17 | UX-5: Consistent column formatting | `create_email_body` refactor | Low |
