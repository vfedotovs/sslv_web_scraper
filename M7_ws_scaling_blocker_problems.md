
Here's how I'd design it clean-sheet. First a reality check that shapes everything: 3000 detail fetches/day is *small* — about two requests per minute if spread out. So the architecture should optimize for correctness, politeness to ss.lv, and observability, **not** raw throughput. That changes what matters.

## Core principle: separate the four concerns

The current code fuses fetching, parsing, diffing, and reporting into one synchronous pass. I'd split them into distinct stages that hand off through storage, so each can fail, retry, and be replayed independently:

**Discover → Fetch → Parse → Diff/Persist → Report**

## The components

**1. City registry (config, not code).** A table or config file listing each city, its ss.lv section URL(s), and per-city settings (enabled, schedule, expected volume). Adding city #11 becomes a row, never a code change. This is the single thing the hardcoded `CITY_NAME = "Ogre"` most needs to become.

**2. Scheduler + job queue.** A scheduler (cron-like) enqueues one "scrape city" job per enabled city daily. A queue (RQ/arq/Celery) decouples triggering from execution, gives you retries and concurrency control, and means an HTTP endpoint or timer just enqueues and returns — nothing blocks for minutes.

**3. Two-phase scraping.**
- *Discovery* walks a city's listing pages and produces the set of ad URLs that exist today. This alone is your "still listed" universe.
- *Extraction* fetches each ad's data. Whether you need detail-page fetches or the listing rows suffice depends on ss.lv's markup — but keeping discovery separate means you always have today's URL set even if some detail fetches fail.

**4. A polite fetch layer, shared by both phases.** Central place for a per-domain rate limiter, exponential backoff with jitter, a real User-Agent, conditional requests (ETag/If-Modified-Since) to skip unchanged pages, and a bounded concurrency pool. At 3000 URLs you can afford to be slow and gentle; this layer is what keeps you from getting blocked.

**5. Raw landing zone.** Persist the raw fetched HTML/JSON (S3 or a raw table) *before* parsing, keyed by city+date+url_hash. This is the highest-leverage design choice: when a parser bug appears or ss.lv changes layout, you re-parse from stored snapshots instead of re-scraping the site. It also makes the pipeline idempotent and auditable.

**6. Parser/adapter layer.** Per-site (and if needed per-city) parsing that turns raw pages into normalized records, followed by a validation step that rejects or quarantines malformed rows rather than letting them corrupt the DB. Site-specific brittleness (like the fixed `split("/", 9)` hash extraction) lives here, isolated behind an interface.

**7. Diff engine — set-based, per city.** For each city: `today = set(scraped hashes)`, `db = set(currently-listed hashes)`, then `new = today − db`, `removed = db − today`, `still = today ∩ db`. O(N+M), and scoped by city so cities never interfere.

## The data model

I'd move away from the three-table listed/removed juggling toward an event-sourced shape:

- **`ads`** — current state, one row per (city, url_hash): fields, `first_seen`, `last_seen`, `status` (active/removed), `days_listed` as a derived value.
- **`price_history`** — append-only (ad, date, price). This is what actually gives you trend tracking, which the current schema can't do well.
- **`ad_events`** — append-only log of listed / removed / price_changed. Reporting reads from here.
- **`scrape_runs`** — one row per (city, date) with counts and status; this is your idempotency guard and your dashboard source, replacing the filesystem marker files.

The daily write then collapses to two bulk operations per city: upsert everything scraped today (setting `last_seen = today`, appending price rows), then mark `status = 'removed'` where `last_seen < today`. No per-row loops, no per-ad connections, one transaction per city.

## Reporting and observability, decoupled

Report generation and email become **consumers** of the DB/event log on their own schedule, not steps welded into the scrape. And because every stage writes to `scrape_runs`, you get monitoring almost for free: alert when a city's scraped count drops to zero (parser broke or site changed), when removed-count spikes abnormally (likely a discovery failure, not real delistings), or when a run doesn't complete.

## Why this scales past 3000

Cities run concurrently as independent jobs; the diff is linear and per-city; DB writes are bulk and transactional; raw snapshots make reprocessing free; and the whole thing is idempotent — re-running a day is safe. The bottleneck stays where it should: polite request pacing to ss.lv, which is a deliberate throttle, not an accident of design.

One decision worth making early: how much history you want. If price-trend analysis over months is a real goal, the `price_history` + `ad_events` split matters a lot; if you only ever care about "what's listed now," you could simplify. Want me to sketch the schema in detail, or map this onto specific infrastructure (e.g. AWS, given the repo already uses Lambda + S3)?
