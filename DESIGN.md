# Smart House Hunting Design

## 1. Goals and Constraints

This document translates `REQUIREMENTS.md` into an implementation design.

The system is a single-user, localhost-only web application for finding an owner-occupied home in Massachusetts. It scans Redfin, Zillow, and Realtor only when the user presses `GO`. LLM analysis is a separate, explicitly triggered operation.

The design optimizes for:

- Long-term maintainability by one household.
- Clear source provenance and reversible deduplication.
- Idempotent scans and recoverable background jobs.
- Explicit control over cloud LLM calls.
- Simple local deployment with no database or Node server to operate.

The main technical risk is source acquisition. Public websites can change markup, rate-limit access, or require browser interaction. Source-specific code must therefore remain isolated and independently testable.

## 2. Technology Stack

### Backend

- Python
- FastAPI and Uvicorn
- Pydantic for API, configuration, and profile validation
- SQLAlchemy 2 for persistence
- Alembic for schema migrations
- SQLite in WAL mode
- HTTPX for ordinary HTTP requests and LLM calls
- Playwright for sources that require a real browser

### Frontend

- React
- TypeScript
- Vite
- Native `fetch` for JSON APIs
- Server-Sent Events for job progress
- CSS Modules or plain scoped CSS
- Google Maps JavaScript API for explicitly selected property markers

React Router should be added only if the interface grows beyond a results page and a property-detail route. Redux, Next.js, SSR, Tailwind, and a production Node server are not required.

During development, Vite proxies `/api` to FastAPI. A production build generates static assets that FastAPI serves alongside the API, so production still runs as one Python process.

### Persistent Formats

- YAML: application configuration and the private household profile.
- SQLite: canonical properties, listings, scans, history, comparables, and LLM results.
- Optional compressed JSON: source diagnostic fixtures or retained extraction payloads.
- CSV: export only; never the source of truth.

## 3. Runtime Layout

Default paths:

```text
~/.config/smart_house_hunting/config.yaml
<configured private path>/house_profile.yaml
<configured private path>/backups/
~/.local/share/smart_house_hunting/app.db
~/.local/state/smart_house_hunting/app.log
```

The server binds to `localhost` on port `7004` by default. FastAPI serves both `/api/*` and the compiled React assets.

The application uses one web process and one in-process job worker. No Celery, Redis, PostgreSQL, or separate frontend server is used in production.

## 4. Repository Layout

Proposed layout:

```text
smart_house_hunting/
  pyproject.toml
  alembic.ini
  src/smart_house_hunting/
    main.py
    api/
      config.py
      profile.py
      scans.py
      properties.py
      analyses.py
      exports.py
    config/
      models.py
      loader.py
    profile/
      models.py
      storage.py
      backup.py
    db/
      engine.py
      models.py
      migrations/
      repositories/
    jobs/
      manager.py
      models.py
      events.py
    sources/
      base.py
      redfin.py
      zillow.py
      realtor.py
      normalization.py
    dedup/
      address.py
      matcher.py
      resolver.py
    finance/
      models.py
      calculator.py
    llm/
      base.py
      providers.py
      prompts.py
      schemas.py
      service.py
    maps/
      models.py
      places.py
      routes.py
      service.py
    services/
      scan.py
      property.py
      comparable.py
      analysis.py
  frontend/
    package.json
    vite.config.ts
    src/
      api/
      components/
      hooks/
      pages/
      types/
  tests/
    fixtures/sources/
    unit/
    integration/
```

Source adapters, deduplication, finance, and LLM logic are domain modules rather than API-handler code. API handlers validate requests and delegate to services.

## 5. Configuration and Profile

### 5.1 Application Configuration

Conceptual configuration:

```yaml
profile_file: /private/path/house_profile.yaml

search:
  state: MA
  municipalities:
    - "<town-one>"
    - "<town-two>"
  included_property_types:
    - single_family
  minimum_bedrooms: 0
  minimum_bathrooms: 0

finance:
  mortgage_years: 30
  default_down_payment_percent: 20
  annual_interest_rate:
    low: 0.060
    high: 0.075
  annual_insurance_rate:
    low: 0.002
    high: 0.005
  annual_maintenance_rate:
    low: 0.005
    high: 0.015
  closing_cost_rate:
    low: 0.02
    high: 0.05

llm:
  default_provider: google
  timeout_seconds: 180
  providers:
    google:
      base_url: https://generativelanguage.googleapis.com/v1beta/openai
      api_key: "..."
      model: "..."
    ollama:
      base_url: http://localhost:11434/v1
      api_key: dummy
      model: "..."

maps:
  enabled: false
  browser_api_key_env: GOOGLE_MAPS_BROWSER_API_KEY
  backend_api_key_env: GOOGLE_MAPS_BACKEND_API_KEY
  nearby_search_radius_meters: 2500
  cache_days: 14
```

Rates above are examples, not product-prescribed defaults. They must be reviewed when the implementation reaches financial configuration.

Provider-specific environment variables may override secrets and endpoint settings. LLM and backend service keys are backend-only, masked in settings responses, and never logged. The restricted Google Maps JavaScript browser key is the sole planned exception because that SDK executes in the browser.

### 5.2 Household Profile

Conceptual profile:

```yaml
family: |
  ...

must_have: |
  ...

good_to_have: |
  ...

finance:
  current_annual_gross_income: 0
  minimum_future_annual_gross_income: 0
  annual_travel_spending: 0
  down_payment:
    mode: amount
    value: 0
```

Money is represented with decimal arithmetic, not binary floating point.

### 5.3 Saving and Backup

The profile service owns all reads and writes. Saving performs:

1. Validate the complete profile.
2. Acquire a profile-file lock.
3. Determine the local calendar date.
4. If the profile exists and today's backup does not, copy the current file to the backup path.
5. Write the new YAML to a temporary sibling file.
6. Flush and atomically replace the profile.
7. Return a SHA-256 hash of the canonical profile data.

The backup is the state before the first save of the day. Reading never creates a backup.

The database stores the profile hash and timestamps needed for evaluation versioning, not a second plaintext copy of the private profile.

## 6. Database Design

SQLite runs in WAL mode with foreign keys enabled. Schema changes use Alembic migrations. A database backup should be taken before applying a non-trivial migration.

### 6.1 Main Entities

#### `properties`

One physical property or condo unit:

- Canonical address components.
- Municipality, state, and ZIP code.
- Unit number.
- Coordinates.
- Parcel or assessor identifier when known.
- Persistent user-defined manual-review tags, with 双黄线, Corner lot, and 剪刀煞 as defaults.
- Manual fallback property facts stored separately from crawled listing states.
- Creation and update timestamps.

#### `property_aliases`

Normalized addresses, source identities, and other match keys that resolve to a property. This makes deduplication explainable and allows a bad match to be corrected without destroying source data.

#### `property_duplicate_candidates`

Reversible links between records that may represent the same property but lack enough evidence for an automatic merge. The reason, confidence, and review status remain inspectable.

#### `listings`

A source-specific listing episode:

- Property ID.
- Source and source listing ID.
- Source URL.
- Listing episode identity.
- First and last seen times.

A relisted property may have more than one listing episode.

#### `listing_states`

Versioned source facts such as status, price, bedrooms, bathrooms, area, tax, HOA, description, and source timestamps. Each normalized state has a content hash. An unchanged state is reused rather than duplicated.

#### `scan_jobs`

The top-level `GO` job, including status, configuration fingerprint, timestamps, counters, and error summary.

#### `scan_source_runs`

One row per source per scan, with independent status, counts, timing, parser version, and error details.

#### `scan_progress_events`

Append-only progress records written before SSE delivery. Event IDs support browser reconnect and replay.

#### `scan_observations`

Links a scan, listing, and listing state. This records that an unchanged listing was still observed on a later scan without duplicating its content state.

#### `property_events`

Derived transitions such as first seen, price change, pending, sold, delisted, and relisted. Each event records its source evidence.

#### `sold_comparables`

Links a candidate property to a sold property or source sold record, with similarity inputs, distance, and retrieval metadata. Similarity is transparent and deterministic.

#### `profile_versions`

Profile hash, creation time, and criteria-extraction status. The plaintext profile remains in the configured YAML file.

#### `llm_runs`

One user-triggered analysis job, including provider, model, prompt version, force flag, status, counts, and timestamps.

#### `llm_evaluations`

One versioned property evaluation with:

- LLM run and property IDs.
- Profile hash.
- Material property-data hash.
- Provider and model.
- Prompt version.
- Structured result JSON.
- Human-readable evaluation.
- Missing information.
- Status and error summary.

#### `llm_digests`

One versioned, persisted cross-listing comparison linked to an LLM run. Its cache identity includes
the profile, current per-property evaluation inputs, provider, model, and digest prompt version. A
successful refresh becomes current while older and failed attempts remain available.

#### `places`

Google Place identity and policy-permitted cached fields, including place ID, coordinates, categories, retrieval time, and refresh metadata.

#### `property_place_walks`

Links a property and place with walking-route distance, duration, route status, retrieval time, and request fingerprint. An unavailable walking route is stored explicitly rather than converted to a straight-line estimate.

#### `nearby_analysis_runs`

Records each explicit selected-property nearby analysis, its Google service status, cache/refresh mode, counts, timestamps, and sanitized errors.

### 6.2 Idempotency

Idempotency is enforced at multiple layers:

- A source listing has a unique source/source-ID/episode key.
- Listing states use a normalized content hash.
- A scan has at most one observation per listing.
- Events use a deterministic event fingerprint.
- Active scan and LLM jobs are protected by transactional uniqueness or a database lease.
- LLM cache keys include profile, property data, provider, model, and prompt version.
- Nearby results use property coordinates, category set, API mode, and retrieval policy in their cache identity.

## 7. Source Acquisition

All adapters implement a common contract:

```text
scan_active(municipalities)
refresh_tracked(source_listing_ids)
fetch_details(source_listing)
fetch_sold_comparables(property)
```

Each adapter returns source DTOs. It never writes directly to canonical property tables.

Acquisition preference:

1. Accessible structured data.
2. Structured data embedded in a public page.
3. Ordinary HTTP parsing.
4. Playwright browser automation.

The system does not bypass CAPTCHA or explicit access blocks. Such a condition produces a visible source failure and leaves other sources running.

Each adapter provides:

- Its own rate limit and bounded concurrency.
- Timeouts and bounded retry with exponential backoff and jitter.
- A parser version.
- Sanitized diagnostic errors.
- Offline fixtures for parser tests.

Passwords, cookies, tokens, and API keys must not be written to diagnostic fixtures or logs.

When `logging.retain_source_payloads` is enabled (the default), every received HTTP
body is saved before status/block/layout handling under the private XDG data directory:

```text
source_payloads/<source>/<UTC-date>/<timestamp>_<status>_<content-hash>.body.gz
```

A sidecar JSON file stores the source, public request URL, status, retrieval time,
content type, and SHA-256 digest. Headers and cookies are deliberately excluded. Files
use mode `0600`, directories use `0700`, and no payload is stored in the repository.
Network failures that produce no HTTP response have no payload to retain.

### 7.1 Redfin access decision

Redfin exposes public town search and listing-detail pages. A standard browser user
agent currently returns server-rendered home cards and Schema.org JSON-LD without
requiring browser automation. The filtered town URL applies property type, maximum
price, and minimum bedroom/bathroom constraints; the adapter repeats those checks after normalization and
removes nearby-town recommendations.

The adapter is strictly user-triggered by `GO`, makes one request at a time, waits a
random 3–8 seconds between requests, and performs at most two attempts for transient
failures. It does not retry HTTP 403/429, CAPTCHA, robot pages, or explicit access
blocks. Those conditions and unrecognized layouts are visible source failures rather
than empty successful scans. Detail pages contribute explicit bedroom, bathroom,
property type, year-built, description, price, coordinates, availability, and source
update fields from JSON-LD. Missing tracked listings are refreshed and recorded as
`unavailable` on HTTP 404.

An HTTP 202 AWS WAF challenge is terminal for Redfin during the current scan. The
triggering listing first persists useful search-card fallback data, then Redfin stops
immediately so later requests are not wasted; other sources continue.

Redfin's current Terms of Use restrict automated extraction. The local user is
responsible for ensuring their use is authorized; the adapter can be disabled in local
configuration. The application does not bypass CAPTCHA, authentication, or access
controls.

Research references checked for M6.1:

- Redfin public town-search page: <https://www.redfin.com/city/36093/MA/Belmont>
- Redfin Terms of Use: <https://www.redfin.com/about/terms-of-use>

### 7.2 Zillow access decision

Zillow town searches encode property type, maximum price, and minimum bedroom and
bathroom constraints in the public page's `searchQueryState`. When the page is
accessible, the adapter reads embedded application JSON and Schema.org JSON-LD,
repeats all filters locally, and fetches listing details one at a time. It waits a
random 5–10 seconds between requests and performs at most two attempts for transient
network and server failures.

As checked on 2026-08-05, an ordinary HTTP request from the development environment
receives HTTP 403 with `x-px-blocked: 1` and a CAPTCHA page. The adapter detects this
as `ZillowAccessBlocked`, stops immediately, and reports an independent source
failure. It does not bypass CAPTCHA or reuse browser cookies. Redfin results already
persisted by the same scan remain available.

Zillow's current Terms of Use prohibit automated queries and scraping. The local user
is responsible for obtaining permission before enabling the adapter. It can be
disabled in local configuration.

Research references checked for M7.1:

- Zillow public Belmont search: <https://www.zillow.com/belmont-ma/>
- Zillow Terms of Use: <https://www.zillow.com/corporate/terms-of-use/>

### 7.3 Realtor access decision

Realtor public search pages currently return server-rendered property cards to an
ordinary HTTP client. Filtered URL path segments apply property type, maximum price,
and minimum bedroom/bathroom constraints. The adapter extracts the listing link,
price, beds, baths, area, type, and address from each card, then uses Schema.org
JSON-LD on detail pages for coordinates, updated price, area, description, image, and
availability. All configured constraints are checked again after normalization.

Requests run sequentially with a random 3–8 second interval, a 20-second timeout,
and at most two attempts for transient network or server errors. HTTP 403/429 and
human-verification pages stop only the Realtor source. Existing Redfin and Zillow
results remain available.

Realtor's current Terms of Use restrict scraping and automated collection without
written permission. The local user is responsible for permission and can disable the
adapter in local configuration. The application does not bypass access controls.

Research references checked for M8.1:

- Realtor public Belmont search: <https://www.realtor.com/realestateandhomes-search/Belmont_MA/type-single-family-home>
- Realtor Terms of Use: <https://www.realtor.com/terms-of-service/>

## 8. Normalization and Deduplication

Normalization produces consistent:

- Municipality names.
- Street suffixes and directionals.
- Unit numbers.
- ZIP codes.
- Numeric and monetary fields.
- Listing status vocabulary.

Matching levels:

1. **Exact:** normalized municipality, address, and unit match, or a matching parcel identifier with compatible unit evidence.
2. **High confidence:** nearly identical address and coordinates with compatible property facts.
3. **Ambiguous:** keep separate and mark as a possible duplicate.

Unit number is mandatory for auto-merging multi-unit properties. A false merge is worse than a visible duplicate.

All source facts remain available. The display resolver always uses Redfin first, Zillow second, and other sources afterward, while exposing conflicts and provenance to the UI. This rule can evolve without rewriting source states.

## 9. Scan Job Design

Pressing `GO` first saves the current form. The scan starts only if the save succeeds.
`Force GO` follows the same save and single-job rules but bypasses same-day detail
reuse. Newly retrieved values win within the same
source; missing new fields are filled from that source's prior state before the new
snapshot is fingerprinted and stored.

Production scans use only implemented live adapters. Fixture adapters are dependency-injected by tests and never run in the default application.

Flow:

1. Validate profile and search configuration.
2. Save and perform the daily backup if needed.
3. Atomically claim the single active scan slot.
4. Start independent source runs with limited concurrency.
5. Normalize each completed listing and commit it immediately.
6. Match or create properties and listing episodes.
7. Store/reuse listing states and add scan observations before fetching the next detail.
8. Derive state and price events.
9. Fetch and link sold comparables.
10. Produce deterministic initial-selection results and financial ranges.
11. Mark the job successful, partially successful, or failed.

One failed source yields `partial_success` when other sources succeed.
If a source fails after emitting at least one listing, the job is also `partial_success` and those listings remain visible. On a same-day retry, the adapter still refreshes town result pages for discovery and current list price, but reuses details only when year built, bedrooms, bathrooms, price, picture, lot size, living area, and status are all present. Missing, partial, and previously failed details resume normally. Progress reports successful, failed, in-progress, and skipped-complete-today counts separately.

### 9.1 History and sold comparables

Every ingested source transition derives append-only first-seen, price-change,
status-change, delisted, relisted, and sold events. The fingerprint includes the source
listing identity, transition values, and transition observation time. Re-observing an
unchanged state therefore creates no event, while a later repeated transition remains
representable. Startup backfills events from persisted scan observations.

Redfin, Zillow, and Realtor parsers normalize source-provided sold-history records into
the listing facts. Realtor also scans one bounded recently-sold results page per configured
town; these records are stored as comparable inventory and excluded from Matching homes
and later active-listing detail refreshes. Cross-source copies of the same property/date/price transaction are
deduplicated by display priority: Redfin, then Zillow, then Realtor. Comparables are
derived locally after each scan. Ranking uses explicit municipality, property type,
living-area, bedroom, recency, and distance evidence. Same-town records are used by
default; nearby towns are added and labeled only when fewer than three same-town
records exist. This data is historical evidence and is never presented as a prediction.

Job progress is persisted before being emitted over SSE. Reconnecting browsers can therefore reconstruct the current status. On server startup, abandoned `running` jobs become `interrupted`.

## 10. Financial Calculation

Financial calculation is deterministic and independent of the LLM.

For a property price `P`:

```text
down_payment = configured amount
```

or:

```text
down_payment = P * configured percentage
```

The loan principal is `max(P - down_payment, 0)`. Monthly principal and interest use the standard fixed-rate amortization formula for a 30-year term, evaluated at the configured low and high interest rates.

The calculator returns typed components rather than a single opaque total:

- Known values.
- Estimated low/high values.
- Missing values.
- Gross-income ratios.
- Gross pre-tax balances after housing and annual travel cost.

Unknown tax, HOA, or insurance is never converted to zero. Closing costs remain an upfront cost range and are not silently folded into monthly cost.

## 11. LLM Design

### 11.1 Provider Interface

All providers expose one internal operation:

```text
chat_json(system_prompt, user_prompt, response_schema)
```

Google AI Studio is the default. Ollama, OpenAI, and DeepSeek use the same OpenAI-compatible request shape where supported. Provider selection is explicit; an unknown or unavailable provider never falls back silently.

### 11.2 Criteria Extraction

The first call for a new profile hash converts freeform text into a structured interpretation:

- Must-have criteria.
- Evidence required for each criterion.
- Good-to-have criteria and relative weights.
- Ambiguities that cannot be safely interpreted.

This extraction runs only after the user presses `LLM Analysis`, not during `Save` or `GO`.

### 11.3 Property Evaluation

Each property is evaluated independently against the extracted criteria. The response schema includes:

- `meets`, `does_not_meet`, or `unknown` for every must-have.
- Evidence for every decision.
- Good-to-have score and explanation.
- Overall personalized evaluation.
- Missing information.

The backend validates every response. Invalid JSON may be retried once with a repair prompt; it is never accepted silently.

The LLM does not invent public facts or recalculate financial numbers. Deterministic application data remains authoritative.

### 11.4 Evaluation Cache

The LLM evaluates individual properties without assigning a rank or changing the user-selected
property order. Its property payload combines the UI's resolved facts and financial calculations
with each source's latest saved listing description, normalized detail facts, source timestamp, and
URL. Provider calls do not enable browsing; URLs are provenance rather than a fetch mechanism.

Cache identity:

```text
profile_hash
property_material_data_hash
provider
model
prompt_version
```

Forced reanalysis bypasses cache lookup but retains old evaluation history. Pressing the analysis
button is the explicit authorization for the configured provider call, so there is no second
confirmation dialog. Provider calls use bounded concurrency and handle rate limits without failing
the entire run.

### 11.5 Listing Digest

After the global analysis action, one additional structured LLM call compares the current analyzed
set using only saved per-property evaluations and deterministic application financials. The digest
contains an overview, up to five top choices, explicit must-have disqualifiers, tradeoffs, a
financial comparison, and shared unknowns. It is cached by its complete inputs and prompt version,
saved in SQLite, and reloaded after restart. Per-card forced analysis does not automatically call the
digest model; it instead makes an existing digest stale when its inputs materially change.

## 12. Google Maps and Walkability

### 12.1 Selected-property Map

The property table already supports selection for LLM analysis. The same selection state powers a `Map selected` action. The React map view:

- Loads Google Maps only after the user opens it.
- Adds one marker per selected property.
- Fits bounds to all selected markers.
- Opens a local property summary when a marker is selected.
- Can overlay cached nearby destinations for the active property.

No map request occurs during initial page load, profile save, `GO`, or LLM analysis.

### 12.2 Nearby Discovery and Walking Routes

For each explicitly selected property:

1. Use its known coordinates; geocode only when coordinates are missing and that service is configured.
2. Use Google Places Nearby Search for configured categories such as parks, groceries, shops, cafes, restaurants, and pharmacies.
3. Deduplicate candidates by Google Place ID.
4. Limit candidates per category before routing to control cost.
5. Use the Google Routes API in walking mode to compute actual walking distance and duration from the property to each candidate.
6. Store policy-permitted fields, derived walk results, retrieval time, and unavailable-route status.
7. Display actual minutes and distance in configurable walk-duration buckets.

Straight-line distance may be used to preselect routing candidates but is never presented as walking distance.

### 12.3 Cost, Cache, and Failure

- A confirmation shows selected-property count and estimated request scope before uncached calls.
- Fresh cache is reused unless the user selects refresh.
- Places and Routes calls use field masks, bounded concurrency, quotas, timeouts, and partial-failure handling.
- Failure for one property or category does not discard other results.
- Google billing, quota, credential, or policy errors remain visible and sanitized.
- Storage and refresh behavior follows current Google Maps Platform terms rather than assuming Google content can be retained forever.

### 12.4 Credentials and Privacy

Use separate keys:

- A browser key restricted to the Maps JavaScript API and approved local referrers.
- A backend key restricted to required Places, Routes, and optional Geocoding APIs.

Neither key is committed or logged. The backend key is never returned by an API. The UI warns that opening the map or running nearby analysis sends selected coordinates and request metadata to Google.

## 13. API Design

Initial API surface:

```text
GET    /api/health

GET    /api/config
PUT    /api/config

GET    /api/profile
PUT    /api/profile

POST   /api/scans
GET    /api/scans/status
GET    /api/scans/{scan_id}
GET    /api/scans/{scan_id}/events

GET    /api/properties
GET    /api/properties/{property_id}
GET    /api/properties/{property_id}/history
GET    /api/properties/{property_id}/comparables

POST   /api/maps/nearby-analyses
GET    /api/maps/nearby-analyses/{analysis_id}
GET    /api/maps/nearby-analyses/{analysis_id}/events
GET    /api/maps/properties/{property_id}/nearby
GET    /api/maps/browser-config

POST   /api/analyses
GET    /api/analyses/latest
GET    /api/analyses/{analysis_id}
GET    /api/analyses/{analysis_id}/events

PUT    /api/properties/{property_id}/manual-tags
PATCH  /api/properties/{property_id}/manual-facts

GET    /api/exports/properties.csv
```

`POST /api/scans` starts an incremental scan immediately, or accepts a force flag to bypass same-day detail reuse. `POST /api/analyses` accepts property IDs, provider, force, and whether the global action should generate a digest. Calling it is the explicit analysis action. `GET /api/analyses/latest` returns current per-property evaluations and the latest saved digest. API responses never include provider secrets.

`GET /api/maps/browser-config` may return the separately restricted browser Maps JavaScript key because Google Maps JavaScript executes in the browser. It must never return the backend Places/Routes key. `POST /api/maps/nearby-analyses` accepts selected property IDs, requested place categories, refresh mode, and explicit Google-call confirmation.

## 14. Frontend Design

The top control bar contains:

```text
[Save] [GO]  Last scan: ...
Provider: [Google v] [LLM Analysis] [ ] Force reanalysis
Last analysis: ...
```

Main interface areas:

- Profile, municipality, and finance editor.
- Sortable, filterable, selectable property results.
- An editable checkbox tag dropdown on each property plus separate top-level require-all and
  hide-any tag dropdowns; no automated Google or LLM classification of those tags.
- A crawl-only retrieval-status pill and a manual missing-field editor. Resolution order is crawled
  source data first, manual fallback second, and unknown last.
- Property detail with source conflicts and provenance.
- Financial breakdown.
- Must-have and good-to-have evaluation.
- Saved cross-listing digest with top choices and tradeoffs.
- Sold comparables.
- Price and status history.
- A selected-property Google Map and per-property nearby walking results.

Frontend state distinguishes:

- Saved versus dirty profile.
- Scan status versus LLM status.
- Fresh, stale, missing, failed, and forced evaluation states.
- Known versus estimated versus missing financial data.

The browser subscribes to SSE while a job is active and falls back to polling after a connection error. Refreshing the page reloads authoritative state from the API.

## 15. Security and Privacy

- Bind to `localhost` on port `7004` by default and never widen the host binding implicitly.
- Use same-origin API access; do not enable broad CORS.
- Escape all source and LLM text before rendering.
- Never log profile contents by default.
- Never log API keys, authorization headers, cookies, or source tokens, and never return backend or LLM keys through an API.
- Mark cloud providers clearly before transmitting private profile data.
- Treat Google Maps as another explicit cloud disclosure: selected coordinates and map activity leave the machine.
- Keep the backend Google Maps key server-side; expose only the separately restricted browser key required by the Maps JavaScript API.
- Use restrictive permissions for newly created config, profile, backup, database, and log files where practical.
- Keep source HTML and diagnostic payloads outside the repository with restrictive permissions; never retain response headers or cookies.
- Never commit personal information, private profile content, personal or network IP addresses, credentials, cookies, tokens, source payloads, or machine-specific absolute paths. Tracked examples use placeholders and `localhost` only.
- Keep runtime configuration, profiles, backups, databases, logs, browser state, HAR files, and traces outside the repository or covered by `.gitignore`.
- Run a privacy and secret scan over staged content before every commit.

No authentication is required because the server is localhost-only. Authentication becomes a separate requirement if the user later exposes it to a network.

## 16. Testing Strategy

### Unit Tests

- Profile validation and daily backup semantics.
- Atomic writes and date handling.
- Finance formulas and low/high ranges.
- Address and unit normalization.
- Deduplication confidence and false-merge prevention.
- Listing state hashes and event derivation.
- LLM cache identity and response validation.
- Nearby category filtering, Place ID deduplication, walk-duration buckets, and cache identity.

### Adapter Contract Tests

- Sanitized offline fixtures for each source.
- Parser behavior for missing and changed fields.
- Status normalization.
- Sold-record extraction.
- CAPTCHA/access-block detection.

Normal tests must not depend on live third-party websites.

### Integration Tests

- Profile save followed by `GO`.
- Single-active-job enforcement across concurrent requests.
- Partial source failure.
- Repeated scan idempotency.
- Server restart and interrupted-job recovery.
- Fake local LLM provider, cache reuse, and forced reanalysis.
- Fake Places and Routes providers, selected-property map configuration, partial failures, and forced refresh.
- React production build served by FastAPI.

## 17. Operational Behavior

- `GO` and LLM analysis are user-triggered; there are no automatic external calls.
- Google map loading and nearby walking analysis are also user-triggered; there are no automatic Google Maps calls.
- Logs use structured messages with secret redaction.
- Database and profile backup procedures are documented separately before release.
- Source parser failures remain visible and actionable rather than silently producing empty results.
- Database migrations are forward-only during normal operation; restoration uses a database backup.
