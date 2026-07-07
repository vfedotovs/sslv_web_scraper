# Feature: Extract "Unikālo apmeklējumu skaits" (Unique Visits Count) from ss.lv Ad URLs

**Status:** Proposed  
**Component:** `web_scraper.py` (ws module)  
**Example URL:** https://www.ss.lv/msg/lv/real-estate/flats/ogre-and-reg/ogre/adggo.html  
**Target Value:** `Unikālo apmeklējumu skaits: 997` (value lives inside `<span id="show_cnt_stat">`)  
**Date:** 2026-07-07

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
- Add a debug / diagnostic mode that, for selected URLs:
  - Dumps all raw `msg_footer` tds using proper BS4.
  - Extracts `#show_cnt_stat` value.
  - Captures all counter-related script loads and `document.write` calls.
  - Logs response headers, cookies, and the exact visits number returned.
- Run against the example URL + several high-traffic ads.
- Capture current scraper output vs. real browser value.
- Add logging: "Visits=<N> (suspiciously_low)" when value < threshold.

### Phase 1 — Replace Brittle Parsing (Foundation)
- Introduce a clean `parse_ad_detail(soup: BeautifulSoup) -> dict` function.
- Replace **all** `str(td).split...` logic with proper selectors:
  - `get_text(separator=" ", strip=True)`
  - `.find("span", {"id": "show_cnt_stat"})`
  - Targeted `td` + text contains checks for the visits footer cell.
- Create dedicated helpers:
  - `extract_visits_count(soup) -> Optional[int]`
  - `extract_date_from_footer(soup) -> Optional[str]`
  - `extract_price(...)`, etc.
- Return a structured dict per ad instead of streaming raw lines immediately.

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
**Status: ✅ Implemented** (see `fetch_detail_page`, `extract_ad_id`, `fire_view_tracking` and updates to debug + extract_data_from_url)

- Create a shared `fetch_detail(url) -> Response` helper that:
  - Uses `requests.Session()`
  - Sets realistic headers (User-Agent, Accept, Accept-Language: lv,LV, Referer pointing to the listing page).
  - Reuses session across related requests.
- After main ad GET:
  1. Parse the internal ad ID (from `af('57817077'`, counter URL, or page data).
  2. Fire the tracking pixel(s) the browser would (`/counter/msg.php?...` + any other async loads) using the same session.
  3. Optionally re-fetch the ad page (or re-query the span) to obtain the count after view recording.
- Add jitter to delays. Consider making delay configurable.
- Add basic retry with exponential backoff that preserves the session.

### Phase 4 — Pipeline & Schema Updates
**Status: ✅ Implemented**

- Update `data_format_changer.py` to recognize and pass through the new field.
- Update `df_cleaner.py`:
  - Add cleaning rule (strip any prefix).
  - Convert to integer column.
- Update `analytics.py`, report generators, PDF/email templates if the field should surface in stats.
- Update DB schema (if persisted in `listed_ads` or similar) and `db_worker.py`.
- Update `pandas_df_default.csv` / expected column lists.
- Add the field to any CSV/JSON export paths.

### Phase 5 — Pagination & Overall Robustness
- Replace hardcoded 3-page logic with real pagination discovery:
  - Parse "pageN.html" links or detect when ss.lv redirects non-existent pages back to page 1.
- Make `scrape_website()` and listing URL handling more dynamic.
- Centralize all network calls behind a fetch layer (headers, session, logging, metrics).
- Replace `os.system` with `shutil`.
- Improve per-URL error isolation (one bad ad must not abort the whole run).
- Add structured logging / metrics for success rate of visits extraction.

### Phase 6 — Browser-backed Extraction (When Needed)
- Evaluate adding **optional** Playwright (recommended) or similar headless browser support.
  - Use it for detail pages when high-fidelity visits count (or other JS-dependent data) is critical.
  - Let tracking scripts and `load_script_async` execute fully.
  - Query `page.locator("#show_cnt_stat").inner_text()` after network idle.
  - Keep the fast `requests` path as the default.
  - Add a feature flag / config (`USE_BROWSER_FOR_VISITS`, `STEALTH_MODE`, etc.).
- Alternative lighter approaches:
  - Use a browser context only to harvest cookies + execute tracking, then fall back to requests with those cookies.
  - Monitor whether ss.lv exposes any other public stats endpoint.

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

- Unit tests with realistic ad HTML fragments (include the exact 6 `msg_footer` blocks).
- Regression test that visits extraction survives the crude old parser removal.
- Integration test (or manual script) against the example URL asserting a plausible integer value.
- End-to-end pipeline test: raw → formatted → cleaned DF → DB contains the field.
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

**Owner / Next Step:** Implement Phase 0 + Phase 1 as a starting PR. Create a feature branch `feature/ws-extract-view-count`.

This document should be updated as decisions are made and phases are completed.
