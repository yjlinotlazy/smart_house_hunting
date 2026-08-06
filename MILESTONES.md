# Smart House Hunting Milestones

Milestones are ordered by dependency. Each milestone must satisfy its acceptance criteria before work proceeds to features that depend on it. Source adapters are deliberately separated because they are the highest-risk components.

## M0: Project Foundation

### Tasks

- [x] M0.1 Create the Python package and `pyproject.toml`.
- [x] M0.2 Create the FastAPI application with a `localhost:7004` default development command.
- [x] M0.3 Create the React, TypeScript, and Vite frontend.
- [x] M0.4 Configure the Vite development API proxy.
- [x] M0.5 Serve the production React build from FastAPI.
- [x] M0.6 Add formatting, linting, and test commands for Python and TypeScript.
- [x] M0.7 Add `/api/health` and a minimal application shell.
- [x] M0.8 Add repository ignore rules for local configuration, profiles, databases, logs, browser state, HAR files, traces, and secrets.

### Acceptance Criteria

- One documented command starts the development backend and frontend.
- One documented production command serves the API and compiled frontend from FastAPI.
- `/api/health` and the browser shell work on `localhost:7004` by default.
- Baseline Python and frontend tests pass.

## M1: Configuration and Profile Storage

### Tasks

- [x] M1.1 Define and validate the application configuration schema.
- [x] M1.2 Load `~/.config/smart_house_hunting/config.yaml` with clear missing/invalid errors.
- [x] M1.3 Define the household profile schema and canonical YAML representation.
- [x] M1.4 Implement profile read and populate API.
- [x] M1.5 Implement atomic profile save.
- [x] M1.6 Implement one pre-save backup per local calendar day.
- [x] M1.7 Implement restrictive permissions for newly created private files.
- [x] M1.8 Build the React profile, town, income, travel, and down-payment form.
- [x] M1.9 Implement the two down-payment inputs and persist the last-edited authoritative mode; calculate the derived value per property in M3.
- [x] M1.10 Show saved, dirty, saving, and error states.
- [x] M1.11 Add a separate dual-mode form/YAML local config editor linked from the home page.
- [x] M1.12 Validate config edits before atomic replacement and preserve invalid-file safety.

### Acceptance Criteria

- Existing YAML populates the web form exactly.
- Saving overwrites the configured file atomically.
- Multiple saves in one day create exactly one backup of the pre-first-save state.
- A first-ever save does not create an empty backup.
- Reloading the page reproduces the saved values and down-payment mode.
- The config page can overwrite valid YAML, while invalid YAML leaves the existing file unchanged.

## M2: SQLite Schema and Persistence

### Tasks

- [x] M2.1 Configure SQLite WAL mode and foreign-key enforcement.
- [x] M2.2 Add SQLAlchemy models for properties, aliases, and listings.
- [x] M2.3 Add models for listing states, scans, source runs, and observations.
- [x] M2.4 Add models for events and sold comparables.
- [x] M2.5 Add models for profile versions, LLM runs, and evaluations.
- [x] M2.6 Create the initial Alembic migration.
- [x] M2.7 Add repository operations with uniqueness and idempotency constraints.
- [x] M2.8 Add database initialization and migration startup checks.

### Acceptance Criteria

- A new installation creates one valid local SQLite database.
- Foreign keys and uniqueness constraints reject invalid duplicate relationships.
- Reusing a listing-state content hash does not duplicate content.
- A later scan can observe an unchanged state without losing scan-presence history.
- Migration tests can upgrade a fresh database to the current schema.

## M3: Financial Engine

### Tasks

- [x] M3.1 Define typed monetary and range models using decimal arithmetic.
- [x] M3.2 Implement fixed-amount and percentage down payments.
- [x] M3.2a Calculate and display the derived amount or percentage for each property.
- [x] M3.3 Implement the 30-year fixed-rate amortization calculation.
- [x] M3.4 Add tax, insurance, HOA, maintenance, and closing-cost components.
- [x] M3.5 Preserve unknown values separately from zero.
- [x] M3.6 Calculate current-income and minimum-income gross ratios and balances.
- [x] M3.7 Build the financial breakdown component.
- [x] M3.8 Add boundary tests for zero, excessive down payment, missing values, and rate ranges.

### Acceptance Criteria

- Calculations reproduce independently checked amortization examples.
- Low and high ranges remain internally consistent.
- Unknown inputs are visible and never silently treated as zero.
- Outputs are labeled as gross/pre-tax and do not claim to be disposable income or risk ratings.

## M4: Job Manager and `GO` Infrastructure

### Tasks

- [x] M4.1 Define the source-adapter contract and normalized DTOs.
- [x] M4.2 Create a deterministic fixture source adapter.
- [x] M4.3 Implement persisted scan jobs and per-source runs.
- [x] M4.4 Enforce one queued/running scan across browser tabs.
- [x] M4.5 Allow user-controlled repeat scans without a recent-scan warning.
- [x] M4.6 Implement interrupted-job recovery on server startup.
- [x] M4.7 Implement persisted progress events and SSE streaming.
- [x] M4.8 Wire `GO` to save the profile before starting a scan.
- [x] M4.9 Show last attempt, last success, running state, and per-source status beside `GO`.
- [x] M4.10 Add SSE reconnect and polling fallback.

### Acceptance Criteria

- Fixture data completes the full `GO` flow without an LLM call.
- Simultaneous `GO` requests produce only one active job.
- Refreshing the page does not lose job status.
- Restarting during a job marks it interrupted.
- A partial source failure remains visible while successful source data is retained.

## M5: Normalization, Deduplication, and Results

### Tasks

- [x] M5.1 Normalize Massachusetts municipality names and addresses.
- [x] M5.2 Preserve and normalize condo/unit identifiers.
- [x] M5.3 Implement exact parcel and address matching.
- [x] M5.4 Implement high-confidence coordinate/fact matching.
- [x] M5.5 Keep ambiguous matches separate and expose possible duplicates.
- [x] M5.6 Implement source fact provenance and conflict resolution.
- [x] M5.7 Upsert listings, states, and observations idempotently.
- [x] M5.8 Implement property list and detail APIs.
- [x] M5.9 Build selectable, sortable, and filterable React results.
- [x] M5.10 Build source links, provenance, conflicts, and collapsible details.

### Acceptance Criteria

- The same detached home from multiple fixture sources appears once.
- Different units at the same street address never auto-merge.
- Ambiguous cases remain reversible and inspectable.
- Repeating the same fixture scan does not duplicate properties, listings, states, or observations.
- Every displayed source-derived value can be traced to its source.

## M6: Redfin Adapter

### Tasks

- [x] M6.1 Document the accessible Redfin acquisition path and failure modes.
- [x] M6.2 Implement configured-town active listing discovery with property-type and minimum bedroom/bathroom website filters.
- [x] M6.3 Implement listing detail extraction.
- [x] M6.4 Implement tracked-listing refresh and state mapping.
- [x] M6.5 Implement sanitized offline parser fixtures.
- [x] M6.6 Add rate limiting, timeout, bounded retry, and block detection.
- [x] M6.7 Integrate Redfin into `GO` and per-source status reporting.

### Acceptance Criteria

- Redfin data passes the shared source contract.
- Parser tests do not access the live website.
- A layout change or access block produces a visible source error, not an empty successful scan.
- Repeated extraction is idempotent.

## M7: Zillow Adapter

### Tasks

- [x] M7.1 Document the accessible Zillow acquisition path and failure modes.
- [x] M7.2 Implement configured-town active listing discovery with property-type and minimum bedroom/bathroom website filters.
- [x] M7.3 Implement listing detail extraction.
- [x] M7.4 Implement tracked-listing refresh and state mapping.
- [x] M7.5 Implement sanitized offline parser fixtures.
- [x] M7.6 Add rate limiting, timeout, bounded retry, and block detection.
- [x] M7.7 Integrate Zillow into cross-source deduplication and status reporting.

### Acceptance Criteria

- Zillow passes the same adapter contract as Redfin.
- Cross-source fixture properties deduplicate without losing Zillow provenance.
- Zillow failure does not prevent Redfin data from completing.

## M8: Realtor Adapter

### Tasks

- [x] M8.1 Document the accessible Realtor acquisition path and failure modes.
- [x] M8.2 Implement configured-town active listing discovery with property-type and minimum bedroom/bathroom website filters.
- [x] M8.3 Implement listing detail extraction.
- [x] M8.4 Implement tracked-listing refresh and state mapping.
- [x] M8.5 Implement sanitized offline parser fixtures.
- [x] M8.6 Add rate limiting, timeout, bounded retry, and block detection.
- [x] M8.7 Integrate Realtor into cross-source deduplication and status reporting.

### Acceptance Criteria

- Realtor passes the shared adapter contract.
- Three-source fixture records resolve to one property where evidence is exact.
- A Realtor failure produces a partial scan rather than a failed global scan.

## M9: Listing History and Sold Comparables

### Tasks

- [x] M9.1 Derive first-seen, price-change, status-change, delisted, relisted, and sold events.
- [x] M9.2 Assign deterministic event fingerprints.
- [x] M9.3 Implement active tracked-listing refresh across later scans.
- [x] M9.4 Implement source-specific sold-record extraction.
- [x] M9.5 Implement transparent comparable similarity rules.
- [x] M9.6 Default to same-town comparables and label nearby-town expansion.
- [x] M9.7 Build property history and comparable APIs.
- [x] M9.8 Build price/status history and sold-comparable UI.

### Acceptance Criteria

- Repeated unchanged scans create no duplicate events.
- Price and status transitions retain source evidence.
- Sold comparables display sale/list prices, differences, links, retrieval time, and missing fields.
- The product never labels comparable output as a sale-price prediction.

## M10: Google Maps and Walkability

### Tasks

- [x] M10.1 Add private Google Maps configuration with separate browser and backend key environment variables.
- [x] M10.2 Add a migration for places, property walking routes, and nearby-analysis runs.
- [x] M10.3 Implement a Google Places Nearby Search client with field masks, category limits, and Place ID deduplication.
- [x] M10.4 Implement a Google Routes walking-mode client for actual route duration and distance.
- [x] M10.5 Implement cache freshness, selected-property scope, explicit confirmation, and forced refresh.
- [x] M10.6 Implement partial-failure handling for properties, categories, places, and routes.
- [x] M10.7 Add safe browser map configuration that exposes only the restricted Maps JavaScript key.
- [x] M10.8 Build reusable property selection and the `Map selected` action.
- [x] M10.9 Build the multi-property map with markers, bounds fitting, local property summaries, and nearby overlays.
- [x] M10.10 Build per-property nearby results with categories, walking minutes, distance, retrieval time, and Google links.
- [x] M10.11 Add cloud privacy disclosure and show selected property/request scope before uncached Google calls.
- [x] M10.12 Add fake Places/Routes providers and offline tests; normal tests must not call Google.
- [x] M10.13 Document key restrictions, enabled APIs, billing, quotas, cache policy, and troubleshooting.

### Acceptance Criteria

- Opening the map shows exactly the selected properties and does not trigger LLM or listing scans.
- No Google Maps request occurs until the user explicitly opens the map or requests nearby analysis.
- Nearby results use actual walking routes when available and never label straight-line distance as walking distance.
- Fresh cached results avoid duplicate paid calls; forced refresh is explicit.
- One failed property, category, or route does not discard successful results.
- The backend Google key never reaches the browser, logs, database, fixtures, or Git.
- The UI states that selected coordinates and map activity are sent to Google.
- Stored Google-derived content and refresh behavior comply with current Google Maps Platform policy.

## M11: LLM Provider Layer

### Tasks

- [x] M11.1 Define the OpenAI-compatible provider interface.
- [x] M11.2 Implement Google AI Studio as the default provider.
- [x] M11.3 Implement local Ollama.
- [x] M11.4 Implement OpenAI.
- [x] M11.5 Implement DeepSeek.
- [x] M11.6 Implement secret-safe configuration and masked settings responses.
- [x] M11.7 Add timeout, bounded concurrency, retry, and rate-limit handling.
- [x] M11.8 Add a fake provider for deterministic integration tests.
- [x] M11.9 Verify that keys and authorization headers never enter logs or API responses.

### Acceptance Criteria

- The selected provider and model are explicit and persisted.
- Google is used when the configured default is unchanged.
- Unknown providers fail visibly without fallback.
- Ollama works without sending profile data to a cloud endpoint.
- Provider failures do not alter listing data.

## M12: Personalized Analysis

### Tasks

- [x] M12.1 Version the criteria-extraction and property-evaluation prompts.
- [x] M12.2 Implement freeform profile criteria extraction after explicit LLM action.
- [x] M12.3 Define and validate structured must-have and good-to-have schemas.
- [x] M12.4 Implement per-property evaluation with evidence and missing information.
- [x] M12.5 Implement one bounded JSON-repair retry.
- [x] M12.6 Implement material property-data hashes and LLM cache keys.
- [x] M12.7 Keep structured evaluations independent without ranking or reordering properties.
- [x] M12.8 Implement selected-property analysis and all-result fallback.
- [x] M12.9 Treat the explicit LLM analysis action as provider-call authorization without a redundant confirmation dialog.
- [x] M12.10 Implement forced reanalysis while retaining old history.
- [x] M12.11 Reset the force checkbox after each attempted run.
- [x] M12.12 Build fresh, stale, missing, running, and failed analysis states in React.
- [x] M12.13 Generate, cache, persist, reload, and display a structured cross-listing digest after
  global analysis without adding a digest call to per-property analysis.

### Acceptance Criteria

- `Save` and `GO` never call an LLM.
- Every must-have result is `meets`, `does_not_meet`, or `unknown` with evidence.
- Missing listing information is never converted to a failed requirement.
- Unchanged inputs reuse cache unless force is selected.
- Forced analysis creates a new current result and preserves the prior result.
- The last analysis time remains separate from the last scan time.

## M13: Export, Hardening, and Local Release

### Tasks

- [x] M13.1 Implement property and history CSV exports.
- [x] M13.2 Add structured logging and secret/profile redaction.
- [x] M13.3 Add database backup and restore documentation.
- [x] M13.4 Back up the database before non-trivial migrations.
- [x] M13.5 Add production configuration validation and actionable startup errors.
- [x] M13.6 Test restrictive file permissions.
- [x] M13.7 Test full production React build and localhost serving.
- [x] M13.8 Add end-to-end tests covering profile, scan, results, maps, nearby analysis, and LLM analysis.
- [x] M13.9 Document installation, Playwright browser setup, configuration, startup, and troubleshooting.
- [x] M13.10 Perform a privacy review of logs, errors, fixtures, exports, maps, and cloud disclosures.
- [x] M13.11 Add and run a staged-file privacy/secret check that rejects personal data, IP addresses, credentials, and machine-specific paths.
- [x] M13.12 Add editable persistent manual property tags and require/hide dropdown filtering.
- [x] M13.13 Add crawl-status pills and persistent manual fallback facts with crawl precedence.

### Acceptance Criteria

- A clean local installation can be configured and started from documentation.
- The complete workflow functions through `localhost:7004` by default with one Python production process.
- Database restore and profile backup recovery are documented and tested.
- No test, log, API response, fixture, or export unintentionally contains API keys.
- Git-tracked content contains no personal information, personal or network IP addresses, credentials, runtime data, or machine-specific absolute paths.
- Source failures and LLM failures are visible without corrupting existing data.

## Delivery Rule

A milestone is complete only when its implementation, automated tests, and acceptance criteria are all complete. Live-source success alone is not sufficient; every source parser must have sanitized offline fixtures so later source changes can be diagnosed without guessing.
