# Smart House Hunting

Local, personalized house hunting for an owner-occupied home in Massachusetts.

## Prerequisites

- Python 3.12 or newer
- Node.js and npm
- A supported desktop browser for using the web interface

## Clean installation

From a fresh checkout:

```text
make setup
mkdir -p "${XDG_CONFIG_HOME:-$HOME/.config}/smart_house_hunting"
cp config.example.yaml "${XDG_CONFIG_HOME:-$HOME/.config}/smart_house_hunting/config.yaml"
```

`make setup` creates `.venv`, installs the Python package and development tools, and installs the
locked frontend dependencies. Edit the private `config.yaml` before starting the application:

- Replace `profile_file` with an absolute private path, or a path relative to the configuration
  directory.
- Replace the example municipalities, maximum price, and financial assumptions.
- Set `finance.default_down_payment_percent`; it seeds a new profile but never overwrites a saved
  profile choice.
- Set the model names for any LLM providers you intend to use.
- Disable listing sources you are not authorized to query.
- Leave Maps disabled unless Google Maps credentials and billing are configured.

The configuration file must remain outside Git. Startup creates the SQLite database; the first
profile save creates the profile, and later operations create state directories and backups as
needed. Private files and directories are created with restrictive permissions.

### Playwright browser setup

No Playwright browser installation is currently required. The Redfin, Zillow, and Realtor adapters
use ordinary HTTP requests and do not bypass CAPTCHA or access controls. Playwright is reserved for
a future adapter that legitimately requires browser rendering; it is intentionally absent from the
current dependency set. If such an adapter is added and declares a pinned Playwright dependency,
install its Chromium runtime after `make setup` with:

```text
.venv/bin/python -m playwright install chromium
```

On Linux, `playwright install --with-deps chromium` also installs system packages and may require
administrator approval. Do not install Playwright as a workaround for a source access block.

## Setup

```text
make setup
```

Running setup again refreshes the local Python environment and frontend dependencies. It does not
overwrite private configuration or runtime data.

## Development

```text
make dev
```

The API runs on `localhost:7004`; Vite runs on `localhost:5173` and proxies `/api` to the API.

## Production-style Local Run

```text
make run
```

This builds React and serves both the frontend and API from FastAPI on `localhost:7004`.
On startup, the application creates or migrates its private local SQLite database automatically.

Open `http://localhost:7004`. Stop either development or production mode with `Ctrl-C`. The server
is intentionally local-only; exposing it to a network is unsupported and would require a separate
authentication and security design.

## Configuration and credentials

The default private configuration path is
`${XDG_CONFIG_HOME:-$HOME/.config}/smart_house_hunting/config.yaml`. After the first successful
startup, **Local config** provides a form and raw-YAML editor. Invalid changes are rejected without
replacing the working file.

Secrets are supplied through the environment variable named by each `api_key_env` setting. Export
only the values needed for the action you intend to run, in the same terminal that starts the app.
For example:

```text
export GOOGLE_API_KEY="<private-value>"
make run
```

The corresponding YAML contains `api_key_env: GOOGLE_API_KEY`, never the private value. LLM keys
are needed only for LLM analysis. Google Maps keys are needed only when Maps is enabled and the user
explicitly opens a map or requests nearby analysis. Ollama may use a locally defined dummy variable
when its server does not require authentication.

## Maps and walkability

Maps are opt-in. Open **Local config**, enable Maps, and keep the key itself in an environment
variable—not YAML. `GOOGLE_MAPS_API_KEY` is supported as a single prototype/demo key. A production
setup should instead use separate `GOOGLE_MAPS_BROWSER_API_KEY` and
`GOOGLE_MAPS_BACKEND_API_KEY` values so the browser key can be restricted to Maps JavaScript and
the backend key to Places API (New) and Routes API.

The map loads only after **Map selected** is pressed. Nearby analysis asks again before sending the
selected coordinates and five category searches to Google. Successful nearby and walking-route
results are cached locally for the configured period (14 days by default); **Force refresh** bypasses
the cache. A failed category or walking route is shown without discarding other results.

The [Google Maps demo key](https://developers.google.com/maps/demo-key) is intended for prototypes.
For a separately billed key, configure API/application restrictions, budgets, and quotas in Google
Cloud. An empty map usually means Maps JavaScript is disabled or the browser restriction does not
match the local origin. Missing nearby results usually means Places API (New) or Routes API is
disabled for the backend key.

## LLM analysis

LLM analysis is separate from **GO**. Select properties (or leave all unselected) and press the
analysis button; that explicit action sends the saved profile and selected property data to the
configured provider. Google AI Studio is the default; Ollama, OpenAI, and
DeepSeek use the same OpenAI-compatible interface. Provider and model settings and key environment
variable names live in local YAML; secret values never do. Ollama can run locally without sending
the profile to a cloud provider.

Unchanged profile/property inputs reuse the last successful result. **Force reanalysis** retains the
old database row and creates a new current result. Each property card's **LLM analysis** button
always performs a forced reanalysis of that property without another prompt. LLM output is advisory;
unknown listing facts stay `unknown` rather than becoming failed requirements.

The global **Analyze** action also creates a saved listing digest for the analyzed set. It compares
top choices, explicit must-have disqualifiers, tradeoffs, financial ranges, and shared unknowns. An
unchanged digest is reused unless **Force all** is selected. Per-property analysis does not incur a
second digest call, and a failed digest refresh does not delete the last successful digest.

Property analysis includes each source URL plus the latest saved listing description and normalized
detail facts. The model does not browse the URL; it evaluates the content collected during scans.

Each property card has a persistent checkbox tag dropdown, initially offering **双黄线**,
**Corner lot**, and **剪刀煞**; new tags can be added there. Above Matching homes, one dropdown
requires all checked tags and another hides homes containing any checked tag. Tags are never
inferred by Google Maps or the LLM.

Each card also shows **Retrieved** or **Partially retrieved** from crawl completeness. For missing
fields, **Manual input** stores local fallback values. A future crawl replaces a fallback when it
returns that field; otherwise the manual value remains. Manual entry does not change the crawl
status pill.

## Export and recovery

CSV downloads are available at `/api/exports/properties.csv` and `/api/exports/history.csv` while the
app is running. Exports contain addresses and source links, so treat them as private local files.

Before a schema upgrade, the app writes a permission-restricted SQLite snapshot beside the live
database under `backups/`. To restore: stop the server, make an additional copy of the current
database, replace it with the chosen snapshot, and restart. Profile recovery uses the dated YAML
files in the profile's `backups/` directory. Never replace either file while the server is running.

Before committing, stage the intended files and run `make privacy-check`; it rejects likely private
network addresses, credentials, and machine-specific home paths.

## Checks

```text
make test
make lint
make format-check
make verify
```

Product requirements, implementation design, and delivery tasks are documented in
`REQUIREMENTS.md`, `DESIGN.md`, and `MILESTONES.md`.

## Troubleshooting

- **Startup says the configuration does not exist:** copy `config.example.yaml` to the default
  private configuration path shown above. Do not put the private copy in this repository.
- **Startup says the configuration is invalid:** compare every field with `config.example.yaml`.
  YAML indentation matters, `search.maximum_price` must be positive, at least one property type is
  required, and the `google` LLM provider entry must exist even when it is not selected.
- **The frontend is missing:** use `make dev`, or run `make build` before starting the Python entry
  point directly. `make run` performs the build automatically.
- **Port 7004 or 5173 is already in use:** stop the older application/Vite process. The documented
  commands currently use these fixed local ports; changing only `server.port` does not change the
  launch command.
- **A listing source reports blocked, CAPTCHA, WAF, or layout errors:** this is an expected visible
  source failure, not a successful empty scan. Do not try to bypass it. Disable that source or retry
  later; completed data from other sources remains stored.
- **A same-day scan skips details:** ordinary `GO` reuses complete details fetched that day. Use
  **Force GO** only when every discoverable detail must be downloaded again.
- **LLM analysis reports a missing key or connection error:** verify the selected provider, model,
  base URL, and named environment variable. For Ollama, confirm its local server is running. A failed
  LLM run does not alter listing data.
- **Maps are empty or nearby analysis fails:** verify Maps is enabled, the browser key permits the
  local origin, the backend key permits Places API (New) and Routes API, and billing/quotas are
  active. The backend key must never be exposed to the browser.
- **Local dependencies or generated assets appear stale:** run `make setup`, then `make clean` and
  `make verify`. `make clean` removes only repository build/test caches, not private configuration,
  profiles, databases, or backups.
- **A schema migration or profile edit needs recovery:** stop the server before restoring. Follow
  the snapshot and dated-profile-backup procedure in **Export and recovery** above.
