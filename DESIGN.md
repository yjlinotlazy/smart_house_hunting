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

The server binds only to `127.0.0.1`. FastAPI serves both `/api/*` and the compiled React assets.

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
    - Lexington
    - Arlington
  recent_scan_confirmation_minutes: 30

finance:
  mortgage_years: 30
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
      base_url: http://127.0.0.1:11434/v1
      api_key: dummy
      model: "..."
```

Rates above are examples, not product-prescribed defaults. They must be reviewed when the implementation reaches financial configuration.

Provider-specific environment variables may override secrets and endpoint settings. API keys are backend-only, masked in settings responses, and never logged.

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
- Creation and update timestamps.

#### `property_aliases`

Normalized addresses, source identities, and other match keys that resolve to a property. This makes deduplication explainable and allows a bad match to be corrected without destroying source data.

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

### 6.2 Idempotency

Idempotency is enforced at multiple layers:

- A source listing has a unique source/source-ID/episode key.
- Listing states use a normalized content hash.
- A scan has at most one observation per listing.
- Events use a deterministic event fingerprint.
- Active scan and LLM jobs are protected by transactional uniqueness or a database lease.
- LLM cache keys include profile, property data, provider, model, and prompt version.

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

## 8. Normalization and Deduplication

Normalization produces consistent:

- Municipality names.
- Street suffixes and directionals.
- Unit numbers.
- ZIP codes.
- Numeric and monetary fields.
- Listing status vocabulary.

Matching levels:

1. **Exact:** normalized municipality, address, and unit match, or a matching parcel identifier.
2. **High confidence:** nearly identical address and coordinates with compatible property facts.
3. **Ambiguous:** keep separate and mark as a possible duplicate.

Unit number is mandatory for auto-merging multi-unit properties. A false merge is worse than a visible duplicate.

All source facts remain available. A display resolver chooses a current value using freshness, completeness, and an explicit source-priority rule while exposing conflicts and provenance to the UI.

## 9. Scan Job Design

Pressing `GO` first saves the current form. The scan starts only if the save succeeds.

Flow:

1. Validate profile and search configuration.
2. Save and perform the daily backup if needed.
3. Atomically claim the single active scan slot.
4. If the previous completed scan is recent, require an explicit confirmation flag.
5. Start independent source runs with limited concurrency.
6. Normalize returned records.
7. Match or create properties and listing episodes.
8. Store/reuse listing states and add scan observations.
9. Derive state and price events.
10. Fetch and link sold comparables.
11. Produce deterministic initial-selection results and financial ranges.
12. Mark the job successful, partially successful, or failed.

One failed source yields `partial_success` when other sources succeed.

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

### 11.4 Ranking and Cache

The LLM evaluates individual properties. The application creates the final list order from must-have results and good-to-have scores so adding another property does not require re-ranking every unchanged property.

Cache identity:

```text
profile_hash
property_material_data_hash
provider
model
prompt_version
```

Forced reanalysis bypasses cache lookup but retains old evaluation history. Cloud analysis requires confirmation with the property count. Provider calls use bounded concurrency and handle rate limits without failing the entire run.

## 12. API Design

Initial API surface:

```text
GET    /api/health

GET    /api/config
PUT    /api/config

GET    /api/profile
PUT    /api/profile

POST   /api/scans
GET    /api/scans/latest
GET    /api/scans/{scan_id}
GET    /api/scans/{scan_id}/events

GET    /api/properties
GET    /api/properties/{property_id}
GET    /api/properties/{property_id}/history
GET    /api/properties/{property_id}/comparables

POST   /api/analyses
GET    /api/analyses/latest
GET    /api/analyses/{analysis_id}
GET    /api/analyses/{analysis_id}/events

GET    /api/exports/properties.csv
```

`POST /api/scans` accepts an explicit recent-scan confirmation flag. `POST /api/analyses` accepts property IDs, provider, force flag, and cloud confirmation. API responses never include provider secrets.

## 13. Frontend Design

The top control bar contains:

```text
[Save] [GO]  Last scan: ...
Provider: [Google v] [LLM Analysis] [ ] Force reanalysis
Last analysis: ...
```

Main interface areas:

- Profile, municipality, and finance editor.
- Sortable, filterable, selectable property results.
- Property detail with source conflicts and provenance.
- Financial breakdown.
- Must-have and good-to-have evaluation.
- Sold comparables.
- Price and status history.

Frontend state distinguishes:

- Saved versus dirty profile.
- Scan status versus LLM status.
- Fresh, stale, missing, failed, and forced evaluation states.
- Known versus estimated versus missing financial data.

The browser subscribes to SSE while a job is active and falls back to polling after a connection error. Refreshing the page reloads authoritative state from the API.

## 14. Security and Privacy

- Bind only to `127.0.0.1`.
- Use same-origin API access; do not enable broad CORS.
- Escape all source and LLM text before rendering.
- Never log profile contents by default.
- Never log or return API keys, authorization headers, cookies, or source tokens.
- Mark cloud providers clearly before transmitting private profile data.
- Use restrictive permissions for newly created config, profile, backup, database, and log files where practical.
- Keep source HTML and diagnostic payload retention opt-in or sanitized.

No authentication is required because the server is localhost-only. Authentication becomes a separate requirement if the user later exposes it to a network.

## 15. Testing Strategy

### Unit Tests

- Profile validation and daily backup semantics.
- Atomic writes and date handling.
- Finance formulas and low/high ranges.
- Address and unit normalization.
- Deduplication confidence and false-merge prevention.
- Listing state hashes and event derivation.
- LLM cache identity and response validation.

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
- React production build served by FastAPI.

## 16. Operational Behavior

- `GO` and LLM analysis are user-triggered; there are no automatic external calls.
- Logs use structured messages with secret redaction.
- Database and profile backup procedures are documented separately before release.
- Source parser failures remain visible and actionable rather than silently producing empty results.
- Database migrations are forward-only during normal operation; restoration uses a database backup.

