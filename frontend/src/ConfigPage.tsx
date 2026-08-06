import { FormEvent, ReactNode, useEffect, useMemo, useState } from "react";

import {
  HouseholdProfile,
  PrivateConfig,
  loadProfile,
  loadSettings,
  loadSettingsYaml,
  saveSettings,
  saveProfile,
  saveSettingsYaml,
} from "./api/client";

const BUILT_IN_LLM_TEMPLATE = `You evaluate one home against the household profile and structured criteria.

Household profile:
{household_profile}

Structured criteria:
{criteria}

Property data:
{property_data}

Output schema:
{output_schema}`;

const EMPTY_PROFILE: HouseholdProfile = {
  family: "",
  must_have: "",
  good_to_have: "",
  finance: {
    current_annual_gross_income: "0",
    minimum_future_annual_gross_income: "0",
    annual_travel_spending: "0",
    down_payment: { mode: "percent", value: "20" },
  },
};

const PROPERTY_TYPES = [
  ["single_family", "Single family"],
  ["condo", "Condo"],
  ["townhouse", "Townhouse"],
  ["multi_family", "Multi-family"],
  ["land", "Land"],
  ["mobile", "Mobile home"],
  ["other", "Other"],
] as const;

type PageState =
  | { status: "loading" }
  | { status: "ready"; initialConfig: string; initialYaml: string }
  | { status: "error"; message: string };

function parseMunicipalities(value: string): string[] {
  return Array.from(
    new Map(
      value
        .split(",")
        .map((town) => town.trim())
        .filter(Boolean)
        .map((town) => [town.toLocaleLowerCase(), town]),
    ).values(),
  );
}

function rateToPercent(value: string): string {
  return String(Number(value) * 100);
}

function percentToRate(value: string): string {
  if (!value) return "";
  return String(Number(value) / 100);
}

export function ConfigPage() {
  const [page, setPage] = useState<PageState>({ status: "loading" });
  const [mode, setMode] = useState<"form" | "yaml">("form");
  const [config, setConfig] = useState<PrivateConfig | null>(null);
  const [profile, setProfile] = useState<HouseholdProfile | null>(null);
  const [yamlContent, setYamlContent] = useState("");
  const [municipalitiesText, setMunicipalitiesText] = useState("");
  const [saveState, setSaveState] = useState<
    "idle" | "saving" | "saved" | "error"
  >("idle");
  const [message, setMessage] = useState("");

  useEffect(() => {
    let active = true;
    Promise.all([loadSettings(), loadSettingsYaml(), loadProfile()])
      .then(([loadedConfig, loadedYaml, loadedProfile]) => {
        if (!active) return;
        setConfig(loadedConfig);
        setProfile(loadedProfile.profile ?? EMPTY_PROFILE);
        setYamlContent(loadedYaml.content);
        setMunicipalitiesText(loadedConfig.search.municipalities.join(", "));
        setPage({
          status: "ready",
          initialConfig: JSON.stringify({
            config: loadedConfig,
            profile: loadedProfile.profile ?? EMPTY_PROFILE,
          }),
          initialYaml: loadedYaml.content,
        });
      })
      .catch((error: unknown) => {
        if (!active) return;
        setPage({
          status: "error",
          message:
            error instanceof Error ? error.message : "Unable to load config",
        });
      });
    return () => {
      active = false;
    };
  }, []);

  const dirty = useMemo(() => {
    if (page.status !== "ready" || !config || !profile) return false;
    return mode === "form"
      ? JSON.stringify({ config, profile }) !== page.initialConfig
      : yamlContent !== page.initialYaml;
  }, [config, mode, page, yamlContent]);

  useEffect(() => {
    function warnBeforeLeaving(event: BeforeUnloadEvent) {
      if (!dirty) return;
      event.preventDefault();
    }
    window.addEventListener("beforeunload", warnBeforeLeaving);
    return () => window.removeEventListener("beforeunload", warnBeforeLeaving);
  }, [dirty]);

  function edit(next: PrivateConfig) {
    setConfig(next);
    setSaveState("idle");
    setMessage("");
  }

  async function handleSave(event: FormEvent) {
    event.preventDefault();
    if (!config || !profile) return;
    setSaveState("saving");
    setMessage("");
    try {
      if (mode === "form") {
        const [saved] = await Promise.all([
          saveSettings(config),
          saveProfile(profile),
        ]);
        const raw = await loadSettingsYaml();
        setConfig(saved);
        setYamlContent(raw.content);
        setMunicipalitiesText(saved.search.municipalities.join(", "));
        setPage({
          status: "ready",
          initialConfig: JSON.stringify({ config: saved, profile }),
          initialYaml: raw.content,
        });
      } else {
        const raw = await saveSettingsYaml(yamlContent);
        const saved = await loadSettings();
        setConfig(saved);
        setYamlContent(raw.content);
        setMunicipalitiesText(saved.search.municipalities.join(", "));
        setPage({
          status: "ready",
          initialConfig: JSON.stringify(saved),
          initialYaml: raw.content,
        });
      }
      setSaveState("saved");
      setMessage("Config validated and saved locally.");
    } catch (error) {
      setSaveState("error");
      setMessage(error instanceof Error ? error.message : "Save failed");
    }
  }

  if (page.status === "loading") {
    return <main className="centered-state">Loading local config…</main>;
  }
  if (page.status === "error" || !config) {
    return (
      <main className="centered-state error-panel">
        <h1>Configuration unavailable</h1>
        <p>{page.status === "error" ? page.message : "Config is missing"}</p>
        <a className="text-link" href="/">
          Back to home
        </a>
      </main>
    );
  }

  return (
    <main className="workspace config-workspace">
      <header className="topbar">
        <div>
          <a className="text-link" href="/">
            ← Home
          </a>
          <p className="eyebrow config-eyebrow">Local application settings</p>
          <h1>Config</h1>
        </div>
        <div className="save-cluster">
          <div className="view-toggle" aria-label="Config editor mode">
            <button
              type="button"
              className={mode === "form" ? "active" : ""}
              disabled={dirty && mode !== "form"}
              onClick={() => setMode("form")}
            >
              Form
            </button>
            <button
              type="button"
              className={mode === "yaml" ? "active" : ""}
              disabled={dirty && mode !== "yaml"}
              onClick={() => setMode("yaml")}
            >
              YAML
            </button>
          </div>
          <span className={`save-state save-state-${saveState}`} role="status">
            {saveState === "saving" && "Validating and saving…"}
            {(saveState === "saved" || saveState === "error") && message}
            {saveState === "idle" && (dirty ? "Unsaved changes" : "Saved")}
          </span>
          <button
            type="submit"
            form="config-form"
            disabled={!dirty || saveState === "saving"}
          >
            Save config
          </button>
        </div>
      </header>

      <form id="config-form" className="config-form" onSubmit={handleSave}>
        {mode === "yaml" ? (
          <YamlEditor
            content={yamlContent}
            onChange={(value) => {
              setYamlContent(value);
              setSaveState("idle");
              setMessage("");
            }}
          />
        ) : (
          <ConfigForm
            config={config}
            profile={profile}
            onProfileChange={setProfile}
            municipalitiesText={municipalitiesText}
            onMunicipalitiesChange={(value) => {
              setMunicipalitiesText(value);
              edit({
                ...config,
                search: {
                  ...config.search,
                  municipalities: parseMunicipalities(value),
                },
              });
            }}
            onChange={edit}
          />
        )}
        <p
          className={saveState === "error" ? "calculation-error" : "field-note"}
          aria-live="polite"
        >
          {message ||
            "Changes apply to later requests; server host and port require restart."}
        </p>
      </form>
    </main>
  );
}

function YamlEditor({
  content,
  onChange,
}: {
  content: string;
  onChange: (value: string) => void;
}) {
  return (
    <section className="form-section">
      <SectionHeading
        label="YAML"
        title="Raw configuration"
        description="Advanced mode. The full schema is still validated before saving."
      />
      <label>
        Config contents
        <textarea
          className="config-editor"
          value={content}
          onChange={(event) => onChange(event.target.value)}
          spellCheck={false}
        />
      </label>
    </section>
  );
}

function ConfigForm({
  config,
  profile,
  onProfileChange,
  municipalitiesText,
  onMunicipalitiesChange,
  onChange,
}: {
  config: PrivateConfig;
  profile: HouseholdProfile | null;
  onProfileChange: (profile: HouseholdProfile) => void;
  municipalitiesText: string;
  onMunicipalitiesChange: (value: string) => void;
  onChange: (config: PrivateConfig) => void;
}) {
  const updateRate = (
    key: keyof PrivateConfig["finance"],
    side: "low" | "high",
    percent: string,
  ) => {
    const range = config.finance[key];
    if (typeof range !== "object") return;
    onChange({
      ...config,
      finance: {
        ...config.finance,
        [key]: { ...range, [side]: percentToRate(percent) },
      },
    });
  };

  return (
    <div className="config-sections">
      <section className="form-section">
        <SectionHeading
          label="01"
          title="Search and files"
          description="Local server, private profile location, towns, and included homes."
        />
        <div className="config-grid">
          <TextInput
            label="Server host"
            value={config.server.host}
            onChange={(host) =>
              onChange({ ...config, server: { ...config.server, host } })
            }
          />
          <NumberInput
            label="Server port"
            value={config.server.port}
            min={1}
            max={65535}
            onChange={(port) =>
              onChange({ ...config, server: { ...config.server, port } })
            }
          />
          <TextInput
            label="Private profile file"
            value={config.profile_file}
            onChange={(profile_file) => onChange({ ...config, profile_file })}
          />
          <TextInput
            label="Cities / towns (comma separated)"
            value={municipalitiesText}
            onChange={onMunicipalitiesChange}
          />
          <DecimalInput
            label="Minimum bedrooms"
            value={config.search.minimum_bedrooms}
            onChange={(minimum_bedrooms) =>
              onChange({
                ...config,
                search: { ...config.search, minimum_bedrooms },
              })
            }
          />
          <DecimalInput
            label="Minimum bathrooms"
            value={config.search.minimum_bathrooms}
            onChange={(minimum_bathrooms) =>
              onChange({
                ...config,
                search: { ...config.search, minimum_bathrooms },
              })
            }
          />
          <DecimalInput
            label="Maximum purchase price ($)"
            value={config.search.maximum_price}
            step="1000"
            onChange={(maximum_price) =>
              onChange({
                ...config,
                search: { ...config.search, maximum_price },
              })
            }
          />
        </div>
        <Checklist
          legend="Included property types"
          options={PROPERTY_TYPES}
          selected={config.search.included_property_types}
          onToggle={(value) => {
            const selected = config.search.included_property_types;
            if (selected.includes(value) && selected.length === 1) return;
            onChange({
              ...config,
              search: {
                ...config.search,
                included_property_types: selected.includes(value)
                  ? selected.filter((item) => item !== value)
                  : [...selected, value],
              },
            });
          }}
        />
      </section>

      <section className="form-section">
        <SectionHeading
          label="02"
          title="Financial assumptions"
          description="All ranges below are annual percentages. Mortgage term is fixed at 30 years."
        />
        <div className="range-grid">
          <DecimalInput
            label="Default down payment (%)"
            value={config.finance.default_down_payment_percent}
            max="100"
            onChange={(default_down_payment_percent) =>
              onChange({
                ...config,
                finance: { ...config.finance, default_down_payment_percent },
              })
            }
          />
          <RateRange
            label="Mortgage interest"
            range={config.finance.annual_interest_rate}
            onChange={(side, value) =>
              updateRate("annual_interest_rate", side, value)
            }
          />
          <RateRange
            label="Home insurance"
            range={config.finance.annual_insurance_rate}
            onChange={(side, value) =>
              updateRate("annual_insurance_rate", side, value)
            }
          />
          <RateRange
            label="Maintenance"
            range={config.finance.annual_maintenance_rate}
            onChange={(side, value) =>
              updateRate("annual_maintenance_rate", side, value)
            }
          />
          <RateRange
            label="Closing cost"
            range={config.finance.closing_cost_rate}
            onChange={(side, value) =>
              updateRate("closing_cost_rate", side, value)
            }
          />
        </div>
      </section>

      <section className="form-section">
        <SectionHeading
          label="03"
          title="Listing sources"
          description="Choose which live adapters GO will use once their milestones are enabled."
        />
        <div className="checklist">
          {(["redfin", "zillow", "realtor"] as const).map((source) => (
            <CheckOption
              key={source}
              label={source[0].toUpperCase() + source.slice(1)}
              checked={config.sources[source].enabled}
              onChange={() =>
                onChange({
                  ...config,
                  sources: {
                    ...config.sources,
                    [source]: { enabled: !config.sources[source].enabled },
                  },
                })
              }
            />
          ))}
        </div>
      </section>

      <section className="form-section">
        <SectionHeading
          label="04"
          title="Household profile"
          description="This context is included in LLM analysis prompts."
        />
        <div className="text-grid">
          {(["family", "must_have", "good_to_have"] as const).map((field) => (
            <label key={field}>
              {field === "family"
                ? "Household and family situation"
                : field === "must_have"
                  ? "Must have"
                  : "Good to have"}
              <textarea
                rows={7}
                value={profile?.[field] ?? ""}
                onChange={(event) =>
                  profile &&
                  onProfileChange({ ...profile, [field]: event.target.value })
                }
              />
            </label>
          ))}
        </div>
      </section>

      <section className="form-section">
        <SectionHeading
          label="05"
          title="LLM analysis template"
          description="Edit the prompt template. Braced fields are replaced with live data."
        />
        <label>
          Template
          <textarea
            className="config-editor"
            value={config.llm.analysis_template || BUILT_IN_LLM_TEMPLATE}
            onChange={(event) =>
              onChange({
                ...config,
                llm: { ...config.llm, analysis_template: event.target.value },
              })
            }
            spellCheck={false}
          />
        </label>
        <label>
          Output schema (JSON)
          <textarea
            className="config-editor"
            value={config.llm.output_schema || ""}
            onChange={(event) =>
              onChange({
                ...config,
                llm: { ...config.llm, output_schema: event.target.value },
              })
            }
            placeholder="Leave blank to use the built-in EvaluationResult schema."
            spellCheck={false}
          />
        </label>
      </section>

      <section className="form-section">
        <SectionHeading
          label="06"
          title="LLM providers"
          description="Only environment-variable names belong here, never actual API keys."
        />
        <div className="config-grid">
          <label>
            Default provider
            <select
              value={config.llm.default_provider}
              onChange={(event) =>
                onChange({
                  ...config,
                  llm: { ...config.llm, default_provider: event.target.value },
                })
              }
            >
              {Object.keys(config.llm.providers).map((provider) => (
                <option key={provider} value={provider}>
                  {provider}
                </option>
              ))}
            </select>
          </label>
          <NumberInput
            label="Timeout (seconds)"
            value={config.llm.timeout_seconds}
            min={1}
            onChange={(timeout_seconds) =>
              onChange({ ...config, llm: { ...config.llm, timeout_seconds } })
            }
          />
          <NumberInput
            label="Maximum concurrency"
            value={config.llm.max_concurrency}
            min={1}
            max={20}
            onChange={(max_concurrency) =>
              onChange({ ...config, llm: { ...config.llm, max_concurrency } })
            }
          />
        </div>
        <div className="provider-grid">
          {Object.entries(config.llm.providers).map(([name, provider]) => (
            <fieldset key={name} className="provider-card">
              <legend>{name}</legend>
              <TextInput
                label="Base URL"
                value={provider.base_url}
                onChange={(base_url) =>
                  onChange({
                    ...config,
                    llm: {
                      ...config.llm,
                      providers: {
                        ...config.llm.providers,
                        [name]: { ...provider, base_url },
                      },
                    },
                  })
                }
              />
              <TextInput
                label="Model"
                value={provider.model}
                onChange={(model) =>
                  onChange({
                    ...config,
                    llm: {
                      ...config.llm,
                      providers: {
                        ...config.llm.providers,
                        [name]: { ...provider, model },
                      },
                    },
                  })
                }
              />
              <TextInput
                label="API key environment variable"
                value={provider.api_key_env}
                onChange={(api_key_env) =>
                  onChange({
                    ...config,
                    llm: {
                      ...config.llm,
                      providers: {
                        ...config.llm.providers,
                        [name]: { ...provider, api_key_env },
                      },
                    },
                  })
                }
              />
            </fieldset>
          ))}
        </div>
      </section>

      <section className="form-section">
        <SectionHeading
          label="05"
          title="Maps and diagnostics"
          description="Google Maps remains off until explicitly enabled and configured."
        />
        <div className="checklist compact-checklist">
          <CheckOption
            label="Enable Google Maps"
            checked={config.maps.enabled}
            onChange={() =>
              onChange({
                ...config,
                maps: { ...config.maps, enabled: !config.maps.enabled },
              })
            }
          />
          <CheckOption
            label="Retain sanitized source payloads"
            checked={config.logging.retain_source_payloads}
            onChange={() =>
              onChange({
                ...config,
                logging: {
                  ...config.logging,
                  retain_source_payloads:
                    !config.logging.retain_source_payloads,
                },
              })
            }
          />
        </div>
        <div className="config-grid">
          <TextInput
            label="Maps prototype/demo key environment variable"
            value={config.maps.demo_api_key_env ?? ""}
            onChange={(demo_api_key_env) =>
              onChange({
                ...config,
                maps: {
                  ...config.maps,
                  demo_api_key_env: demo_api_key_env || null,
                },
              })
            }
          />
          <TextInput
            label="Maps browser key environment variable"
            value={config.maps.browser_api_key_env}
            onChange={(browser_api_key_env) =>
              onChange({
                ...config,
                maps: { ...config.maps, browser_api_key_env },
              })
            }
          />
          <TextInput
            label="Maps backend key environment variable"
            value={config.maps.backend_api_key_env}
            onChange={(backend_api_key_env) =>
              onChange({
                ...config,
                maps: { ...config.maps, backend_api_key_env },
              })
            }
          />
          <NumberInput
            label="Nearby radius (meters)"
            value={config.maps.nearby_search_radius_meters}
            min={100}
            max={50000}
            onChange={(nearby_search_radius_meters) =>
              onChange({
                ...config,
                maps: { ...config.maps, nearby_search_radius_meters },
              })
            }
          />
          <NumberInput
            label="Maps cache (days)"
            value={config.maps.cache_days}
            min={1}
            max={90}
            onChange={(cache_days) =>
              onChange({ ...config, maps: { ...config.maps, cache_days } })
            }
          />
          <label>
            Log level
            <select
              value={config.logging.level}
              onChange={(event) =>
                onChange({
                  ...config,
                  logging: { ...config.logging, level: event.target.value },
                })
              }
            >
              {["DEBUG", "INFO", "WARNING", "ERROR"].map((level) => (
                <option key={level} value={level}>
                  {level}
                </option>
              ))}
            </select>
          </label>
        </div>
      </section>
    </div>
  );
}

function SectionHeading({
  label,
  title,
  description,
}: {
  label: string;
  title: string;
  description: string;
}) {
  return (
    <div className="section-heading">
      <span>{label}</span>
      <div>
        <h2>{title}</h2>
        <p>{description}</p>
      </div>
    </div>
  );
}

function TextInput({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label>
      {label}
      <input value={value} onChange={(event) => onChange(event.target.value)} />
    </label>
  );
}

function NumberInput({
  label,
  value,
  min,
  max,
  onChange,
}: {
  label: string;
  value: number;
  min?: number;
  max?: number;
  onChange: (value: number) => void;
}) {
  return (
    <label>
      {label}
      <input
        type="number"
        value={value}
        min={min}
        max={max}
        onChange={(event) => onChange(Number(event.target.value))}
      />
    </label>
  );
}

function DecimalInput({
  label,
  value,
  step = "0.5",
  max,
  onChange,
}: {
  label: string;
  value: string;
  step?: string;
  max?: string;
  onChange: (value: string) => void;
}) {
  return (
    <label>
      {label}
      <input
        type="number"
        value={value}
        min="0"
        max={max}
        step={step}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}

function Checklist({
  legend,
  options,
  selected,
  onToggle,
}: {
  legend: string;
  options: readonly (readonly [string, string])[];
  selected: string[];
  onToggle: (value: string) => void;
}) {
  return (
    <fieldset className="config-checklist">
      <legend>{legend}</legend>
      <div className="checklist">
        {options.map(([value, label]) => (
          <CheckOption
            key={value}
            label={label}
            checked={selected.includes(value)}
            onChange={() => onToggle(value)}
          />
        ))}
      </div>
    </fieldset>
  );
}

function CheckOption({
  label,
  checked,
  onChange,
}: {
  label: ReactNode;
  checked: boolean;
  onChange: () => void;
}) {
  return (
    <label className="check-option">
      <input type="checkbox" checked={checked} onChange={onChange} />
      <span>{label}</span>
    </label>
  );
}

function RateRange({
  label,
  range,
  onChange,
}: {
  label: string;
  range: { low: string; high: string };
  onChange: (side: "low" | "high", value: string) => void;
}) {
  return (
    <fieldset className="rate-card">
      <legend>{label}</legend>
      <div>
        <label>
          Low
          <span className="input-suffix">
            <input
              type="number"
              min="0"
              step="0.01"
              value={rateToPercent(range.low)}
              onChange={(event) => onChange("low", event.target.value)}
            />
            <span>%</span>
          </span>
        </label>
        <label>
          High
          <span className="input-suffix">
            <input
              type="number"
              min="0"
              step="0.01"
              value={rateToPercent(range.high)}
              onChange={(event) => onChange("high", event.target.value)}
            />
            <span>%</span>
          </span>
        </label>
      </div>
    </fieldset>
  );
}
