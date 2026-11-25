# Action Plan: Dynamic Advert Page Count Extraction for ss.lv Scraper

**Context**  
The current implementation in `src/ws/app/wsmodules/web_scraper.py` only scrapes the first page of listings (`CITY_MAIN_URL`). Page count is effectively hard-coded (earlier versions manually fetched page 2/3 with heavy commenting).  

A clear `TODO` exists:  
```python
# TODO: make page count extraction dynamic
```

Example: Jūrmala (`https://www.ss.lv/lv/real-estate/flats/jurmala/sell/`) currently has **6 pages** of apartment sale ads. Other cities vary (Ogre often ~2 pages). Without dynamic detection, data is incomplete for cities with >1 page.

This plan is **implementation-free**. It lists discrete, actionable items with:
- Description
- Estimated effort
- Expected impact
- Recommended order / phase

**Current State Summary (from code review of `src/ws/`)**

**Primary location of the problem:**
- `src/ws/app/wsmodules/web_scraper.py`
  - `scrape_website()` fetches only `page_one`
  - `find_single_page_urls(bs_object)` is per-page and reusable
  - Heavy legacy "Ogre" strings in logs, filenames, and comments
  - `CITY_MAIN_URL = os.getenv(...)` (good — env driven)
  - `URL_LIMIT = 5` (dev safety valve)
  - No pagination parser
  - Comments document ss.lv redirect behavior on non-existent pages (`/page4.html` → main or `/page.html`)

**Related issues (coupled work):**
- `src/ws/app/main.py`: `/run-task/{city}` accepts city but local scrape path is not fully city-aware. `CITY_NAME = "Ogre"` hard-coded. `check_lst_run_state` and cloud/local file checks have mixed naming.
- `data_format_changer.py`: Some city-aware helpers exist (`get_file_path(city_name)`), but many paths/logs still reference "Ogre-raw-data-report*".
- `file_remover.py`, `aws_mailer.py` (and legacy sendgrid_mailer): hard-coded Ogre files and titles.
- `pdf_creator.py`, analytics, etc.: downstream files often assume fixed names.
- `config/cities.yaml` exists and is used by deployment/backup scripts (`deploy-multi-city-ws.sh`, etc.), but **is not loaded by the runtime Python code** inside the `ws` container. Per-city config is passed exclusively via environment variables (`CITY_MAIN_URL`, `EMAIL_CITY_TITLE`).
- Tests in `tests/test_01_module_web_scraper.py`: most scraper tests are commented out.

**Pagination structure (observed on live ss.lv):**
- Pager lives in `<div align=center class=td2 nowrap>` (or nearby).
- Current page: `<button class=navia>1</button>`
- Other pages: `<a class="navi" href=".../pageN.html">N</a>`
- "Nākamie" (next) and "Iepriekšējie" (previous) links exist.
- Relative URLs: `/lv/real-estate/flats/jurmala/sell/page2.html`
- Non-existent high page (e.g. `page99.html`) returns 200 and redirects to base listing page.
- For small cities (Jurmala=6, Ogre~2) all page numbers are rendered on page 1.

**Risks if not addressed**
- Incomplete data for any city >1 page → wrong analytics, price stats, email reports.
- Multi-city rollout (Jūrmala, Riga-region cities, etc.) amplifies the bug.
- Manual page count maintenance is unsustainable.

---

## Actionable Items (Recommended Order)

| # | Item | Description | Effort | Impact | Phase | Notes / Dependencies |
|---|------|-------------|--------|--------|-------|----------------------|
| 1 | Research & document pagination patterns | Fetch and analyze listing pages for all cities in `config/cities.yaml` (Jūrmala, Ogre, Salaspils, Sigulda, Mārupes, Ādaži, etc.). Capture sample HTML snippets for pager on page 1, last page, and 1-page cities. Document edge cases (redirects, single page, possible ellipsis for very large result sets). | Low (2-4h) | High | 1 | Foundation for everything. Use curl + BeautifulSoup exploration. |
| 2 | Implement pure `get_total_pages(bs_object) -> int` function | New function in `web_scraper.py` (or new `pagination.py` util). Parse `<div class=td2>`, collect integers from `navi`/`navia` elements, return `max(..., 1)`. Add defensive fallback. | Medium (0.5-1 day) | High | 1 | Must be unit-testable in isolation. Include sample HTML test fixtures. |
| 3 | Add page URL builder helper | `def get_page_url(base_url: str, page_num: int) -> str`. Handle trailing slash, construct `/pageN.html` correctly. Use `urllib.parse.urljoin` or equivalent for robustness. | Low (1-2h) | Medium | 1 | Simple but important to avoid URL bugs. |
| 4 | Refactor `scrape_website()` to fetch all pages dynamically | Change flow: fetch page 1 → call `get_total_pages` → loop pages 2..N (respect `SCRAPE_DELAY_SEC` or per-page delay) → aggregate ad URLs → deduplicate → proceed to `extract_data_from_url`. Remove/commented static page2/page3 code. Make function accept `main_url: Optional[str] = None` (fall back to env). Update internal logs to be generic ("Extracting for city..."). | Medium-High (1-2 days) | High | 1 | Core change. Keep `URL_LIMIT` behavior for dev but make it overridable (env var `SCRAPE_URL_LIMIT` or similar). |
| 5 | Make `scrape_website` produce city-prefixed working files | Instead of hard-coded `"Ogre-raw-data-report.txt"`, use `{city_slug or "city"}-raw-data-report.txt` (or a generic temp name + explicit output path). Update `create_file_copy()`, `remove_old_file()`. | Medium (0.5 day) | High | 1-2 | Prevents file collisions in multi-city or future parallel runs. |
| 6 | Update `main.py` to fully utilize the `city` path parameter for local scrape | Pass `city` (and derive or pass `CITY_MAIN_URL` if needed) into the scrape path. Update `check_lst_run_state(city)` usage, log messages, and cloud vs local decisions. Remove or parameterize top-level `CITY_NAME = "Ogre"`. | Medium (0.5-1 day) | High | 2 | `CITY_MAIN_URL` remains env-provided per container (preferred for Docker isolation). |
| 7 | Align file naming and temp files across the full pipeline for a given city | Update callers and consumers: `data_format_changer.py` (use city in `get_local_ws_fp` etc.), `file_remover.py`, `aws_mailer.py`, `pdf_creator.py`, `analytics.py` (indirectly), legacy mailers. Introduce a small shared convention (e.g. city slug + date). | High (2-3 days) | High | 2-3 | This is broader multi-city hygiene. Can be done incrementally after core scraper works. High blast radius if rushed. |
| 8 | Add resilience, logging, and politeness improvements | - Retry logic for list page fetches (separate from detail page retries).<br>- Clear progress logs: "Scraping page 3/6 (Jūrmala) — found X new ad URLs".<br>- Configurable delays (env).<br>- Handle N=1 and N=0 gracefully.<br>- Consider `requests.Session` + headers. | Medium (1 day) | Medium | 2 | Important for reliability and observability when page counts increase. |
| 9 | Add / revive unit and integration tests for pagination + multi-page scrape | Implement `test_get_total_pages` with multiple HTML fixtures (1 page, 6 pages, edge cases). Mock `requests.get` for `scrape_website` multi-page scenario. Re-enable/complete commented tests in `test_01_module_web_scraper.py`. Add a simple "page count matches live" smoke idea (optional). | Medium (1 day) | High | 2 | Current test coverage for scraper is weak. |
| 10 | End-to-end verification on real cities | For each city (at minimum Jurmala + Ogre + one other):<br>1. Trigger `/run-task/<city>`<br>2. Compare scraped ad count vs expected (manual or from live page count × ads-per-page).<br>3. Verify no duplicate ads, correct raw file names, downstream analytics use full data.<br>4. Check that requesting non-existent pages is not happening. | Low-Medium (per city, parallelizable) | High | 3 | Do this on a staging or local Docker setup before prod. Use `make` targets or direct curl. |
| 11 | Update documentation and onboarding | Update `docs/WS_Module_Workflow.md`, `CLAUDE.md` (or add note), city onboarding in `README.md`, architecture docs. Document the new pagination logic and how to add a city with many pages. | Low (2-4h) | Medium | 3 | Prevents future regressions. |
| 12 | (Optional) Runtime city configuration loader | Decide whether to load `config/cities.yaml` inside the ws Python app (for display names, validation, etc.) vs. pure env. If yes, implement a small loader with validation. Update deploy scripts if needed. | Medium (1 day) | Medium | 4 | Nice-to-have. Current env-per-container model works well for isolation. |
| 13 | (Optional) Review cloud Lambda scraper parity | Confirm whether the AWS Lambda scraper (source of `local_lambda_raw_scraped_data` files) already extracts full pages. If not, apply similar fix there or document that local path is now the complete one. | TBD | Medium | 4 | Out of scope for local `src/ws` but relevant for overall data quality. |

---

## Recommended Phasing

**Phase 1 — Core correctness (do this first, minimal blast radius)**
- Items 1, 2, 3, 4, 5
- Goal: Local scraper for any city dynamically discovers pages and collects all ads using current env-driven `CITY_MAIN_URL`.
- Success criteria: Jurmala run collects listings from all 6 pages; Ogre still works; no change to file names outside the scraper yet.

**Phase 2 — Integration & safety**
- Items 6, 8, 9
- Wire the city param through `main.py`, improve logging/resilience, add tests.

**Phase 3 — Full multi-city hygiene (larger refactor)**
- Item 7 (standardize file naming everywhere)
- Items 10 + 11 (verification + docs)

**Phase 4 — Polish / future**
- Items 12, 13 and any follow-ups (e.g. total-ads header parsing as secondary signal, rate limiting improvements).

---

## Effort & Risk Summary

- **Total estimated effort (Phase 1 only)**: ~3–5 developer days (assuming one engineer familiar with the codebase).
- **Full plan (all phases)**: ~8–12 days spread over time.
- **Highest risk items**: Item 7 (wide file name changes) and any live HTML structure drift.
- **Mitigations**:
  - Work behind feature flag / `SCRAPE_DYNAMIC_PAGES=true` env (or just branch).
  - Keep old static behavior temporarily if needed.
  - Heavy use of mocks in tests.
  - Test one city at a time.

## Out of Scope (for this plan)

- Changes to the AWS Lambda cloud scraper (unless explicitly included).
- Modifying Docker health checks, scheduler (ts), or DB schema.
- UI / Streamlit data explorer updates.
- Performance optimization of the detail page scraping loop (separate concern).

---

## Quick Validation Checklist (after implementation)

- [ ] `get_total_pages` returns 6 for current Jurmala page 1 HTML.
- [ ] `get_total_pages` returns 1 when there is no pager or only button "1".
- [ ] Full local run for Jurmala produces more ads than before (no missing pages).
- [ ] No "Ogre" strings appear in logs or temp file creation for a non-Ogre city run.
- [ ] `check_lst_run_state` and downstream modules see the correct city-prefixed report file.
- [ ] Existing cities (Ogre, Sigulda, etc.) continue to work unchanged.
- [ ] Unit tests pass (`pytest tests/test_01_module_web_scraper.py -q`).
- [ ] Manual trigger: `curl http://localhost:8000/run-task/jurmala` succeeds cleanly.

---

**Next step after review of this plan**: Prioritize Phase 1 items and assign owners. Consider pairing the pagination extractor implementation with a test-first approach using captured HTML fixtures from Item 1.

*Document created from code review of `src/ws/` on 2026-07-09. Do not implement from this file without updating the plan for any new discoveries.*