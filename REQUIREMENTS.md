# Smart House Hunting Requirements

## 1. Product Scope

Smart House Hunting is a local web application that helps one household find an owner-occupied home in Massachusetts.

This is the permanent product scope, not an MVP limitation:

- Single user and one shared household profile.
- Owner-occupied homes only. No rental or investment-property workflows.
- Massachusetts only.
- One or more target Massachusetts cities/towns are configured by the user.
- The web server listens on `127.0.0.1` only. Publishing it beyond localhost is outside this project's scope.
- The application is not a public service and does not need multi-user, account, role, or tenant support.
- The application uses existing public listing and sold-home information. It does not predict sale prices or estimate future property values.

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

## 4. User-Controlled Workflow

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
- The backend permits only one scan at a time, including requests from multiple browser tabs.
- Scan state and timestamps persist across application restarts.
- A recent completed scan causes a confirmation prompt rather than an unconditional hard block.
- Changing the configured towns permits an immediate new scan.

### 4.2 `LLM Analysis`: Personalized Analysis

The separate `LLM Analysis` button runs personalized analysis on the latest initial-selection results. It does not fetch listing data.

The LLM stage:

- Evaluates each must-have as `meets`, `does not meet`, or `unknown`.
- Never treats missing public information as a failed requirement.
- Scores and explains good-to-have compatibility.
- Produces a personalized ranking.
- Produces a personalized overall evaluation for each property.
- Identifies the evidence and missing data behind its conclusions.

The user may select a subset of properties for analysis. If nothing is selected, the button analyzes all current initial-selection results.

By default, cached analysis is reused when both the profile and relevant property data are unchanged. Analysis is required for:

- A new property.
- A material change to property data.
- A changed household profile.
- A previous failed LLM request.
- A user-requested forced reanalysis.

The page displays the last LLM analysis time separately from the last scan time.

### 4.3 Forced Reanalysis

A `Force reanalysis` checkbox is displayed beside the LLM button.

- When unchecked, only new, stale, changed, or previously failed analyses run.
- When checked, cached results are ignored for the currently selected properties, or for all current results if none are selected.
- Forced reanalysis does not fetch listing data.
- Before using a cloud provider, the application shows the number of properties and asks for confirmation.
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

The browser interface allows the user to hide or collapse unimportant information.

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

## 9. Database and History

All scanned properties and source records are stored locally. The data model must distinguish:

- A physical property.
- A source-specific listing or listing episode.
- A timestamped listing snapshot.
- A status or price event.
- A versioned LLM evaluation.

The application retains properties after they disappear from active search results. It tracks at least:

- First discovery.
- Price increase or decrease.
- Active, contingent, pending, sold, delisted, and relisted transitions when available.
- Sale date and sale price.
- Source-specific changes and conflicts.

Repeated scans must be idempotent: they must not create duplicate properties, listing episodes, snapshots, or status events for unchanged source data.
