# Single Advert Parser — Implementation Plan

Generated: 2026-05-10
Scope: a Python module that fetches a single ss.lv apartment listing and serialises the parsed fields to JSON.

Reference URL (the user's example): `https://www.ss.lv/msg/lv/real-estate/flats/ogre-and-reg/ikskile/cfdgpk.html`

---

## 0. Reconnaissance (do this first, before any coding)

The structure of the JSON, the parsing approach, and the test fixtures all depend on what the actual page contains. Before locking in a schema, capture the source.

### REC-1: Save a working copy of the page HTML
- Download the example URL — both the eu-north-1 staging EC2 and the working eu-west-1 IP range (52.208.0.0/13) can reach ss.lv. The other eu-west-1 range (34.240.0.0/13) is the only confirmed-blocked one so far.
- Save to `tests/fixtures/single_advert_cfdgpk.html`. This is the test-of-record.
- **Why**: parsing tests must not hit the network — both for speed and because GitHub-hosted CI runners may end up in blocked IP ranges even if AWS production hosts are fine.

### REC-2: Identify content blocks
Open the saved HTML and note where each piece of data lives. ss.lv historically uses table-based layouts; expect:
- A `<table>` with class like `options_list` or similar holding key-value pairs (rooms, area, floor, series, etc.).
- A standalone block for price (often nested inside a `td` with a class like `ads_price`).
- A description `<div>` or `<td>` with free-form Latvian text.
- An image carousel with `<img>` tags (need both thumbnail and full-size URLs).
- Phone number in a JS-protected `<a>` tag — may render as base64 or as an obfuscated image.
- Map link / coordinates (latitude/longitude) embedded in a JS variable or data attribute.

### REC-3: Sample a few more URLs
Single-fixture parsers tend to overfit. Save 3-5 more apartment pages from different categories (1-room, 2-room, house, different cities) so the schema and parser handle realistic variation.

---

## 1. Module placement & boundaries

### MOD-1: Where the file lives
Match the existing project convention:
- Path: `src/ws/app/wsmodules/advert_parser.py`
- Public API: `parse_advert(url_or_html: str) -> dict` and `save_advert_json(data: dict, output_path: str) -> None`.
- Entry point: a `__main__` guard so the module can be invoked as `python -m wsmodules.advert_parser <url>` for ad-hoc use.

### MOD-2: Separate fetch from parse
Two distinct functions, in this order:
1. `fetch_html(url: str, timeout: int = 10) -> str` — network I/O only.
2. `parse_html(html: str, source_url: str) -> dict` — pure function, no I/O. **Tests target this one exclusively.**

Rationale: the AWS-IP-block investigation in this project showed that scraping is fragile to where the request originates from. Decoupling fetch from parse means tests stay green even when network is unreachable, and the parser is reusable behind any HTTP client (proxy, headless browser, cached responses).

---

## 2. Dependencies

### DEP-1: HTML parser
Use **BeautifulSoup4 + lxml** (already in `src/ws/requirements.txt` since the existing scraper modules use them). No new dependencies needed unless reconnaissance shows a JS-rendered page — in which case escalate to `playwright` or `selenium` (separate decision; flag if needed).

### DEP-2: HTTP client
Use **`requests`** with explicit timeouts and a custom User-Agent. The existing scraper modules already use it. Avoid `urllib` directly.

### DEP-3: JSON serialisation
Standard library `json`. No new deps.

---

## 3. Output schema

### SCHEMA-1: Draft JSON shape
Lock this in BEFORE writing the parser, otherwise the parser drives the schema and tests have to chase. Suggested initial shape (refine after REC-2/REC-3):

```json
{
  "source_url": "https://www.ss.lv/msg/lv/real-estate/flats/ogre-and-reg/ikskile/cfdgpk.html",
  "listing_id": "cfdgpk",
  "city": "Ikšķile",
  "region": "ogre-and-reg",
  "scraped_at": "2026-05-10T13:42:11Z",

  "address": "...",
  "rooms": 2,
  "area_sqm": 54.0,
  "floor": 3,
  "total_floors": 5,
  "series": "P104",
  "building_material": "panelis",
  "year_built": 1985,

  "price_eur": 49500,
  "price_per_sqm_eur": 916.67,
  "currency": "EUR",

  "description": "Free-form Latvian text...",
  "image_urls": ["https://...", "..."],

  "contact": {
    "phone": "+371 ...",
    "phone_obfuscated": false
  },

  "coordinates": {
    "latitude": 56.8358,
    "longitude": 24.4982
  },

  "raw_fields": { "Istabas": "2", "Platība": "54 m²", "...": "..." }
}
```

### SCHEMA-2: Field nullability
Every field except `source_url`, `listing_id`, and `scraped_at` should be **optional / nullable**. ss.lv listings vary wildly — some omit the floor, some have no images, some have free-text addresses instead of structured. Treating fields as required will break the parser on edge cases.

### SCHEMA-3: Keep `raw_fields`
Always include the unparsed key-value table contents as a `raw_fields` dict. Lets downstream consumers handle any field the typed schema misses, and lets us iterate on the schema without re-scraping.

---

## 4. Parser implementation order

### PARSE-1: Header + IDs
Extract `listing_id` (from URL last path segment, strip `.html`), `city`, `region`. These are derivable from the URL alone — no HTML parsing needed.

### PARSE-2: Structured key-value table
The main `<table>` of the listing has rows like `<tr><td>Istabas:</td><td>2</td></tr>`. Walk the table once, build `raw_fields` dict, then map known Latvian keys to typed fields:

| Latvian | English | Type |
|---|---|---|
| Istabas | rooms | int |
| Platība | area_sqm | float (strip "m²") |
| Stāvs | floor (and total_floors via "3/5") | int + int |
| Sērija | series | str |
| Mājas tips | building_material | str |
| Gads | year_built | int |

### PARSE-3: Price block
ss.lv prices are usually in EUR with thousand separators. Strip `€`/`EUR`, commas, spaces; cast to int (or Decimal — see CODE-1 below). Also extract `price_per_sqm_eur` if shown separately.

### PARSE-4: Description text
Find the description `<div>` or `<td>`. Strip HTML, collapse whitespace. Keep multi-paragraph structure with `\n\n` between paragraphs.

### PARSE-5: Images
Extract all `<img>` URLs from the carousel. Filter out site-chrome images (logos, icons) by matching against the listing image path pattern (typically `/img.lv/...` or similar — confirm in REC-2).

### PARSE-6: Phone number
The trickiest field. ss.lv obfuscates phone numbers to deter scrapers — sometimes as base64-encoded JS, sometimes as inline images, sometimes split across CSS pseudo-elements. **Plan for failure**:
- If the phone is decodable from HTML alone (base64 / numeric concat in JS), do it.
- Otherwise set `phone: null, phone_obfuscated: true` and move on. Don't add Selenium just for this.

### PARSE-7: Coordinates
Look for an embedded JS variable like `var center = [56.8358, 24.4982]` or a `data-lat`/`data-lng` attribute on the map div. Extract with a tight regex over the script tag — don't try to fully parse the JS.

---

## 5. Error handling

### ERR-1: Fetch failures
`fetch_html` should distinguish:
- Connection timeout / DNS fail → raise `AdvertFetchError(reason="unreachable")`
- HTTP 4xx → raise `AdvertFetchError(reason="not_found")` for 404, generic otherwise
- HTTP 5xx → raise with reason="server_error"; let caller retry
- Empty body → same

This matters because the project's prior network issues (AWS IP block on ss.lv) need clear signals to differentiate from "page genuinely doesn't exist."

### ERR-2: Parse failures
`parse_html` should never raise on missing fields — return them as `null` and continue. Only raise on truly malformed input (e.g., the page isn't an ss.lv listing at all). Define a single `AdvertParseError` for that case.

### ERR-3: Logging
Match the pattern used by `aws_mailer.py` (now-cleaned-up version per PR #421): module logger via `logging.getLogger("advert_parser")`, configured idempotently in a `_configure_logging()` function, called from the public entry points. Don't attach handlers at import time.

---

## 6. Testing

### TEST-1: Parser tests against fixtures
- Add `tests/test_advert_parser.py`.
- For each fixture in `tests/fixtures/`, assert known field values (snapshot-style).
- Cover at least: a typical listing, a listing missing the year, a listing with no images, a listing with obfuscated phone.

### TEST-2: Schema validation
- Either hand-rolled (assert each top-level key exists and has expected type) or use `pydantic` / `jsonschema`. Hand-rolled is fine for a 15-field schema.
- This guards against silent schema drift if the parser changes.

### TEST-3: No fetch tests in CI
The `fetch_html` function should NOT be exercised in unit tests. If you want a smoke test, add a manually-invoked script (e.g. `scripts/fetch_advert_smoke.sh`) that hits the live URL — but skip it in `pytest`.

---

## 7. Persistence

### PERSIST-1: JSON file output
- Default path: `./adverts/<listing_id>.json` (relative to cwd, matching the existing project convention — flagged in the aws_mailer review as RF-3, but not worth solving differently here).
- `json.dumps(data, ensure_ascii=False, indent=2)` so Latvian characters render legibly in the file.
- Optionally add `--output-dir` CLI flag.

### PERSIST-2: Optional database write
Out of scope for the first cut. Note as a follow-up: if downstream modules (`db_worker.py`) need to consume parsed data, add a `save_advert_db(data: dict, conn)` that writes to a new `single_adverts` table — separate PR.

---

## 8. Integration with existing project (deferred)

The existing `df_cleaner.py` / `db_worker.py` / `aws_mailer.py` pipeline operates on listing-LIST pages (search results). This new parser operates on individual advert pages. Before wiring it into the cron pipeline:

- Decide WHEN single-advert parsing runs. Options:
  - Per cron tick, walk the search-results listing and fetch each advert page (slow; ss.lv may rate-limit).
  - Only on adverts newly seen in the search-results page (delta-based).
  - Out-of-band, triggered by a separate cron schedule.
- Decide what data is added to the email report based on the new fields.

Ship the parser module standalone first; integrate in a separate PR once usage shape is clear.

---

## 9. Code-quality choices to confirm before writing

These mirror lessons learned from the `aws_mailer.py` review (PRs #419, #420, #421):

| ID | Choice | Default |
|---|---|---|
| **CODE-1** | Numeric type for prices: `int` cents vs `Decimal` vs `float` | `int` for whole-EUR prices; never `float` for money |
| **CODE-2** | Type hints on every public function | Yes — match project's recent convention |
| **CODE-3** | Module docstring with required env vars (e.g. `ADVERT_PARSER_USER_AGENT`) | Yes — same template as the cleaned-up `aws_mailer.py` docstring |
| **CODE-4** | Bare `except Exception` is forbidden; catch specific exceptions | Yes (RF-5 lesson) |
| **CODE-5** | No import-time side effects (logging, network) | Yes (RF-2 lesson) |
| **CODE-6** | Encoding handling | Always `encoding="utf-8"` on file ops; ss.lv pages are utf-8 in `<meta charset>` |

---

## Implementation priority

| Priority | ID | Item | Effort | Reason |
|---|---|---|---|---|
| 1 | REC-1 | Save sample HTML fixture | 5 min | Everything else depends on it |
| 2 | REC-2 + SCHEMA-1 | Identify content blocks + lock schema | 30 min | Avoids schema/parser ping-pong later |
| 3 | MOD-1 + MOD-2 | Skeleton module with `fetch_html` and `parse_html` stubs | 30 min | Establishes the seams before content fills in |
| 4 | PARSE-1 + PARSE-2 | URL-derived fields + structured table | 1 hr | Highest-value fields, simplest to parse |
| 5 | TEST-1 | Fixture-based tests | 30 min | Lock in correctness before adding more parsers |
| 6 | PARSE-3..5 | Price, description, images | 1 hr | Routine extraction once the seams exist |
| 7 | ERR-1..3 + PERSIST-1 | Error handling + JSON file output | 1 hr | Production-readiness |
| 8 | PARSE-6 + PARSE-7 | Phone (best-effort) + coordinates | 30 min - 2 hrs | Nice-to-have; phone may be unparseable from HTML |
| 9 | REC-3 | Sample more URLs, refine schema | 30 min | Catches single-fixture overfit |
| 10 | MOD-CLI | `__main__` entry point + argparse | 15 min | Convenience |

**Total**: ~6-8 hours for a feature-complete, well-tested module without DB integration.

---

## Open questions to resolve before coding

1. **Network access**: which environment will run the parser? Both the eu-north-1 staging EC2 and the working eu-west-1 prod EC2 can reach ss.lv directly — no proxy required. Just confirm the chosen host before wiring the fetch step into a cron schedule.
2. **Rate limiting**: how often will single-advert pages be fetched? ss.lv may throttle aggressive scraping. Add a per-host delay (`time.sleep(1)`) between fetches in any batch driver, even if the parser itself is stateless.
3. **Robots.txt / ToS**: out of scope for the parser code, but worth confirming with the project owner that scraping individual listing pages is in line with the operational practice already established by the existing scraper.
4. **Phone-number obfuscation**: how strict is the requirement? If the phone field is genuinely needed (and not just nice-to-have), this drives a major architectural decision (keep it pure-HTTP, or escalate to headless browser). Default in this plan: best-effort, fall back to null. Confirm.
