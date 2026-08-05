# Smart House Hunting Milestones

Milestones are ordered by dependency. Each milestone must satisfy its acceptance criteria before work proceeds to features that depend on it. Source adapters are deliberately separated because they are the highest-risk components.

## M0: Project Foundation

### Tasks

- [ ] M0.1 Create the Python package and `pyproject.toml`.
- [ ] M0.2 Create the FastAPI application with a `127.0.0.1` development command.
- [ ] M0.3 Create the React, TypeScript, and Vite frontend.
- [ ] M0.4 Configure the Vite development API proxy.
- [ ] M0.5 Serve the production React build from FastAPI.
- [ ] M0.6 Add formatting, linting, and test commands for Python and TypeScript.
- [ ] M0.7 Add `/api/health` and a minimal application shell.

### Acceptance Criteria

- One documented command starts the development backend and frontend.
- One documented production command serves the API and compiled frontend from FastAPI.
- `/api/health` and the browser shell work on `127.0.0.1`.
- Baseline Python and frontend tests pass.

## M1: Configuration and Profile Storage

### Tasks

- [ ] M1.1 Define and validate the application configuration schema.
- [ ] M1.2 Load `~/.config/smart_house_hunting/config.yaml` with clear missing/invalid errors.
- [ ] M1.3 Define the household profile schema and canonical YAML representation.
- [ ] M1.4 Implement profile read and populate API.
- [ ] M1.5 Implement atomic profile save.
- [ ] M1.6 Implement one pre-save backup per local calendar day.
- [ ] M1.7 Implement restrictive permissions for newly created private files.
- [ ] M1.8 Build the React profile, town, income, travel, and down-payment form.
- [ ] M1.9 Implement amount/percentage synchronization with last-edited mode.
- [ ] M1.10 Show saved, dirty, saving, and error states.

### Acceptance Criteria

- Existing YAML populates the web form exactly.
- Saving overwrites the configured file atomically.
- Multiple saves in one day create exactly one backup of the pre-first-save state.
- A first-ever save does not create an empty backup.
- Reloading the page reproduces the saved values and down-payment mode.

## M2: SQLite Schema and Persistence

### Tasks

- [ ] M2.1 Configure SQLite WAL mode and foreign-key enforcement.
- [ ] M2.2 Add SQLAlchemy models for properties, aliases, and listings.
- [ ] M2.3 Add models for listing states, scans, source runs, and observations.
- [ ] M2.4 Add models for events and sold comparables.
- [ ] M2.5 Add models for profile versions, LLM runs, and evaluations.
- [ ] M2.6 Create the initial Alembic migration.
- [ ] M2.7 Add repository operations with uniqueness and idempotency constraints.
- [ ] M2.8 Add database initialization and migration startup checks.

### Acceptance Criteria

- A new installation creates one valid local SQLite database.
- Foreign keys and uniqueness constraints reject invalid duplicate relationships.
- Reusing a listing-state content hash does not duplicate content.
- A later scan can observe an unchanged state without losing scan-presence history.
- Migration tests can upgrade a fresh database to the current schema.

## M3: Financial Engine

### Tasks

- [ ] M3.1 Define typed monetary and range models using decimal arithmetic.
- [ ] M3.2 Implement fixed-amount and percentage down payments.
- [ ] M3.3 Implement the 30-year fixed-rate amortization calculation.
- [ ] M3.4 Add tax, insurance, HOA, maintenance, and closing-cost components.
- [ ] M3.5 Preserve unknown values separately from zero.
- [ ] M3.6 Calculate current-income and minimum-income gross ratios and balances.
- [ ] M3.7 Build the financial breakdown component.
- [ ] M3.8 Add boundary tests for zero, excessive down payment, missing values, and rate ranges.

### Acceptance Criteria

- Calculations reproduce independently checked amortization examples.
- Low and high ranges remain internally consistent.
- Unknown inputs are visible and never silently treated as zero.
- Outputs are labeled as gross/pre-tax and do not claim to be disposable income or risk ratings.

## M4: Job Manager and `GO` Infrastructure

### Tasks

- [ ] M4.1 Define the source-adapter contract and normalized DTOs.
- [ ] M4.2 Create a deterministic fixture source adapter.
- [ ] M4.3 Implement persisted scan jobs and per-source runs.
- [ ] M4.4 Enforce one queued/running scan across browser tabs.
- [ ] M4.5 Implement recent-scan confirmation behavior.
- [ ] M4.6 Implement interrupted-job recovery on server startup.
- [ ] M4.7 Implement persisted progress events and SSE streaming.
- [ ] M4.8 Wire `GO` to save the profile before starting a scan.
- [ ] M4.9 Show last attempt, last success, running state, and per-source status beside `GO`.
- [ ] M4.10 Add SSE reconnect and polling fallback.

### Acceptance Criteria

- Fixture data completes the full `GO` flow without an LLM call.
- Simultaneous `GO` requests produce only one active job.
- Refreshing the page does not lose job status.
- Restarting during a job marks it interrupted.
- A partial source failure remains visible while successful source data is retained.

## M5: Normalization, Deduplication, and Results

### Tasks

- [ ] M5.1 Normalize Massachusetts municipality names and addresses.
- [ ] M5.2 Preserve and normalize condo/unit identifiers.
- [ ] M5.3 Implement exact parcel and address matching.
- [ ] M5.4 Implement high-confidence coordinate/fact matching.
- [ ] M5.5 Keep ambiguous matches separate and expose possible duplicates.
- [ ] M5.6 Implement source fact provenance and conflict resolution.
- [ ] M5.7 Upsert listings, states, and observations idempotently.
- [ ] M5.8 Implement property list and detail APIs.
- [ ] M5.9 Build selectable, sortable, and filterable React results.
- [ ] M5.10 Build source links, provenance, conflicts, and collapsible details.

### Acceptance Criteria

- The same detached home from multiple fixture sources appears once.
- Different units at the same street address never auto-merge.
- Ambiguous cases remain reversible and inspectable.
- Repeating the same fixture scan does not duplicate properties, listings, states, or observations.
- Every displayed source-derived value can be traced to its source.

## M6: Redfin Adapter

### Tasks

- [ ] M6.1 Document the accessible Redfin acquisition path and failure modes.
- [ ] M6.2 Implement configured-town active listing discovery.
- [ ] M6.3 Implement listing detail extraction.
- [ ] M6.4 Implement tracked-listing refresh and state mapping.
- [ ] M6.5 Implement sanitized offline parser fixtures.
- [ ] M6.6 Add rate limiting, timeout, bounded retry, and block detection.
- [ ] M6.7 Integrate Redfin into `GO` and per-source status reporting.

### Acceptance Criteria

- Redfin data passes the shared source contract.
- Parser tests do not access the live website.
- A layout change or access block produces a visible source error, not an empty successful scan.
- Repeated extraction is idempotent.

## M7: Zillow Adapter

### Tasks

- [ ] M7.1 Document the accessible Zillow acquisition path and failure modes.
- [ ] M7.2 Implement configured-town active listing discovery.
- [ ] M7.3 Implement listing detail extraction.
- [ ] M7.4 Implement tracked-listing refresh and state mapping.
- [ ] M7.5 Implement sanitized offline parser fixtures.
- [ ] M7.6 Add rate limiting, timeout, bounded retry, and block detection.
- [ ] M7.7 Integrate Zillow into cross-source deduplication and status reporting.

### Acceptance Criteria

- Zillow passes the same adapter contract as Redfin.
- Cross-source fixture properties deduplicate without losing Zillow provenance.
- Zillow failure does not prevent Redfin data from completing.

## M8: Realtor Adapter

### Tasks

- [ ] M8.1 Document the accessible Realtor acquisition path and failure modes.
- [ ] M8.2 Implement configured-town active listing discovery.
- [ ] M8.3 Implement listing detail extraction.
- [ ] M8.4 Implement tracked-listing refresh and state mapping.
- [ ] M8.5 Implement sanitized offline parser fixtures.
- [ ] M8.6 Add rate limiting, timeout, bounded retry, and block detection.
- [ ] M8.7 Integrate Realtor into cross-source deduplication and status reporting.

### Acceptance Criteria

- Realtor passes the shared adapter contract.
- Three-source fixture records resolve to one property where evidence is exact.
- A Realtor failure produces a partial scan rather than a failed global scan.

## M9: Listing History and Sold Comparables

### Tasks

- [ ] M9.1 Derive first-seen, price-change, status-change, delisted, relisted, and sold events.
- [ ] M9.2 Assign deterministic event fingerprints.
- [ ] M9.3 Implement active tracked-listing refresh across later scans.
- [ ] M9.4 Implement source-specific sold-record extraction.
- [ ] M9.5 Implement transparent comparable similarity rules.
- [ ] M9.6 Default to same-town comparables and label nearby-town expansion.
- [ ] M9.7 Build property history and comparable APIs.
- [ ] M9.8 Build price/status history and sold-comparable UI.

### Acceptance Criteria

- Repeated unchanged scans create no duplicate events.
- Price and status transitions retain source evidence.
- Sold comparables display sale/list prices, differences, links, retrieval time, and missing fields.
- The product never labels comparable output as a sale-price prediction.

## M10: LLM Provider Layer

### Tasks

- [ ] M10.1 Define the OpenAI-compatible provider interface.
- [ ] M10.2 Implement Google AI Studio as the default provider.
- [ ] M10.3 Implement local Ollama.
- [ ] M10.4 Implement OpenAI.
- [ ] M10.5 Implement DeepSeek.
- [ ] M10.6 Implement secret-safe configuration and masked settings responses.
- [ ] M10.7 Add timeout, bounded concurrency, retry, and rate-limit handling.
- [ ] M10.8 Add a fake provider for deterministic integration tests.
- [ ] M10.9 Verify that keys and authorization headers never enter logs or API responses.

### Acceptance Criteria

- The selected provider and model are explicit and persisted.
- Google is used when the configured default is unchanged.
- Unknown providers fail visibly without fallback.
- Ollama works without sending profile data to a cloud endpoint.
- Provider failures do not alter listing data.

## M11: Personalized Analysis and Ranking

### Tasks

- [ ] M11.1 Version the criteria-extraction and property-evaluation prompts.
- [ ] M11.2 Implement freeform profile criteria extraction after explicit LLM action.
- [ ] M11.3 Define and validate structured must-have and good-to-have schemas.
- [ ] M11.4 Implement per-property evaluation with evidence and missing information.
- [ ] M11.5 Implement one bounded JSON-repair retry.
- [ ] M11.6 Implement material property-data hashes and LLM cache keys.
- [ ] M11.7 Implement deterministic ranking from structured results.
- [ ] M11.8 Implement selected-property analysis and all-result fallback.
- [ ] M11.9 Implement cloud property-count confirmation.
- [ ] M11.10 Implement forced reanalysis while retaining old history.
- [ ] M11.11 Reset the force checkbox after each attempted run.
- [ ] M11.12 Build fresh, stale, missing, running, and failed analysis states in React.

### Acceptance Criteria

- `Save` and `GO` never call an LLM.
- Every must-have result is `meets`, `does_not_meet`, or `unknown` with evidence.
- Missing listing information is never converted to a failed requirement.
- Unchanged inputs reuse cache unless force is selected.
- Forced analysis creates a new current result and preserves the prior result.
- The last analysis time remains separate from the last scan time.

## M12: Export, Hardening, and Local Release

### Tasks

- [ ] M12.1 Implement property and history CSV exports.
- [ ] M12.2 Add structured logging and secret/profile redaction.
- [ ] M12.3 Add database backup and restore documentation.
- [ ] M12.4 Back up the database before non-trivial migrations.
- [ ] M12.5 Add production configuration validation and actionable startup errors.
- [ ] M12.6 Test restrictive file permissions.
- [ ] M12.7 Test full production React build and localhost serving.
- [ ] M12.8 Add end-to-end tests covering profile, scan, results, and LLM analysis.
- [ ] M12.9 Document installation, Playwright browser setup, configuration, startup, and troubleshooting.
- [ ] M12.10 Perform a privacy review of logs, errors, fixtures, exports, and cloud confirmations.

### Acceptance Criteria

- A clean local installation can be configured and started from documentation.
- The complete workflow functions through `127.0.0.1` with one Python production process.
- Database restore and profile backup recovery are documented and tested.
- No test, log, API response, fixture, or export unintentionally contains API keys.
- Source failures and LLM failures are visible without corrupting existing data.

## Delivery Rule

A milestone is complete only when its implementation, automated tests, and acceptance criteria are all complete. Live-source success alone is not sufficient; every source parser must have sanitized offline fixtures so later source changes can be diagnosed without guessing.
