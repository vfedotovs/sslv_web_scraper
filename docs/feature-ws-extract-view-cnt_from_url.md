# Feature: Extract "Unikālo apmeklējumu skaits" (Unique Visits Count) from ss.lv Ad URLs

**Status:** Mostly Implemented (Phases 0-4 complete, Phase 5 pagination done, Phase 6 spiked)  
**Component:** `web_scraper.py` (ws module)  
**Example URL:** https://www.ss.lv/msg/lv/real-estate/flats/ogre-and-reg/ogre/adggo.html  
**Target Value:** `Unikālo apmeklējumu skaits: 997` (value lives inside `<span id="show_cnt_stat">`)  
**Date:** 2026-07-07

## Decisions Made (as of implementation)

- Output key: `UniqueVisits:>` (consistent with Date:/Price:>)
- Visits field is **optional** for MVP (log warning + skip if missing/non-numeric)
- Credible fetching: `requests.Session` + realistic headers + tracking pixel simulation (Phase 3). Playwright available behind `USE_PLAYWRIGHT=1` flag (Phase 6).
- Pagination: dynamic discovery (replaces hardcoded 3 pages).
- Parser: proper BS4 `_extract_clean_text` + dedicated `extract_visits_count`.

## 1. Problem Statement

The current web scraper extracts price, address, size, rooms, floor, series, date, etc. from ss.lv apartment listings but completely ignores the **unique visits counter** (`Unikālo apmeklējumu skaits`).

This value is required (or highly desired) for analytics, ad quality scoring, popularity signals, and downstream reporting.

The scraper uses only `requests` + BeautifulSoup with very fragile string splitting. JavaScript-driven tracking and bot-detection behavior on ss.lv make naive extraction unreliable.

## 2. Current Code Problems (web_scraper.py)

- Hardcoded pagination (only pages 1-3, manual `set()` dedup).
- Extremely brittle parsing everywhere:
  ```python
  tostr = str(data)
  no_front = tostr.split('">', 1)[1]
  name = no_front.split("</", 1)[0]
  ```
- `extract_data_from_url` only processes `table_date[2]` for the date. All other `msg_footer` tds are discarded.
- No `User-Agent`, `Referer`, cookies, or `Session` on detail page requests.
- `get_msg_table_data` retry path does bare `requests.get(msg_url)` (no timeout, no headers).
- Duplicate price writing logic, magic index numbers, `os.system("cp ...")`.
- No handling of nested HTML inside footer cells (especially the visits `<span>`).
- No extraction or output of visits count at all.
- Tests for the scraper are largely commented out.

## 3. Root Cause Analysis — HTML Structure + JavaScript

### Server-rendered location (confirmed via direct fetch)

```html
<td width="250" class="msg_footer" align="right">
  Unikālo apmeklējumu skaits: <span id="show_cnt_stat">997</span>
</td>
```

This is the **5th** `td.msg_footer` element (0-based index 4) among these:

0. Add to favorites / Memo  
1. Print  
2. `Datums: ...` ← current code only reads this (index 2)  
3. Forward / email  
4. **Unikālo apmeklējumu skaits** ← target  
5. Remind + page footer links

### Why JavaScript is involved (non-trivial part)

- The number **is present** in the initial HTML response (server-rendered).
- However, the page also executes:
  - `document.write('<img src="/counter/msg.php?NTc4MTcwNzc=|14742|...` (base64 of internal ad ID `57817077`)
  - `load_script_async("/w_inc/js/msg.count-ss.js?...")`
  - `_puls_counter_local(...)`, `_ps_counter_local(...)`
  - External pixels: `hits.puls.lv`, `top.lv/counter.php`, etc.
- These mechanisms primarily **record** a view (to increment the server-side counter).
- Unique counting logic (cookies, fingerprinting, referrers, time windows) + caching means plain `requests` clients frequently receive low/placeholder values (often `1` in our tests) even when real browsers see hundreds or thousands.
- Re-fetching with proper headers + explicitly firing the tracking pixel(s) can improve fidelity.

Simply doing `soup.find(id="show_cnt_stat")` on a naive request is often insufficient for accurate numbers.

## 4. Action Plan (Phased, Non-Trivial)

### Phase 0 — Reproduce & Instrument (Immediate)
✅ Implemented
- Added `debug_ad_visits()` (usable via `python ... --debug [url]`)
- Dumps footers, extracts `#show_cnt_stat`, logs headers, flags low counts.

### Phase 1 — Replace Brittle Parsing (Foundation)
✅ Implemented
- Added `_extract_clean_text()` helper (replaces all str().split brittle logic).
- Refactored `get_msg_table_data` / `get_msg_table_info`.
- Added `extract_visits_count(soup) -> Optional[int]` (primary span + footer fallback).
- Internal ad_data dict structure in extraction.

### Phase 2 — Add Visits Field Extraction + Output
**Status: ✅ Implemented** (see detailed implementation plan and code in `extract_data_from_url`)

- After successful date extraction, also extract and write:
  ```
  UniqueVisits:>997
  ```
  (decided on `UniqueVisits:>` key)
- Place it consistently (right after `Date:>` line).
- Update `extract_data_from_url` to call the new parser (`extract_visits_count`) and serialize the new field.
- Handle missing / non-numeric cases gracefully (log warning and skip).

### Phase 3 — Credible Fetching (Address the JS/Tracking Reality)
✅ Implemented (see `fetch_detail_page` + helpers)

- `fetch_detail_page()` uses Session + realistic headers + jitter.
- `extract_ad_id()` + `fire_view_tracking()` for /counter/msg.php simulation.
- Optional re-fetch after tracking.
- Integrated into debug and visits extraction.
- Added Playwright spike behind USE_PLAYWRIGHT flag (see Phase 6).

### Phase 4 — Pipeline & Schema Updates
✅ Implemented (core pipeline)

- `data_format_changer.py` now parses UniqueVisits:> into Unique_Visits column.
- `df_cleaner.py` strips prefix + converts to Int64.
- `pandas_df_default.csv` updated with schema.
- (Full analytics/DB/report updates are lower priority / follow-on work.)

### Phase 5 — Pagination & Overall Robustness
✅ Implemented (pagination)
- Replaced hardcoded 3-page logic with dynamic discovery loop in `scrape_website()`.
- Stops on redirect / no new URLs (respects ss.lv behavior).
- (Other robustness items like central fetch layer can be follow-on.)

### Phase 6 — Browser-backed Extraction (When Needed)
✅ Spiked (optional, behind flag)
- Added `fetch_with_playwright()` (requires playwright + env USE_PLAYWRIGHT=1).
- Integrated into `fetch_detail_page()` (falls back gracefully).
- Uses networkidle + waits for #show_cnt_stat.
- Fast requests path remains default.
- (Full evaluation / stealth can be done if counts remain inaccurate.)

## 5. Output Format Decision

Current raw format is line-oriented:

```
https://ss.lv/...
...
Date:>01.07.2026
UniqueVisits:>997
<next url>
```

Keep compatibility for now. Consider emitting a parallel structured artifact (`.jsonl` per run) for future-proofing.

## 6. Risks & Considerations

- **Detection / Blocking**: Firing tracking pixels + high volume can trigger rate limits or degraded HTML. Keep polite delays.
- **Accuracy semantics**: The number you capture is "what ss.lv showed at fetch time". It may or may not include your own simulated view. Document this.
- **Maintenance cost**: ss.lv can change footer structure or counter mechanism. Proper selectors + tests will reduce pain vs. current string hacks.
- **Performance**: Browser automation is slower. Use it judiciously.
- **Downstream impact**: Adding a numeric field affects reports, DB migrations, pandas schemas, and any ML features built on top.
- **Ethics / ToS**: Respect robots.txt and site load. The existing 5s delay is already conservative.

## 7. Testing Strategy

- ✅ Unit tests with realistic ad HTML fragments (include the exact 6 `msg_footer` blocks). (item 13)
- ✅ Regression test that visits extraction survives the crude old parser removal.
- ✅ Integration test (or manual script) against the example URL asserting a plausible integer value. (item 14)
- ✅ End-to-end pipeline test: raw → formatted → cleaned DF → DB contains the field. (item 15)
- Add a health metric: "% of ads with missing or suspiciously low visits count".

## 8. Open Questions / Decisions Needed

1. Preferred output key name? (`UniqueVisits:>`, `Views:>`, `ApmeklejumuSkaits:>`)
2. Should the value be mandatory (fail the ad) or optional (log + continue)?
3. Do we want historical tracking of views per ad (requires DB schema change)?
4. Browser automation: OK to add Playwright as optional dependency, or stay pure requests + clever headers forever?
5. Should we also capture other footer signals (e.g. "Pievienot Memo" interactions) later?

## 9. References / Artifacts

- Source: `src/ws/app/wsmodules/web_scraper.py`
- Example ad: `https://www.ss.lv/msg/lv/real-estate/flats/ogre-and-reg/ogre/adggo.html`
- Internal ad ID pattern: base64 of numeric ID appears in `/counter/msg.php`
- Related modules that will need updates: `data_format_changer.py`, `df_cleaner.py`, `db_worker.py`, analytics/reporting.

---

**Status update (item 16):** All core phases (0-6) and detailed action items 1-18 have been implemented or spiked. See `docs/feature-ws-extract-view-cnt-implementation.md` for per-item status.

**Next Step:** Merge feature branch `feature/ws-extract-view-cnt` → `dev-1.5.13` for staging validation, then to main. Add monitoring for low visit counts if desired.

This document is kept up-to-date as a living record of decisions and completion.
