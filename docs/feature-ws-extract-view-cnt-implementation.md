# Implementation Plan: Extract "Unikālo apmeklējumu skaits" (Unique Visits Count)

**Feature:** ws-extract-view-cnt  
**Related document:** [feature-ws-extract-view-cnt_from_url.md](./feature-ws-extract-view-cnt_from_url.md)  
**Branch:** `feature/ws-extract-view-cnt`  
**Date:** 2026-07-07  
**Status:** Ready for implementation

## Overview

This document provides a detailed, ordered action item list derived from the high-level plan. Items are prioritized for safe, incremental delivery with clear effort and impact assessments.

## Decisions Made

### Item #1: Output Key Name and Optionality
- **Chosen key:** `UniqueVisits:>`
- **Optionality:** Optional for MVP (log warning and skip if extraction fails or value is invalid)
- **Rationale:** Clear, descriptive, consistent with existing `Date:>`, `Price:>` format. "UniqueVisits" matches the Latvian "Unikālo apmeklējumu skaits".
- **Status:** ✅ Implemented (constant `UNIQUE_VISITS_OUTPUT_KEY` defined in web_scraper.py)
- **Date:** 2026-07-07

### Item #2: Debug / Instrumentation
- **Status:** ✅ Implemented (`debug_ad_visits()` function + `--debug` CLI support)
- Supports dumping footers, extracting #show_cnt_stat, logging headers, and low-count warnings.

### Item #3: Reusable Test Fixtures
- **Status:** ✅ Implemented
- Created `tests/fixtures/ad_footer_sample.html` with the 6 msg_footer tds (including the visits span with value 997)
- Added `test_load_footer_fixture_has_visits_span()` in `tests/test_01_module_web_scraper.py`

### Item #4: Refactor get_msg_table_data (and related)
- **Status:** ✅ Implemented
- Introduced `_extract_clean_text(element)` helper using `get_text(separator=" ", strip=True)` + whitespace normalization.
- Replaced all `str(td).split('">')` brittle logic in `get_msg_table_data`, `get_msg_table_info`.
- Added basic None checks for table.
- Also improved `get_msg_table_data` with timeout and broader error handling.
- This affects all data extraction (ads_opt, price, footer, etc.) positively.

### Item #5: Implement extract_visits_count
- **Status:** ✅ Implemented
- Added `extract_visits_count(soup: BeautifulSoup) -> Optional[int]`
- Primary: looks for `<span id="show_cnt_stat">`
- Fallback: scans msg_footer tds for "Unikālo apmeklējumu skaits" and extracts the number.
- Reuses the new `_extract_clean_text`.
- Ready to be used in `extract_data_from_url` (see item 6).

### Items 6 + 7: Integrate visits output + update extract_data_from_url
- **Status:** ✅ Implemented
- Refactored `extract_data_from_url` to use per-ad `ad_data` dict for cleaner structure.
- Integrated `extract_visits_count` after the Date line.
- Writes `UniqueVisits:>NNN` using the constant.
- Removed duplicate price write logic.
- Graceful handling: if visits is None or non-numeric → log warning, skip writing the line.
- Uses the same output format (`Key:>value`) for compatibility.
- Added timeout to the visits fetch.

### Items 11 + 12: Phase 3 Credible Fetching
- **Status:** ✅ Implemented
- Added `fetch_detail_page(url, simulate_view=True, use_session=True)`:
  - Uses `requests.Session()` + realistic headers (UA, Accept-Language, Referer).
  - Jitter (`random.uniform`).
  - Extracts ad ID via `extract_ad_id`.
  - Fires tracking pixel via `fire_view_tracking` (the /counter/msg.php mechanism).
  - Optionally re-fetches after tracking.
- Updated `debug_ad_visits` and the visits extraction in `extract_data_from_url` to use the new credible fetch.
- Added `extract_ad_id` and `fire_view_tracking` helpers.
- This should produce more realistic (higher) visit counts than plain requests.

### Items 8 + 9 + 10: Phase 4 Pipeline & Schema Updates
- **Status:** ✅ Implemented (verified with test data)
- Updated `data_format_changer.py` (`create_oneline_report`):
  - Added parsing for "UniqueVisits:" lines.
  - Added `unique_visits` list, updated trim/validate/unpack and mydict with 'Unique_Visits' column.
- Updated `df_cleaner.py`:
  - Added `df.replace(to_replace=r'UniqueVisits:>', value='', regex=True, inplace=True)`
  - Added conversion of 'Unique_Visits' to Int64 after cleaning.
- Updated `pandas_df_default.csv` with header including Unique_Visits and sample row.
- Schema expectations in pandas_df and column handling now support the new field (existing named-column code continues to work; verified parser + clean produces correct column and numeric values).

Future items will reference this decision.

The implementation should follow the current workflow:
- Develop on `feature/ws-extract-view-cnt`
- Merge to `dev-1.5.13` for staging validation (manual "Deploy to Staging")
- Only merge to `main` after successful staging runs

## Ordered Action Items

| # | Action Item | Phase | Effort | Impact | Dependencies | Blast Radius / Risk | Notes / Order Rationale |
|---|-------------|-------|--------|--------|--------------|---------------------|-------------------------|
| 1 | **Decide output key name** (`UniqueVisits:>`, `Visits:>`, `ApmeklejumuSkaits:>`, etc.) and whether the field is mandatory or optional | Decision | XS | High | — | Low | **Do this first**. Blocks all output changes. |
| 2 | Add debug/instrumentation mode (or CLI flag) that dumps all `msg_footer` tds, extracts `#show_cnt_stat`, logs headers, and flags suspiciously low values | Phase 0 | S | Medium | — | Low | Quick win. Helps validate counts during development on staging. |
| 3 | Create reusable test fixtures: realistic HTML fragments containing the 6 `msg_footer` tds (with nested `<span id="show_cnt_stat">`) | Testing | S | High | — | Low | Critical for unit testing the parser refactor. |
| 4 | Refactor `get_msg_table_data` (and related functions) to stop using `str(td).split...` and use proper BeautifulSoup methods (`get_text()`, `.find()`, CSS selectors) | Phase 1 | M | **Very High** | #3 | Medium (affects all fields) | **Highest priority technical debt item**. Everything else becomes easier after this. |
| 5 | Implement dedicated `extract_visits_count(soup) -> Optional[int]` (or similar) that reliably pulls the value from the correct footer cell + span | Phase 1 / 2 | S | High | #4 | Low | Core of the feature. |
| 6 | Refactor `extract_data_from_url` to use a cleaner structure (ideally return a dict per ad first) and consistently write the visits line (e.g. after `Date:>`) | Phase 1 / 2 | M | High | #4, #5 | Medium | Cleans up duplicate price code and magic index logic at the same time. |
| 7 | Update raw output format and ensure `write_line` calls for visits are robust (handle missing/non-numeric gracefully) | Phase 2 | S | Medium | #1, #6 | Low | Keep backward-compatible `Key:>value` format for now. |
| 8 | Update `data_format_changer.py` (`create_oneline_report`) to parse the new visits line and include it in the DataFrame | Phase 4 | M | High | #7 | Medium | Parser here is also somewhat hardcoded (regex per known field). |
| 9 | Update `df_cleaner.py` — add cleaning rule for the new key and (if desired) convert to integer | Phase 4 | S | Medium | #8 | Low | Small change but required for clean data. |
| 10 | Update pandas schema expectations (`pandas_df_default.csv`, column lists, any hardcoded expectations in analytics/reports) | Phase 4 | S–M | Medium | #8, #9 | Medium | Check `analytics.py`, `db_worker.py`, PDF/email templates. |
| 11 | Improve detail page fetching: introduce `requests.Session()`, add realistic headers (User-Agent, Referer, Accept-Language), jitter, and better retry logic | Phase 3 | M | Medium–High | — | Low–Medium | Improves visits count fidelity even without tracking simulation. |
| 12 | (Optional but recommended for accuracy) Add logic to simulate the tracking pixel (`/counter/msg.php`) after fetching the ad page using the same session | Phase 3 | M | Medium | #11 | Medium (rate-limit risk) | Can improve the number returned by ss.lv. Document the semantics. |
| 13 | Write proper unit tests for the new visits extraction + parser changes (uncomment/fix existing test file) | Testing | M | High | #3, #4, #5 | Low | Currently very weak test coverage. | ✅ Implemented (added tests for extract_visits_count and clean parsing in test_01)
| 14 | Add/update integration test that runs against a real ad (or fixture) and asserts visits field appears | Testing | S–M | Medium | #13 | Low | Can be skipped in CI or use mocked responses. | ✅ Implemented (using ad_footer_sample fixture + mocks)
| 15 | Perform end-to-end validation on staging: build raw report → format → clean → check visits column appears with plausible value | Validation | S | High | All above | Low (staging only) | Use your current `feature/ws-extract-view-cnt` + `dev-1.5.13` flow + manual "Deploy to Staging". | ✅ Implemented (E2E test in test_01 using temp raw report -> DF -> cleaned with Unique_Visits) |
| 16 | Update the plan document (`feature-ws-extract-view-cnt_from_url.md`) with decisions made and mark completed items | Housekeeping | XS | Low | #1 | Low | Keep it as living documentation. | ✅ Done (high-level plan updated with statuses + decisions)
| 17 | (Lower priority) Replace hardcoded 3-page pagination with dynamic page discovery | Phase 5 | M–L | Medium | — | Low | Can be done in a separate PR. Not required for the visits feature. | ✅ Done (dynamic loop in scrape_website using redirect/empty detection)
| 18 | Evaluate / spike optional Playwright support for higher-fidelity counts (behind feature flag) | Phase 6 | L | Low–Medium | — | Low | Only if counts from requests+headers are consistently too low. | ✅ Spiked (`fetch_with_playwright()` + integration in fetch_detail_page, gated by USE_PLAYWRIGHT=1) |

## Effort & Impact Summary

| Effort Level | Count | Typical Items |
|--------------|-------|---------------|
| **XS / S**   | 7     | Decisions, small updates, instrumentation, dedicated helper |
| **M**        | 7     | Core parser refactor, output changes, fetching improvements, tests |
| **L / XL**   | 2     | Pagination, browser automation |

| Impact Level | Notes |
|--------------|-------|
| **High**     | Items 1, 3, 4, 5, 6, 8, 13, 15 — these either unlock the feature or fix foundational problems |
| **Medium**   | Fetching improvements, downstream schema updates, optional tracking simulation |
| **Low**      | Pure robustness (pagination), browser spike, doc updates |

## Recommended Sequencing & MVP Cut

**MVP (get the value flowing safely):**
Items **1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 11 → 13 → 15**

Do the foundation refactor (#4) early — it has the highest long-term impact and reduces risk of future breakage.

**Post-MVP / follow-up:**
Items 10, 12, 14, 16, 17, 18

## Additional Recommendations

- Work on `feature/ws-extract-view-cnt`, merge to `dev-1.5.13` for staging validation, and only merge to `main` after successful staging runs.
- Consider emitting the visits field as optional initially (log warning + continue if missing) to reduce risk.
- After the parser refactor, you may want to introduce a small `AdData` dataclass or TypedDict for cleaner code.
- Because `data_format_changer.py` does not do generic key parsing, adding fields will always require a small change there until that is improved.
- Respect polite delays (existing 5s) and robots.txt when testing against real ss.lv pages.

## Open Questions to Resolve Early

1. Preferred output key name?
2. Should the value be mandatory or optional?
3. Do we need historical tracking of view counts in DB?
4. When (if ever) do we introduce browser automation?

---

**Next Step:** Start with item #1 (decision) and item #4 (parser refactor foundation) on the feature branch.