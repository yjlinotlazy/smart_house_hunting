# Smart House Hunting Requirements

## 1. Product Scope

Smart House Hunting is a local web application that helps one household find an owner-occupied home or a rental home in Massachusetts.

This is the permanent product scope, not an MVP limitation:

- Single user and one shared household profile.
- The application has two completely independent modes: Buy and Rent. Buy is the default mode.
- Buy mode covers owner-occupied homes. Rent mode covers residential rental homes. The modes do not mix listings, filters, statuses, scan results, or UI state.
- Investment-property workflows are outside this project's scope.
- Massachusetts only.
- One or more target Massachusetts cities/towns are configured by the user.
- The web server listens on `localhost`, port `7004`, by default. Publishing it beyond localhost is outside this project's scope.
- The application is not a public service and does not need multi-user, account, role, or tenant support.
- The application uses existing public listing and sold-home information. It does not predict sale prices or estimate future property values.
- Git-tracked files must never contain personal information, private profile data, personal or network IP addresses, credentials, cookies, tokens, or machine-specific absolute paths. Documentation and examples use placeholders and `localhost` only.

## 2. Configuration and Private Profile

The application configuration is stored at:

```text
~/.config/smart_house_hunting/config.yaml
```

The configuration contains operational settings, including:

- The path of the private household profile YAML file.
- One or more target Massachusetts cities/towns.
- LLM provider settings.
- Financial-model assumptions.
- The default down-payment percentage used when no household profile has been saved yet.
- One or more included property types. The default local selection is `single_family` only.
- Rental preferences, including desired move-in date and lease term, are stored in the same household profile/configuration but are used only by Rent mode.

The home page links to a separate local configuration page. It defaults to a
user-friendly sectioned form and can switch to a complete raw YAML editor. Fields
with a fixed multi-value set, including property types and listing sources, use
checklists. Saving either mode validates the entire configuration and atomically
overwrites it only after validation succeeds. The other mode is refreshed after a
successful save. Actual credentials must remain in environment variables; the YAML
stores environment-variable names, not secret values. Invalid edits must leave the
existing file unchanged.

The household profile is a single YAML file at the configured path. It contains three freeform text fields:

- Household and family situation.
- Must-have requirements.
- Good-to-have requirements.

It also contains the user's private financial inputs. When the web page opens, it reads the existing profile file and populates all corresponding form fields. The user may modify the fields and overwrite the file by saving.

### 2.1 Daily Profile Backup

Saving the profile follows these rules:

- Opening or reading the profile does not create a backup.
- On the first save of each local calendar day, the current profile file is copied to a date-stamped backup before it is overwritten.
- Further saves on the same day overwrite the profile without creating additional backups.
- The application checks the date stamp of the existing daily backup rather than relying only on the profile file modification time.
- A profile being created for the first time has no old file to back up.
- Profile writes must use an atomic replacement so an interrupted save does not leave a partially written file.
- Backups retain the profile state immediately before that day's first modification.

Example:

```text
house_profile.yaml
backups/
  house_profile.2026-08-05.yaml
  house_profile.2026-08-06.yaml
```

## 3. Search Area and Sources

The user may configure multiple Massachusetts cities/towns. Candidate listings must be inside one of those configured municipalities.

Candidate listings must also match one of `search.included_property_types`. Supported values are `single_family`, `condo`, `townhouse`, `multi_family`, `land`, `mobile`, and `other`. Changing this list permits an immediate scan because it changes the scan fingerprint.

The search configuration also contains nonnegative minimum bedroom and bathroom counts. Half-unit values are allowed. Source adapters must apply these minimums to website searches when supported, and normalized results are filtered again locally.

The search configuration contains a positive maximum purchase price. It is applied to source website filters, the scan fingerprint, normalized results, and the default Matching homes filter.

The initial supported listing sources are:

- Redfin
- Zillow
- Realtor

Each source is independent. Failure of one source must not discard successful results from the other sources or fail the entire scan.

### 3.1 Cross-source Deduplication

The application must recognize the same property across multiple sources and show it as one property with multiple source records and links.

Deduplication should use, when available:

- Normalized full street address.
- Standard Massachusetts municipality.
- Unit number for condos and other multi-unit properties.
- Geographic coordinates.
- Parcel or assessor identifier.
- Property characteristics as supporting evidence.

Source-specific listing IDs are not sufficient for cross-source identity. Conflicting source values must not be silently discarded; source values and provenance should be retained, with an explicit rule for choosing the primary displayed value.

Living area and lot size are separate source facts. Lot size is normalized to square
feet for storage and comparison; the UI also shows acres when useful. Unknown lot
size remains `-` and is never inferred from living area.

Candidate cards display the source lead image and year built when available. Missing
images use a stable placeholder, and missing construction year remains `-`.

For conflicting displayed facts, source priority is Redfin first, Zillow second, then all other sources. Lower-priority values remain visible as provenance and conflicts.

## 4. User-Controlled Workflow

The home page has two independent tabs:

- Buy is the default tab and contains the purchase workflow.
- Rent contains only rental listings and rental filters. Switching tabs never mixes buy and rental results, filters, statuses, or scan state.

Both tabs use the configured Massachusetts municipalities, property types, and enabled listing sources unless a mode-specific rule says otherwise.

The application separates public-data scanning from LLM analysis. Saving the profile alone does not scan sources or call an LLM.

### 4.1 `GO`: Scan and Initial Selection

`GO` performs the non-LLM stage:

1. Save the current form contents, applying the daily backup rule.
2. Fetch current listing and sold-home information from the configured sources.
3. Deduplicate properties across sources.
4. Update prices, listing states, sold information, and history.
5. Perform deterministic initial selection using configured towns and available structured facts.
6. Calculate rough financial ranges.
7. Present the candidate listings.

Because must-have and good-to-have requirements are freeform, `GO` must not claim to understand or enforce them. Personalized hard-condition decisions happen during the LLM stage.

The page displays the last scan time beside `GO`, including:

- Last scan attempt.
- Last successful scan.
- Current running state.
- Success or failure for each source.

Duplicate scans are prevented as follows:

- `GO` is disabled while a scan is running.
- Live scan progress separately displays detail successes, failures, in-progress work, and listings skipped because their required data was already complete earlier that local day.
- The backend permits only one scan at a time, including requests from multiple browser tabs.
- Scan state and timestamps persist across application restarts.
- Each completed listing is committed immediately. A later source failure or server restart must not discard earlier results from the same scan.
- Retrying a scan on the same local calendar day refreshes each town listing page but reuses only complete listing details. A listing is complete only when it has year built, bedroom count, bathroom count, price, at least one picture, lot size, living area, and status. A listing missing any required field is partial and its detail page is fetched again by ordinary `GO`.
- `Force GO` bypasses same-day detail reuse. It downloads every discoverable listing detail again from every enabled source.
- Within one source, a newly retrieved non-missing value supersedes the prior value. If the new response omits a field that the prior state knew, the new state retains that prior field. Historical states remain intact.
- Repeated `GO` actions never require a recent-scan confirmation; the user controls when to run another incremental scan.
- Changing the configured towns permits an immediate new scan.

### 4.2 `LLM Analysis`: Personalized Analysis

The separate `LLM Analysis` button runs personalized analysis on the latest initial-selection results. It does not fetch listing data.

The LLM stage:

- Evaluates each must-have as `meets`, `does not meet`, or `unknown`.
- Never treats missing public information as a failed requirement.
- Scores and explains good-to-have compatibility.
- Produces a personalized overall evaluation for each property.
- Uses the latest saved description and normalized detail facts from every source, with source URLs
  retained as provenance; it does not assume the LLM can browse those URLs.
- Produces and saves a cross-listing digest after the global action, covering top choices, explicit
  must-have disqualifiers, tradeoffs, financial comparison, and shared unknowns.
- Identifies the evidence and missing data behind its conclusions.

The user may select a subset of properties for analysis. If nothing is selected, the button analyzes all current initial-selection results.

By default, cached analysis is reused when both the profile and relevant property data are unchanged. Analysis is required for:

- A new property.
- A material change to property data.
- A changed household profile.
- A previous failed LLM request.
- A user-requested forced reanalysis.

The page displays the last LLM analysis time separately from the last scan time.

LLM analysis is available only in Buy mode. Rent mode does not call an LLM and does not display LLM analysis controls or results.

### 4.3 Rent Workflow

Rent mode uses Redfin, Zillow, and Realtor and stores rental results independently from Buy mode.

Rent mode has these independent search inputs:

- Maximum monthly rent.
- Minimum bedrooms.
- Minimum bathrooms.
- Desired move-in date.
- Desired lease term.

Pet requirements are not part of the rental workflow.

Rental cards retain source links, provenance, manual tags, manual fields, selection, and history behavior, but only within Rent mode. They show monthly rent and HOA separately, plus their sum as the monthly housing cost. HOA uses the same normalized monthly HOA field as Buy mode.

Rental statuses are limited in the visible UI: `active` listings remain visible, while every other status is retained in the database and hidden from the Rent tab.

Rent mode displays monthly rental cost only. It does not calculate mortgage, down payment, property tax, or purchase affordability.

### 4.4 Forced Reanalysis

A `Force reanalysis` checkbox is displayed beside the LLM button.

- When unchecked, only new, stale, changed, or previously failed analyses run.
- When checked, cached results are ignored for the currently selected properties, or for all current results if none are selected.
- Forced reanalysis does not fetch listing data.
- The per-property `LLM analysis` action always forces a new analysis for that property without a
  confirmation dialog; the global action uses its separate `Force all` checkbox.
- Per-property analysis does not regenerate the cross-listing digest. A global analysis reuses an
  unchanged saved digest unless `Force all` is selected, and failed refreshes retain the prior digest.
- Pressing `LLM Analysis` is the explicit authorization to send the saved profile and selected
  property data to the configured provider; no redundant confirmation dialog is shown.
- The newest result becomes the current result, while older analysis remains in history.
- The checkbox resets to unchecked after the operation to prevent accidental repeated calls.

## 5. LLM Providers and Privacy

The LLM API design follows the provider-switching approach used by `algo_monster`: providers use an OpenAI-compatible chat-completions interface and have configurable base URL, API key, and model.

Supported providers are:

- Google AI Studio, the default provider.
- Local Ollama.
- OpenAI.
- DeepSeek.

The selected default provider is persisted in configuration and used by LLM analysis until the user changes it. Model names are configurable and are not hard-coded into business logic.

Provider requirements:

- API keys remain on the backend and are never sent to the browser.
- API keys must never appear in logs, errors, database records, or saved analysis.
- An unknown provider is a configuration error and must not silently fall back to another provider.
- Provider failure is recorded visibly for the affected analysis and must not damage listing data.
- Cloud providers receive the household profile and relevant property information needed for analysis.
- Selecting local Ollama keeps LLM request data on the local machine.

Each saved analysis records the property, profile version, provider, model, prompt version, analysis time, structured result, text evaluation, missing inputs, and request status. It never records the API key.

## 6. Financial Inputs and Results

All income inputs are annual gross, pre-tax amounts:

- Current annual gross income.
- Minimum expected future annual gross income.
- Current annual travel spending.

The mortgage term is fixed at 30 years.

The down payment is presented as two inputs:

- Fixed dollar amount.
- Percentage of the current property's listing price.

Entering either value automatically calculates the other. The last edited input is the authoritative mode:

- In `amount` mode, the planned dollar amount remains fixed and its percentage varies by property price.
- In `percent` mode, the percentage remains fixed and its dollar amount varies by property price.

A fixed amount represents the planned amount to contribute, not merely an upper limit.

The application produces rough numerical ranges and does not assign a financial risk level. For each property it displays, when available:

- Listing price.
- Down-payment amount and percentage.
- Estimated loan amount.
- Estimated closing-cost range.
- 30-year principal-and-interest monthly range using the configured interest-rate range.
- Monthly property tax.
- Monthly insurance range.
- Monthly HOA.
- Monthly maintenance estimate range.
- Known monthly housing-cost subtotal.
- Estimated total monthly housing-cost range.
- Housing cost as a percentage of current gross income.
- Housing cost as a percentage of minimum future gross income.
- Current gross income remaining after housing and travel costs.
- Minimum future gross income remaining after housing and travel costs.

The last two values must be labeled as gross, pre-tax balances, not disposable income. They do not imply that taxes, debt, food, childcare, healthcare, or other living costs have been deducted.

Missing property tax, HOA, insurance, or other data must be shown as unknown and must not be silently treated as zero. Known subtotals must remain distinguishable from totals containing estimates.

## 7. Property Output

Each property page or result includes:

- Public basic property and listing information.
- All available source links.
- Must-have results after LLM analysis.
- Good-to-have compatibility and explanation.
- Rough financial numbers and ranges.
- Gross-income impact rather than a system-generated risk label.
- Personalized overall evaluation.
- Data confidence, missing information, and source provenance where relevant.
- Similar sold properties and their source links.
- Nearby parks, stores, and other useful destinations with walking distance and duration when analyzed.
- Persistent user-defined labels, initially offering `双黄线`, `Corner lot`, and `剪刀煞`.
- A `Retrieved` or `Partially retrieved` card indicator based only on fields returned by crawls.
- Manual fallback entry for fields missing from crawls.

The browser interface allows the user to add labels from each property dropdown. Two top-level
checkbox dropdowns require all selected labels or hide properties containing any selected label.
These labels are human observations; Google Maps and the LLM do not set them automatically.

Manual property values persist locally but have lower precedence than every crawled source. A later
crawl value replaces the manual value for display and analysis; if the later crawl still omits that
field, the manual fallback remains active. Manual values do not turn a partially retrieved crawl
indicator into a retrieved one.

## 8. Comparable Sold Properties

Comparable records come from existing sold-home information. The application does not use them to predict a sale price.

Each sold comparable should include, when available:

- Address and source link.
- Sale date and sale price.
- Original listing price.
- Final listing price.
- Difference between sale price and original listing price.
- Difference between sale price and final listing price.
- Property type, bedrooms, bathrooms, and living area.
- Distance from the candidate property.
- Explanation of why it is considered similar.
- Data source, retrieval time, and missing fields.

Similarity uses transparent rules such as municipality, recency, property type, size, bedrooms, and price range. Comparables should default to the same municipality; the application may expand to nearby municipalities when there are too few results, but must label that expansion clearly.

## 9. Google Maps and Walkable Destinations

The user can select any subset of current candidate properties and open them together in an interactive Google Map.

Map behavior:

- Only properties selected by the user are placed on the map.
- Each property is shown as a distinct marker.
- Selecting a marker shows the property summary and a link back to its local detail page.
- The map automatically fits the selected markers.
- Mapping is an explicit user action and is not loaded during `GO` or LLM analysis.

For a selected property, the user can explicitly request research into useful places that can actually be reached on foot, including at least:

- Parks and public green spaces.
- Grocery stores and supermarkets.
- General stores and shopping destinations.
- Cafes and restaurants.
- Pharmacies and other useful daily services when available.

Nearby-place analysis must not use straight-line radius alone. It uses nearby-place discovery followed by walking-route distance and duration where Google provides a route. Results display:

- Place name and category.
- Actual walking duration and distance when available.
- A Google Maps link.
- Retrieval time.
- Missing route or place information.

The application should show useful time buckets such as short, moderate, and longer walks, while retaining the actual duration so the user can make the final judgment. It does not claim that every suggested route is safe, accessible, or pleasant; Google route results and public data are evidence, not a guarantee.

Cost and privacy controls:

- Nearby-place and walking-route calls run only after an explicit user action.
- The UI shows how many selected properties will be analyzed before paid Google calls are made.
- Cached fresh results are reused by default; a separate refresh action bypasses the cache.
- The UI clearly states that selected property coordinates and map activity are sent to Google.
- Missing credentials, quota exhaustion, billing errors, or Google service failures are visible and do not affect locally stored property data.
- Google-derived data is stored and refreshed only as permitted by the applicable Google Maps Platform policies.

Google Maps credentials remain in local private configuration or environment variables and are never committed. Browser and backend credentials are separate: the browser Maps JavaScript key is restricted for local web use and the backend Places/Routes key is never sent to the browser.

## 10. Database and History

All scanned properties and source records are stored locally. The data model must distinguish:

- A physical property.
- A source-specific listing or listing episode.
- A timestamped listing snapshot.
- A status or price event.
- A versioned LLM evaluation.

Every received listing-source HTTP response body is saved locally before parsing,
including successful, blocked, unavailable, and unrecognized-layout responses. Bodies
are stored losslessly compressed with retrieval metadata so parsing can be replayed
without another download. Response headers, cookies, and tokens are not retained.
Payload files remain outside the repository and use restrictive permissions.

The application retains properties after they disappear from active search results. It tracks at least:

- First discovery.
- Price increase or decrease.
- Active, contingent, pending, sold, delisted, and relisted transitions when available.
- Sale date and sale price.
- Source-specific changes and conflicts.

Repeated scans must be idempotent: they must not create duplicate properties, listing episodes, snapshots, or status events for unchanged source data.
