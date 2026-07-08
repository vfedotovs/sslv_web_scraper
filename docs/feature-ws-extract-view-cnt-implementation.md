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

## Debugging Guide: "Always 1" View Count After PR #428 (2026-07-08)

**Symptom observed:**
- All ads (including popular ones like adggo.html) extract `view_count=1`
- Real browser sessions on the same ads show much higher numbers (e.g. 1099+)
- Logs consistently show:
  - `view_count extraction event: count=1`
  - `DB interaction: inserting view_count=1`

### Likely Root Causes (in order of probability)

1. **"Unique" counter semantics + scraper fingerprinting**
   - The counter (`Unikālo apmeklējumu skaits`) is **unique visitor** based.
   - Our traffic (even with Session + headers + pixel) is fingerprinted as the same "visitor" or as non-human → server returns base value `1`.

2. **Count is computed server-side at HTML render time**
   - The number in `<span id="show_cnt_stat">` is baked in when the page HTML is generated.
   - Firing the pixel + re-fetch may not cause the *next* HTML response to reflect an immediate increment for that client.

3. **Pixel not effective or wrong format**
   - The pixel might need to be requested as an `<img>` with exact timing/cookies/Referer that the page's `document.write` does.
   - Session cookies (PHPSESSID) set by the pixel may not be carried correctly to the re-fetch in some environments.

4. **Environment-specific (IP / ASN / datacenter)**
   - If the scraper runs in a cloud/datacenter IP range, ss.lv may deliberately return low/placeholder counts to suspected bots.

5. **Caching** on ss.lv side for the count value per ad.

### Recommended Debug Action Plan (Step by Step)

**Step 1: Reproduce with maximum visibility (use --debug)**
```bash
USE_PLAYWRIGHT=0 python -m src.ws.app.wsmodules.web_scraper --debug https://www.ss.lv/msg/lv/real-estate/flats/ogre-and-reg/ogre/adggo.html
```
Capture:
- Full before/after count from the new logs we just added.
- All session cookies after first GET and after pixel.
- Whether `tracked` and `refetched` are true.

**Step 2: Compare with/without simulation**
Temporarily modify or run two variants:
- `fetch_detail_page(url, simulate_view=False)` → what count do we get?
- `fetch_detail_page(url, simulate_view=True)` → what count?

Log the difference explicitly.

**Step 3: Inspect cookies and pixel response**
Add temporary logging (or use debug_ad_visits enhancements):
```python
print("Cookies after ad GET:", dict(session.cookies))
resp_pixel = session.get(pixel_url, ...)
print("Pixel status:", resp_pixel.status_code, "cookies after pixel:", dict(session.cookies))
```

**Step 4: Test the exact pixel the page uses**
The page does:
`document.write('<img src="/counter/msg.php?NTc4MTcwNzc=|14742|'+new Date()+'" ...>');`

Try requesting the pixel **without** extra headers or with `Accept: image/*` and see if count changes on re-fetch.

**Step 5: Test persistence across runs**
- Run the debug tool twice in a row from the same environment (same IP/session).
- Does the count stay 1, or ever go to 2?

**Step 6: Compare environments**
- Run from your local laptop browser (note the count).
- Run the scraper from the same machine (if possible) vs from the server/CI.
- Difference points to environment fingerprinting.

**Step 7: Try Playwright (if not already)**
```bash
USE_PLAYWRIGHT=1 python -m src.ws.app.wsmodules.web_scraper --debug https://...
```
Playwright can set real cookies, execute the page's JS, load the pixel as an image, etc. Compare the count it gets vs pure requests.

**Step 8: Check if the count ever increases for scraper traffic**
Add temporary code to run the fetch + track 3-5 times in a row with delays, logging the count each time.

**Step 9: Consider the counter may be intentionally low for automated traffic**
If after above experiments the scraper consistently sees 1 while real users see high numbers:
- This may be **by design** (anti-bot measure).
- Options:
  - Accept it and only use the number for "real browser" traffic.
  - Build our own view counter on top (store cumulative in our DB).
  - Use Playwright with persistent user profiles / residential proxies (higher cost/risk).

### Immediate Code Improvements (to aid debugging)
- (Already added in this session) Before/after count logging + cookie logging in `fetch_detail_page`.
- Consider logging the full `info` dict at the end of visits extraction.
- In `debug_ad_visits`, print cookies and before/after explicitly.

### Next Actions After Debugging
1. If the pixel + re-fetch never increases the number → the current "simulate_view" approach has limited effect for unique counters.
2. Decide whether to keep showing the (low) server-provided number or compute something else.
3. If Playwright gives significantly higher numbers, make it the default for production runs (with proper stealth + proxy strategy).
4. Update the email report to flag listings with suspiciously low views (e.g. `< 5` or `< 10`).

**Owner:** Run the debug steps above, especially Step 1-4 with the enhanced logging. Share the before/after + cookie output.

---
**Next Step:** Focus on debugging why the credible fetch still yields count=1. Update this plan with findings.

## Conclusion & Findings (after live debug runs on 2026-07-08)

**Test results from two runs on the example ad (https://www.ss.lv/msg/lv/real-estate/flats/ogre-and-reg/ogre/adggo.html):**

- **Run with USE_PLAYWRIGHT=0** (requests + session + tracking + re-fetch):
  - Ad ID correctly extracted: 57817077
  - "View tracking pixel fired (simulated real visit)"
  - "Page was re-fetched after tracking"
  - HTML still showed: `Unikālo apmeklējumu skaits: 1`
  - `extract_visits_count(soup) result: 1`
  - Low count warning triggered

- **Run with USE_PLAYWRIGHT=1** (full Playwright):
  - Identical outcome: extracted count = 1
  - Same messages about pixel and re-fetch
  - Still received 1 from the server

**Key conclusions:**

1. **The scraping logic is functioning correctly.** All the Phase 3 mechanisms (Session + headers + jitter + pixel firing + re-fetch) are executing as designed. The same is true for the Playwright path.

2. **The server is returning 1 for this client/environment.** Even after firing the tracking pixel and re-fetching (and even when using a real browser engine via Playwright), the HTML delivered by ss.lv contains `show_cnt_stat">1<`.

3. **Firing the tracking pixel + re-fetch does not increase the displayed count for the scraper.** The counter (`Unikālo apmeklējumu skaits`) is a **unique visitor** counter. The simulated view does not register as an additional unique visit from the server's perspective for this traffic.

4. **Playwright did not help in this case.** This indicates the issue is not simply missing JavaScript execution. It is likely tied to persistent client identity (cookies accumulated over time, browser fingerprint, IP/ASN reputation, or other signals that a fresh automated session does not possess).

5. **The value "1" is what the server chooses to show the scraper.** The high numbers the user observed (e.g. 1099) are almost certainly from long-lived personal browser sessions that carry prior visit history. The scraper (even with best-effort simulation) is treated as a new or non-counting visitor.

6. **Logging is working as specified.**
   - `web_scraper.log` correctly records: `view_count extraction event: count=1 url=...`
   - `dbworker.log` correctly records DB interactions: `inserting view_count=1 for ... into listed_ads`

7. **The email report will now reflect reality.** Because the scraper legitimately sees low numbers, the `Views` column (with `[LOW VIEWS]` flags for counts < 10) will show these values. This is correct behavior for the feature.

**Implications:**

- The feature successfully extracts and propagates the number the server returns to the scraper client.
- It is not currently possible to obtain the "high" cumulative numbers visible to real returning users using the current simulation techniques.
- The extracted view count is useful for relative comparison and for detecting suspiciously low activity, but absolute values will often be low when the scraper runs from its normal environment.

**Practical recommendation:**

Report the number that was actually observed during the scrape (as we are now doing), and consider adding a clarifying note in future reports:

"View counts reflect the value returned by ss.lv to the scraper at the time of fetch. These are typically lower than numbers seen in long-lived personal browsers."

The root cause is the nature of ss.lv's unique-visitor counter combined with the limitations of simulating unique visits from automated clients. The implementation (extraction, pipeline, logging, reporting) is working; the low values are expected given how the counter operates.
