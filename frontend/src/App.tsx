import {
  FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import {
  DownPaymentMode,
  FinancialResult,
  HouseholdProfile,
  PropertyResult,
  PropertyHistory,
  PropertyComparables,
  ResolvedFact,
  NearbyResult,
  AnalysisResult,
  ListingDigest,
  ManualFactField,
  ManualPropertyFacts,
  ManualPropertyTagCategory,
  ManualPropertyTag,
  ScanStatus,
  calculateFinance,
  loadConfig,
  loadProfile,
  loadProperties,
  loadPropertyComparables,
  loadPropertyHistory,
  loadScanStatus,
  saveConfig,
  saveProfile,
  startScan,
  loadMapConfig,
  loadNearby,
  analyzeNearby,
  runLLMAnalysis,
  loadLatestAnalysis,
  updatePropertyManualTags,
  updatePropertyManualFacts,
} from "./api/client";
import { ConfigPage } from "./ConfigPage";

type FormState = {
  municipalities: string;
  profile: HouseholdProfile;
};

const DEFAULT_MANUAL_TAGS: ManualPropertyTag[] = [
  "双黄线",
  "Corner lot",
  "剪刀煞",
];
const DEFAULT_TAG_CATEGORY: ManualPropertyTagCategory = "bad";
const TAG_CATEGORY_LABELS: Record<ManualPropertyTagCategory, string> = {
  good: "好",
  bad: "坏",
  neutral: "中",
};

const MANUAL_FACT_OPTIONS: {
  key: ManualFactField;
  label: string;
  type: "number" | "text" | "url";
  step?: string;
}[] = [
  { key: "price", label: "Price", type: "number", step: "1" },
  { key: "bedrooms", label: "Bedrooms", type: "number", step: "0.5" },
  { key: "bathrooms", label: "Bathrooms", type: "number", step: "0.5" },
  {
    key: "living_area_sqft",
    label: "Living area (sq ft)",
    type: "number",
    step: "1",
  },
  {
    key: "lot_size_sqft",
    label: "Lot size (sq ft)",
    type: "number",
    step: "1",
  },
  { key: "status", label: "Status", type: "text" },
  { key: "property_type", label: "Property type", type: "text" },
  { key: "year_built", label: "Year built", type: "number", step: "1" },
  { key: "image_url", label: "Image URL", type: "url" },
];

function manualFactLabel(field: ManualFactField): string {
  return (
    MANUAL_FACT_OPTIONS.find((option) => option.key === field)?.label ?? field
  );
}

type PageState =
  | { status: "loading" }
  | { status: "ready"; initial: FormState }
  | { status: "error"; message: string };

type ScanProgress = {
  municipality: string;
  current: number;
  total: number;
  succeeded: number;
  failed: number;
  skipped: number;
  inProgress: number;
  phase: "list" | "details" | "sold";
};

type HistoryPanelState =
  | { status: "idle" }
  | { status: "loading" }
  | {
      status: "ready";
      history: PropertyHistory;
      comparables: PropertyComparables;
    }
  | { status: "error"; message: string };

const emptyProfile: HouseholdProfile = {
  family: "",
  must_have: "",
  good_to_have: "",
  finance: {
    current_annual_gross_income: "0",
    minimum_future_annual_gross_income: "0",
    annual_travel_spending: "0",
    down_payment: { mode: "amount", value: "0" },
  },
};

function parseMunicipalities(value: string): string[] {
  const seen = new Set<string>();
  return value
    .split(",")
    .map((town) => town.trim())
    .filter((town) => {
      const key = town.toLocaleLowerCase();
      if (!town || seen.has(key)) return false;
      seen.add(key);
      return true;
    });
}

function canonicalState(state: FormState): string {
  return JSON.stringify({
    municipalities: parseMunicipalities(state.municipalities),
    profile: state.profile,
  });
}

export function App() {
  return window.location.pathname === "/config" ? <ConfigPage /> : <HomePage />;
}

function HomePage() {
  const [clock, setClock] = useState(() => Date.now());
  const [page, setPage] = useState<PageState>({ status: "loading" });
  const [form, setForm] = useState<FormState>({
    municipalities: "",
    profile: emptyProfile,
  });
  const [saveStatus, setSaveStatus] = useState<
    "idle" | "saving" | "saved" | "error"
  >("idle");
  const [saveMessage, setSaveMessage] = useState("");
  const [propertyInputs, setPropertyInputs] = useState({
    listing_price: "800000",
    annual_property_tax: "",
    monthly_hoa: "",
  });
  const [financialResult, setFinancialResult] =
    useState<FinancialResult | null>(null);
  const [financialError, setFinancialError] = useState("");
  const [scanStatus, setScanStatus] = useState<ScanStatus>({
    latest_attempt: null,
    last_success: null,
    active_job: null,
  });
  const [scanState, setScanState] = useState<"idle" | "starting" | "error">(
    "idle",
  );
  const [scanMessage, setScanMessage] = useState("");
  const [scanProgress, setScanProgress] = useState<ScanProgress | null>(null);
  const [properties, setProperties] = useState<PropertyResult[]>([]);
  const [propertyState, setPropertyState] = useState<
    "loading" | "ready" | "error"
  >("loading");
  const [propertyError, setPropertyError] = useState("");
  const [searchSummary, setSearchSummary] = useState("");
  const [propertyRefresh, setPropertyRefresh] = useState(0);
  const [selectedProperties, setSelectedProperties] = useState<Set<number>>(
    new Set(),
  );
  const [mapOpen, setMapOpen] = useState(false);
  const [analysis, setAnalysis] = useState<Map<number, AnalysisResult>>(
    new Map(),
  );
  const [listingDigest, setListingDigest] = useState<ListingDigest | null>(
    null,
  );
  const [analysisLoaded, setAnalysisLoaded] = useState(false);
  const [analysisState, setAnalysisState] = useState<
    "idle" | "running" | "error"
  >("idle");
  const [analysisTargetPropertyId, setAnalysisTargetPropertyId] = useState<
    number | null
  >(null);
  const [analysisMessage, setAnalysisMessage] = useState("");
  const [forceAnalysis, setForceAnalysis] = useState(false);
  const [propertyFilters, setPropertyFilters] = useState({
    municipality: "",
    max_price: "",
    min_bedrooms: "",
    min_bathrooms: "",
    built_after: "",
    sort: "price_asc" as "price_asc" | "price_desc" | "town",
  });

  const saveManualTags = async (
    propertyId: number,
    tags: ManualPropertyTag[],
    categories: Record<ManualPropertyTag, ManualPropertyTagCategory>,
  ) => {
    const updated = await updatePropertyManualTags(
      propertyId,
      tags,
      categories,
    );
    setProperties((current) =>
      current.map((property) =>
        property.id === propertyId ? updated : property,
      ),
    );
  };

  const saveManualFacts = async (
    propertyId: number,
    facts: ManualPropertyFacts,
  ) => {
    const updated = await updatePropertyManualFacts(propertyId, facts);
    setProperties((current) =>
      current.map((property) =>
        property.id === propertyId ? updated : property,
      ),
    );
  };

  const refreshScanStatus = useCallback(async () => {
    const status = await loadScanStatus();
    setScanStatus(status);
    if (!status.active_job) setScanProgress(null);
    return status;
  }, []);

  useEffect(() => {
    const timer = window.setInterval(() => setClock(Date.now()), 30_000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    loadLatestAnalysis()
      .then(({ results, digest }) => {
        setAnalysis(new Map(results.map((item) => [item.property_id, item])));
        setListingDigest(digest);
        setAnalysisLoaded(true);
      })
      .catch(() => setAnalysisLoaded(true));
  }, []);

  const analyzeProperties = async (
    ids: number[],
    targetPropertyId: number | null = null,
    force = forceAnalysis,
  ) => {
    setAnalysisState("running");
    setAnalysisTargetPropertyId(targetPropertyId);
    setAnalysisMessage("");
    try {
      const result = await runLLMAnalysis(
        ids,
        force,
        targetPropertyId === null,
      );
      const latest = await loadLatestAnalysis();
      setAnalysis(
        new Map(latest.results.map((item) => [item.property_id, item])),
      );
      setListingDigest(latest.digest);
      setAnalysisState("idle");
      setAnalysisMessage(`LLM analysis: ${result.status}`);
    } catch (error) {
      setAnalysisState("error");
      setAnalysisMessage(
        error instanceof Error ? error.message : "LLM analysis failed",
      );
    } finally {
      if (targetPropertyId === null) setForceAnalysis(false);
      setAnalysisTargetPropertyId(null);
    }
  };

  const analyzeSelected = () => analyzeProperties([...selectedProperties]);

  useEffect(() => {
    let active = true;
    Promise.all([loadConfig(), loadProfile(), loadScanStatus()])
      .then(([config, profile, scans]) => {
        if (!active) return;
        const loaded = {
          municipalities: config.search.municipalities.join(", "),
          profile: profile.profile,
        };
        setForm(loaded);
        setSearchSummary(
          [
            config.search.municipalities.join(", "),
            config.search.included_property_types
              .join(", ")
              .replaceAll("_", " "),
            `${config.search.minimum_bedrooms}+ beds`,
            `${config.search.minimum_bathrooms}+ baths`,
            `max ${currency(config.search.maximum_price)}`,
          ].join(" · "),
        );
        setPropertyFilters((current) => ({
          ...current,
          min_bedrooms: config.search.minimum_bedrooms,
          max_price: config.search.maximum_price,
        }));
        setPage({ status: "ready", initial: loaded });
        setScanStatus(scans);
      })
      .catch((error: unknown) => {
        if (!active) return;
        setPage({
          status: "error",
          message:
            error instanceof Error
              ? error.message
              : "Unable to load local settings",
        });
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    const activeJob = scanStatus.active_job;
    if (!activeJob) return;
    let pollTimer: number | undefined;
    let eventSource: EventSource | undefined;
    let stopped = false;

    const poll = () => {
      if (pollTimer !== undefined) return;
      pollTimer = window.setInterval(() => {
        refreshScanStatus().catch(() => undefined);
      }, 1000);
    };

    if (typeof window.EventSource === "function") {
      eventSource = new EventSource(`/api/scans/${activeJob.id}/events`);
      eventSource.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data) as {
            payload?: {
              step?: string;
              municipality?: string;
              current?: number;
              total?: number;
              count?: number;
              succeeded?: number;
              failed?: number;
              skipped?: number;
              in_progress?: number;
            };
          };
          const payload = message.payload;
          if (
            payload?.step === "municipality_started" &&
            payload.municipality
          ) {
            setScanProgress({
              municipality: payload.municipality,
              current: 0,
              total: 0,
              succeeded: 0,
              failed: 0,
              skipped: 0,
              inProgress: 0,
              phase: "list",
            });
          } else if (
            payload?.step === "listings_discovered" &&
            payload.municipality
          ) {
            setScanProgress({
              municipality: payload.municipality,
              current: 0,
              total: payload.count ?? 0,
              succeeded: 0,
              failed: 0,
              skipped: 0,
              inProgress: 0,
              phase: "details",
            });
          } else if (
            (payload?.step === "sold_search_started" ||
              payload?.step === "sold_search_completed") &&
            payload.municipality
          ) {
            setScanProgress({
              municipality: payload.municipality,
              current:
                payload.step === "sold_search_started"
                  ? Math.max((payload.current ?? 1) - 1, 0)
                  : (payload.current ?? 0),
              total: payload.total ?? 0,
              succeeded: 0,
              failed: 0,
              skipped: 0,
              inProgress: payload.step === "sold_search_started" ? 1 : 0,
              phase: "sold",
            });
          } else if (
            (payload?.step === "listing_started" ||
              payload?.step === "listing_completed" ||
              payload?.step === "listing_reused" ||
              payload?.step === "listing_detail_failed") &&
            payload.municipality
          ) {
            setScanProgress({
              municipality: payload.municipality,
              current: payload.current ?? 0,
              total: payload.total ?? 0,
              succeeded: payload.succeeded ?? 0,
              failed: payload.failed ?? 0,
              skipped: payload.skipped ?? 0,
              inProgress: payload.in_progress ?? 0,
              phase: "details",
            });
          }
        } catch {
          // A malformed progress event must not stop status refresh.
        }
        refreshScanStatus().catch(() => undefined);
      };
      eventSource.onerror = () => {
        eventSource?.close();
        if (!stopped) poll();
      };
    } else {
      poll();
    }

    return () => {
      stopped = true;
      eventSource?.close();
      if (pollTimer !== undefined) window.clearInterval(pollTimer);
    };
  }, [refreshScanStatus, scanStatus.active_job?.id]);

  const dirty = useMemo(
    () =>
      page.status === "ready" &&
      canonicalState(form) !== canonicalState(page.initial),
    [form, page],
  );

  useEffect(() => {
    if (
      page.status !== "ready" ||
      !propertyInputs.listing_price ||
      !form.profile.finance.down_payment.value
    ) {
      setFinancialResult(null);
      setFinancialError("");
      return;
    }
    const controller = new AbortController();
    const timeout = window.setTimeout(() => {
      calculateFinance(
        form.profile.finance,
        {
          listing_price: propertyInputs.listing_price,
          annual_property_tax: propertyInputs.annual_property_tax || null,
          monthly_hoa: propertyInputs.monthly_hoa || null,
        },
        controller.signal,
      )
        .then((result) => {
          setFinancialResult(result);
          setFinancialError("");
        })
        .catch((error: unknown) => {
          if (controller.signal.aborted) return;
          setFinancialResult(null);
          setFinancialError(
            error instanceof Error ? error.message : "Calculation failed",
          );
        });
    }, 200);
    return () => {
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [form.profile.finance, page.status, propertyInputs]);

  useEffect(() => {
    if (page.status !== "ready") return;
    const controller = new AbortController();
    const timeout = window.setTimeout(() => {
      setPropertyState("loading");
      loadProperties(propertyFilters, controller.signal)
        .then((result) => {
          setProperties(result.properties);
          setPropertyState("ready");
          setPropertyError("");
        })
        .catch((error: unknown) => {
          if (controller.signal.aborted) return;
          setPropertyState("error");
          setPropertyError(
            error instanceof Error
              ? error.message
              : "Unable to load properties",
          );
        });
    }, 150);
    return () => {
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [
    page.status,
    propertyFilters,
    propertyRefresh,
    scanStatus.latest_attempt?.id,
    scanStatus.latest_attempt?.status,
  ]);

  function updateProfile<K extends keyof HouseholdProfile>(
    key: K,
    value: HouseholdProfile[K],
  ) {
    setForm((current) => ({
      ...current,
      profile: { ...current.profile, [key]: value },
    }));
    setSaveStatus("idle");
  }

  function updateFinance(
    key: keyof Omit<HouseholdProfile["finance"], "down_payment">,
    value: string,
  ) {
    setForm((current) => ({
      ...current,
      profile: {
        ...current.profile,
        finance: { ...current.profile.finance, [key]: value },
      },
    }));
    setSaveStatus("idle");
  }

  function updateDownPayment(mode: DownPaymentMode, value: string) {
    setForm((current) => ({
      ...current,
      profile: {
        ...current.profile,
        finance: {
          ...current.profile.finance,
          down_payment: { mode, value },
        },
      },
    }));
    setSaveStatus("idle");
  }

  async function persistForm() {
    setSaveStatus("saving");
    setSaveMessage("");
    try {
      const municipalities = parseMunicipalities(form.municipalities);
      const [, savedProfile] = await Promise.all([
        saveConfig(municipalities),
        saveProfile(form.profile),
      ]);
      const saved = {
        municipalities: municipalities.join(", "),
        profile: savedProfile.profile,
      };
      setForm(saved);
      setPage({ status: "ready", initial: saved });
      setSaveStatus("saved");
      setSaveMessage(
        savedProfile.backup_created
          ? "Saved. Today's backup was created."
          : "Saved locally.",
      );
      setPropertyRefresh((value) => value + 1);
      return saved;
    } catch (error) {
      setSaveStatus("error");
      setSaveMessage(error instanceof Error ? error.message : "Save failed");
      throw error;
    }
  }

  async function handleSave(event: FormEvent) {
    event.preventDefault();
    await persistForm().catch(() => undefined);
  }

  async function handleGo(forceRefresh = false) {
    setScanState("starting");
    setScanMessage("");
    setScanProgress(null);
    try {
      if (dirty) await persistForm();
      const started = await startScan(forceRefresh);
      setScanStatus((current) => ({
        ...current,
        latest_attempt: started.job,
        active_job: started.job,
      }));
      setScanState("idle");
      setScanMessage(
        started.reused_active
          ? "Using the scan already in progress."
          : "Scan started.",
      );
    } catch (error) {
      setScanState("error");
      setScanMessage(
        error instanceof Error ? error.message : "Unable to start scan",
      );
      await refreshScanStatus().catch(() => undefined);
    }
  }

  if (page.status === "loading") {
    return (
      <main className="centered-state">Loading private local settings…</main>
    );
  }

  if (page.status === "error") {
    return (
      <main className="centered-state error-panel">
        <h1>Configuration unavailable</h1>
        <p>{page.message}</p>
      </main>
    );
  }

  const downPayment = form.profile.finance.down_payment;

  return (
    <main className="workspace">
      <header className="topbar">
        <div>
          <h1>Smart House Hunting</h1>
        </div>
        <div className="save-cluster">
          <a className="text-link" href="/config">
            Config
          </a>
          <span className={`save-state save-state-${saveStatus}`} role="status">
            {saveStatus === "saving" && "Saving…"}
            {saveStatus === "saved" && saveMessage}
            {saveStatus === "error" && saveMessage}
            {saveStatus === "idle" && (dirty ? "Unsaved changes" : "Saved")}
          </span>
          <button
            type="submit"
            form="profile-form"
            disabled={saveStatus === "saving" || !dirty}
          >
            Save
          </button>
        </div>
      </header>

      <form id="profile-form" className="profile-form" onSubmit={handleSave}>
        <section className="form-section form-section-wide scan-panel">
          <div className="scan-action">
            <div>
              <p className="eyebrow">User-controlled scan</p>
              <h2>Find candidate homes</h2>
              <p className="scan-note">
                GO scans enabled live sources in priority order: Redfin, Zillow,
                then Realtor. Force GO downloads every detail again.
              </p>
            </div>
            <div className="scan-buttons">
              <button
                type="button"
                className="go-button"
                onClick={() => handleGo(false)}
                disabled={
                  scanState === "starting" ||
                  saveStatus === "saving" ||
                  scanStatus.active_job !== null
                }
              >
                {scanStatus.active_job
                  ? "Scanning…"
                  : scanState === "starting"
                    ? "Starting…"
                    : "GO"}
              </button>
              <button
                type="button"
                className="force-go-button"
                onClick={() => handleGo(true)}
                disabled={
                  scanState === "starting" ||
                  saveStatus === "saving" ||
                  scanStatus.active_job !== null
                }
              >
                Force GO
              </button>
            </div>
          </div>
          <div className="scan-meta" aria-live="polite">
            <span>
              Last attempt:{" "}
              {formatTimestamp(scanStatus.latest_attempt?.created_at, clock)}
            </span>
            <span>
              Last success:{" "}
              {formatTimestamp(scanStatus.last_success?.completed_at, clock)}
            </span>
            {scanStatus.latest_attempt && (
              <span>Status: {scanStatus.latest_attempt.status}</span>
            )}
          </div>
          {scanStatus.active_job && scanProgress && (
            <div className="scan-progress" aria-live="polite">
              <div className="scan-progress-label">
                <span>
                  {scanProgress.municipality} ·{" "}
                  {scanProgress.phase === "list"
                    ? "loading listing page"
                    : scanProgress.phase === "sold"
                      ? `${scanProgress.current} / ${scanProgress.total} towns · loading sold records`
                      : `${scanProgress.current} / ${scanProgress.total} details · ` +
                        `${scanProgress.succeeded} succeeded · ` +
                        `${scanProgress.failed} failed · ` +
                        `${scanProgress.skipped} skipped (complete today) · ` +
                        `${scanProgress.inProgress} in progress`}
                </span>
                {scanProgress.total > 0 && (
                  <span>
                    {Math.round(
                      (scanProgress.current / scanProgress.total) * 100,
                    )}
                    %
                  </span>
                )}
              </div>
              <progress
                max={Math.max(scanProgress.total, 1)}
                value={scanProgress.current}
              />
            </div>
          )}
          {scanStatus.latest_attempt?.source_runs.length ? (
            <div className="source-statuses">
              {scanStatus.latest_attempt.source_runs.map((run) => (
                <span
                  key={run.source}
                  className={`source-status source-${run.status}`}
                >
                  {run.source}: {run.status.replaceAll("_", " ")}
                </span>
              ))}
            </div>
          ) : null}
          {(scanMessage || scanStatus.latest_attempt?.error_summary) && (
            <p
              className={
                scanState === "error" ? "calculation-error" : "field-note"
              }
            >
              {scanMessage || scanStatus.latest_attempt?.error_summary}
            </p>
          )}
        </section>

        <PropertyResults
          properties={properties}
          state={propertyState}
          error={propertyError}
          municipalities={parseMunicipalities(form.municipalities)}
          searchSummary={searchSummary}
          filters={propertyFilters}
          onFiltersChange={setPropertyFilters}
          selected={selectedProperties}
          onToggle={(propertyId) =>
            setSelectedProperties((current) => {
              const next = new Set(current);
              if (next.has(propertyId)) next.delete(propertyId);
              else next.add(propertyId);
              return next;
            })
          }
          onMapSelected={() => setMapOpen(true)}
          onAnalyze={analyzeSelected}
          onAnalyzeProperty={(propertyId) =>
            analyzeProperties([propertyId], propertyId, true)
          }
          onManualTagsChange={saveManualTags}
          onManualFactsChange={saveManualFacts}
          analysisState={analysisState}
          analysisTargetPropertyId={analysisTargetPropertyId}
          analysisMessage={analysisMessage}
          forceAnalysis={forceAnalysis}
          onForceAnalysis={setForceAnalysis}
          analysis={analysis}
          digest={listingDigest}
          analysisLoaded={analysisLoaded}
        />

        {mapOpen && (
          <MapPanel
            properties={properties.filter((property) =>
              selectedProperties.has(property.id),
            )}
            onClose={() => setMapOpen(false)}
          />
        )}

        <section className="form-section form-section-wide">
          <div className="section-heading">
            <span>01</span>
            <div>
              <h2>Search area</h2>
              <p>Massachusetts cities and towns, separated by commas.</p>
            </div>
          </div>
          <label>
            Cities / towns
            <input
              value={form.municipalities}
              onChange={(event) => {
                setForm((current) => ({
                  ...current,
                  municipalities: event.target.value,
                }));
                setSaveStatus("idle");
              }}
              placeholder="Town one, Town two"
            />
          </label>
        </section>

        <section className="form-section form-section-wide">
          <div className="section-heading">
            <span>02</span>
            <div>
              <h2>Household profile</h2>
              <p>
                Freeform context used only when you explicitly request LLM
                analysis.
              </p>
            </div>
          </div>
          <div className="text-grid">
            <label>
              Household and family situation
              <textarea
                value={form.profile.family}
                onChange={(event) =>
                  updateProfile("family", event.target.value)
                }
                rows={7}
              />
            </label>
            <label>
              Must have
              <textarea
                value={form.profile.must_have}
                onChange={(event) =>
                  updateProfile("must_have", event.target.value)
                }
                rows={7}
              />
            </label>
            <label>
              Good to have
              <textarea
                value={form.profile.good_to_have}
                onChange={(event) =>
                  updateProfile("good_to_have", event.target.value)
                }
                rows={7}
              />
            </label>
          </div>
        </section>

        <section className="form-section form-section-wide">
          <div className="section-heading">
            <span>03</span>
            <div>
              <h2>Financial inputs</h2>
              <p>All income values are annual gross, pre-tax amounts.</p>
            </div>
          </div>
          <div className="number-grid">
            <MoneyField
              label="Current annual gross income"
              value={form.profile.finance.current_annual_gross_income}
              onChange={(value) =>
                updateFinance("current_annual_gross_income", value)
              }
            />
            <MoneyField
              label="Minimum future gross income"
              value={form.profile.finance.minimum_future_annual_gross_income}
              onChange={(value) =>
                updateFinance("minimum_future_annual_gross_income", value)
              }
            />
            <MoneyField
              label="Annual travel spending"
              value={form.profile.finance.annual_travel_spending}
              onChange={(value) =>
                updateFinance("annual_travel_spending", value)
              }
            />
          </div>

          <fieldset className="down-payment">
            <legend>Planned down payment</legend>
            <p>
              Editing either field makes it authoritative. The other is
              calculated per listing.
            </p>
            <div className="number-grid down-payment-grid">
              <label>
                Fixed amount
                <span className="input-prefix">
                  <span>$</span>
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    value={
                      downPayment.mode === "amount"
                        ? downPayment.value
                        : (financialResult?.down_payment.amount ?? "")
                    }
                    placeholder={
                      downPayment.mode === "percent"
                        ? "Calculated per listing"
                        : "0"
                    }
                    onChange={(event) =>
                      updateDownPayment("amount", event.target.value)
                    }
                  />
                </span>
              </label>
              <label>
                Percentage
                <span className="input-suffix">
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    value={
                      downPayment.mode === "percent"
                        ? downPayment.value
                        : (financialResult?.down_payment.percent ?? "")
                    }
                    placeholder={
                      downPayment.mode === "amount"
                        ? "Calculated per listing"
                        : "0"
                    }
                    onChange={(event) =>
                      updateDownPayment("percent", event.target.value)
                    }
                  />
                  <span>%</span>
                </span>
              </label>
            </div>
          </fieldset>
        </section>

        <section className="form-section form-section-wide finance-preview">
          <div className="section-heading">
            <span>04</span>
            <div>
              <h2>Property financial preview</h2>
              <p>
                Test the financial model before listings arrive. These property
                fields are temporary and are not saved.
              </p>
            </div>
          </div>
          <div className="number-grid">
            <MoneyField
              label="Example listing price"
              value={propertyInputs.listing_price}
              onChange={(value) =>
                setPropertyInputs((current) => ({
                  ...current,
                  listing_price: value,
                }))
              }
            />
            <MoneyField
              label="Annual property tax (blank = unknown)"
              value={propertyInputs.annual_property_tax}
              onChange={(value) =>
                setPropertyInputs((current) => ({
                  ...current,
                  annual_property_tax: value,
                }))
              }
            />
            <MoneyField
              label="Monthly HOA (blank = unknown)"
              value={propertyInputs.monthly_hoa}
              onChange={(value) =>
                setPropertyInputs((current) => ({
                  ...current,
                  monthly_hoa: value,
                }))
              }
            />
          </div>
          <p className="field-note">
            Enter 0 only when the cost is known to be none.
          </p>
          {financialError && (
            <p className="calculation-error">{financialError}</p>
          )}
          {!financialError && !financialResult && (
            <p className="calculation-empty">
              Enter a listing price and planned down payment to calculate.
            </p>
          )}
          {financialResult && <FinancialBreakdown result={financialResult} />}
        </section>
      </form>
    </main>
  );
}

function formatTimestamp(
  value: string | undefined | null,
  now: number,
): string {
  if (!value) return "Never";
  const timestamp = new Date(value);
  if (Number.isNaN(timestamp.getTime())) return "Unknown";
  const absolute = new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(timestamp);
  return `${absolute} (${formatElapsedTimestamp(value, now)})`;
}

export function formatElapsedTimestamp(
  value: string,
  now = Date.now(),
): string {
  const timestamp = new Date(value).getTime();
  if (Number.isNaN(timestamp)) return "unknown time";
  const elapsedMinutes = Math.floor(Math.max(0, now - timestamp) / 60_000);
  if (elapsedMinutes === 0) return "just now";
  if (elapsedMinutes < 60) return `${elapsedMinutes}m ago`;
  const hours = Math.floor(elapsedMinutes / 60);
  const minutes = elapsedMinutes % 60;
  return `${hours}h ${minutes}m ago`;
}

function useCloseDetailsOnOutsideClick() {
  const detailsRef = useRef<HTMLDetailsElement>(null);

  useEffect(() => {
    const closeOnOutsidePointer = (event: PointerEvent) => {
      const details = detailsRef.current;
      if (
        !details?.open ||
        !(event.target instanceof Node) ||
        details.contains(event.target)
      ) {
        return;
      }
      details.open = false;
    };
    document.addEventListener("pointerdown", closeOnOutsidePointer);
    return () =>
      document.removeEventListener("pointerdown", closeOnOutsidePointer);
  }, []);

  return detailsRef;
}

function TagFilterDropdown({
  label,
  tags,
  selected,
  onToggle,
}: {
  label: string;
  tags: ManualPropertyTag[];
  selected: Set<ManualPropertyTag>;
  onToggle: (tag: ManualPropertyTag, checked: boolean) => void;
}) {
  const detailsRef = useCloseDetailsOnOutsideClick();

  return (
    <details ref={detailsRef} className="tag-dropdown">
      <summary>
        {label}
        {selected.size > 0 ? ` (${selected.size})` : ""}
      </summary>
      <div className="tag-dropdown-menu">
        {tags.map((tag) => (
          <label key={tag}>
            <input
              type="checkbox"
              checked={selected.has(tag)}
              aria-label={`${label}: ${tag}`}
              onChange={(event) => onToggle(tag, event.target.checked)}
            />
            {tag}
          </label>
        ))}
      </div>
    </details>
  );
}

function PropertyResults({
  properties,
  state,
  error,
  municipalities,
  searchSummary,
  filters,
  onFiltersChange,
  selected,
  onToggle,
  onMapSelected,
  onAnalyze,
  onAnalyzeProperty,
  onManualTagsChange,
  onManualFactsChange,
  analysisState,
  analysisTargetPropertyId,
  analysisMessage,
  forceAnalysis,
  onForceAnalysis,
  analysis,
  digest,
  analysisLoaded,
}: {
  properties: PropertyResult[];
  state: "loading" | "ready" | "error";
  error: string;
  municipalities: string[];
  searchSummary: string;
  filters: {
    municipality: string;
    max_price: string;
    min_bedrooms: string;
    min_bathrooms: string;
    built_after: string;
    sort: "price_asc" | "price_desc" | "town";
  };
  onFiltersChange: (filters: {
    municipality: string;
    max_price: string;
    min_bedrooms: string;
    min_bathrooms: string;
    built_after: string;
    sort: "price_asc" | "price_desc" | "town";
  }) => void;
  selected: Set<number>;
  onToggle: (propertyId: number) => void;
  onMapSelected: () => void;
  onAnalyze: () => void;
  onAnalyzeProperty: (propertyId: number) => void;
  onManualTagsChange: (
    propertyId: number,
    tags: ManualPropertyTag[],
    categories: Record<ManualPropertyTag, ManualPropertyTagCategory>,
  ) => Promise<void>;
  onManualFactsChange: (
    propertyId: number,
    facts: ManualPropertyFacts,
  ) => Promise<void>;
  analysisState: "idle" | "running" | "error";
  analysisTargetPropertyId: number | null;
  analysisMessage: string;
  forceAnalysis: boolean;
  onForceAnalysis: (value: boolean) => void;
  analysis: Map<number, AnalysisResult>;
  digest: ListingDigest | null;
  analysisLoaded: boolean;
}) {
  const [requiredTagFilters, setRequiredTagFilters] = useState<
    Set<ManualPropertyTag>
  >(new Set());
  const [hiddenTagFilters, setHiddenTagFilters] = useState<
    Set<ManualPropertyTag>
  >(new Set());
  const availableTags = useMemo(() => {
    const known = new Set(
      properties.flatMap((property) => property.manual_tags),
    );
    const custom = [...known]
      .filter((tag) => !DEFAULT_MANUAL_TAGS.includes(tag))
      .sort((left, right) => left.localeCompare(right));
    return [...DEFAULT_MANUAL_TAGS, ...custom];
  }, [properties]);
  const visibleProperties = properties.filter(
    (property) =>
      [...requiredTagFilters].every((tag) =>
        property.manual_tags.includes(tag),
      ) &&
      ![...hiddenTagFilters].some((tag) => property.manual_tags.includes(tag)),
  );

  const toggleRequiredTag = (tag: ManualPropertyTag, checked: boolean) => {
    setRequiredTagFilters((current) => {
      const next = new Set(current);
      if (checked) next.add(tag);
      else next.delete(tag);
      return next;
    });
    if (checked) {
      setHiddenTagFilters((current) => {
        const next = new Set(current);
        next.delete(tag);
        return next;
      });
    }
  };

  const toggleHiddenTag = (tag: ManualPropertyTag, checked: boolean) => {
    setHiddenTagFilters((current) => {
      const next = new Set(current);
      if (checked) next.add(tag);
      else next.delete(tag);
      return next;
    });
    if (checked) {
      setRequiredTagFilters((current) => {
        const next = new Set(current);
        next.delete(tag);
        return next;
      });
    }
  };

  return (
    <section className="form-section form-section-wide results-section">
      <div className="results-heading">
        <div>
          <p className="eyebrow">GO results</p>
          <div className="results-title-row">
            <h2>Matching homes</h2>
            <div className="results-actions">
              <button
                className="results-action-map"
                type="button"
                disabled={selected.size === 0}
                onClick={onMapSelected}
              >
                Map selected
              </button>
              <button
                type="button"
                disabled={
                  analysisState === "running" || properties.length === 0
                }
                onClick={onAnalyze}
              >
                {analysisState === "running"
                  ? "Analyzing…"
                  : selected.size
                    ? "Analyze selected"
                    : "Analyze"}
              </button>
              <label className="compact-check results-force-analysis">
                <input
                  type="checkbox"
                  checked={forceAnalysis}
                  onChange={(event) => onForceAnalysis(event.target.checked)}
                />
                Force all
              </label>
            </div>
          </div>
          {searchSummary && <p>{searchSummary}</p>}
          <p>
            {state === "loading"
              ? "Loading…"
              : `${visibleProperties.length} shown · ${selected.size} selected`}
          </p>
        </div>
        <div className="result-filters">
          <label>
            Town
            <select
              value={filters.municipality}
              onChange={(event) =>
                onFiltersChange({
                  ...filters,
                  municipality: event.target.value,
                })
              }
            >
              <option value="">All</option>
              {municipalities.map((town) => (
                <option key={town} value={town}>
                  {town}
                </option>
              ))}
            </select>
          </label>
          <MoneyField
            label="Max price"
            value={filters.max_price}
            onChange={(value) =>
              onFiltersChange({ ...filters, max_price: value })
            }
          />
          <label>
            Min beds
            <input
              type="number"
              min="0"
              step="0.5"
              value={filters.min_bedrooms}
              onChange={(event) =>
                onFiltersChange({
                  ...filters,
                  min_bedrooms: event.target.value,
                })
              }
            />
          </label>
          <label>
            Min baths
            <input
              type="number"
              min="0"
              step="0.5"
              value={filters.min_bathrooms}
              onChange={(event) =>
                onFiltersChange({
                  ...filters,
                  min_bathrooms: event.target.value,
                })
              }
            />
          </label>
          <label>
            Built after
            <input
              type="number"
              min="0"
              step="1"
              value={filters.built_after}
              onChange={(event) =>
                onFiltersChange({
                  ...filters,
                  built_after: event.target.value,
                })
              }
            />
          </label>
          <label>
            Sort
            <select
              value={filters.sort}
              onChange={(event) =>
                onFiltersChange({
                  ...filters,
                  sort: event.target.value as typeof filters.sort,
                })
              }
            >
              <option value="price_asc">Price: low to high</option>
              <option value="price_desc">Price: high to low</option>
              <option value="town">Town and address</option>
            </select>
          </label>
        </div>
      </div>
      <div className="manual-tag-filters" aria-label="Manual tag filters">
        <strong>Manual tags</strong>
        <TagFilterDropdown
          label="Must have tags"
          tags={availableTags}
          selected={requiredTagFilters}
          onToggle={toggleRequiredTag}
        />
        <TagFilterDropdown
          label="Hide tags"
          tags={availableTags}
          selected={hiddenTagFilters}
          onToggle={toggleHiddenTag}
        />
      </div>
      {analysisMessage && (
        <p
          className={
            analysisState === "error" ? "calculation-error" : "field-note"
          }
        >
          {analysisMessage}
        </p>
      )}
      {state === "error" && <p className="calculation-error">{error}</p>}
      {state === "ready" && properties.length === 0 && (
        <p className="empty-results">
          No candidate properties yet. Press GO to scan enabled sources.
        </p>
      )}
      {state === "ready" &&
        properties.length > 0 &&
        visibleProperties.length === 0 && (
          <p className="empty-results">
            No homes match the selected manual tags.
          </p>
        )}
      {digest && <ListingDigestPanel digest={digest} />}
      <div className="property-grid">
        {visibleProperties.map((property) => (
          <PropertyCard
            key={property.id}
            property={property}
            availableTags={availableTags}
            selected={selected.has(property.id)}
            onToggle={() => onToggle(property.id)}
            onAnalyze={() => onAnalyzeProperty(property.id)}
            onManualTagsChange={(tags, categories) =>
              onManualTagsChange(property.id, tags, categories)
            }
            onManualFactsChange={(facts) =>
              onManualFactsChange(property.id, facts)
            }
            analysisDisabled={analysisState === "running"}
            analysisRunning={analysisTargetPropertyId === property.id}
            analysis={analysis.get(property.id)}
            analysisLoaded={analysisLoaded}
          />
        ))}
      </div>
    </section>
  );
}

function ListingDigestPanel({ digest }: { digest: ListingDigest }) {
  const result = digest.result;
  return (
    <section className="listing-digest" aria-label="Listing digest">
      <div className="listing-digest-heading">
        <div>
          <p className="eyebrow">Saved LLM comparison</p>
          <h3>Listing digest</h3>
        </div>
        <small>
          {digest.property_ids.length} properties · {digest.provider} ·{" "}
          {digest.freshness} · {new Date(digest.generated_at).toLocaleString()}
        </small>
      </div>
      {result ? (
        <>
          <p className="listing-digest-overview">{result.overview}</p>
          {result.top_choices.length > 0 && (
            <div className="listing-digest-section">
              <h4>Top choices</h4>
              <ol className="digest-choice-list">
                {result.top_choices.map((choice) => (
                  <li key={choice.property_id}>
                    <a href={`#property-${choice.property_id}`}>
                      {choice.address}
                    </a>
                    <span>{choice.reason}</span>
                    {choice.strengths.length > 0 && (
                      <small>Strengths: {choice.strengths.join(" · ")}</small>
                    )}
                    {choice.concerns.length > 0 && (
                      <small>Concerns: {choice.concerns.join(" · ")}</small>
                    )}
                  </li>
                ))}
              </ol>
            </div>
          )}
          <div className="listing-digest-grid">
            <div className="listing-digest-section">
              <h4>Financial comparison</h4>
              <p>{result.financial_comparison}</p>
            </div>
            <div className="listing-digest-section">
              <h4>Tradeoffs</h4>
              {result.tradeoffs.length ? (
                <ul>
                  {result.tradeoffs.map((tradeoff) => (
                    <li key={tradeoff}>{tradeoff}</li>
                  ))}
                </ul>
              ) : (
                <p>No material tradeoffs were identified.</p>
              )}
            </div>
            <div className="listing-digest-section">
              <h4>Must-have disqualifiers</h4>
              {result.disqualifiers.length ? (
                <ul>
                  {result.disqualifiers.map((item) => (
                    <li key={`${item.property_id}-${item.finding}`}>
                      <a href={`#property-${item.property_id}`}>
                        {item.address}
                      </a>
                      : {item.finding}
                    </li>
                  ))}
                </ul>
              ) : (
                <p>No explicit must-have failures were identified.</p>
              )}
            </div>
            <div className="listing-digest-section">
              <h4>Shared unknowns</h4>
              {result.shared_unknowns.length ? (
                <ul>
                  {result.shared_unknowns.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              ) : (
                <p>No material shared unknowns were identified.</p>
              )}
            </div>
          </div>
        </>
      ) : (
        <p className="calculation-error">
          The latest digest failed:{" "}
          {digest.last_attempt_error ?? "provider error"}
        </p>
      )}
      {digest.freshness === "stale" && (
        <p className="property-warning">
          This digest is stale because the profile, property data, evaluations,
          or prompt changed.
        </p>
      )}
      {digest.last_attempt_status === "failed" && result && (
        <p className="property-warning">
          The last digest refresh failed:{" "}
          {digest.last_attempt_error ?? "provider error"}
        </p>
      )}
    </section>
  );
}

function PropertyCard({
  property,
  availableTags,
  selected,
  onToggle,
  onAnalyze,
  onManualTagsChange,
  onManualFactsChange,
  analysisDisabled,
  analysisRunning,
  analysis,
  analysisLoaded,
}: {
  property: PropertyResult;
  availableTags: ManualPropertyTag[];
  selected: boolean;
  onToggle: () => void;
  onAnalyze: () => void;
  onManualTagsChange: (
    tags: ManualPropertyTag[],
    categories: Record<ManualPropertyTag, ManualPropertyTagCategory>,
  ) => Promise<void>;
  onManualFactsChange: (facts: ManualPropertyFacts) => Promise<void>;
  analysisDisabled: boolean;
  analysisRunning: boolean;
  analysis?: AnalysisResult;
  analysisLoaded: boolean;
}) {
  const tagDropdownRef = useCloseDetailsOnOutsideClick();
  const address = `${property.street_address}${property.unit_number ? `, Unit ${property.unit_number}` : ""}`;
  const [imageAvailable, setImageAvailable] = useState(
    Boolean(property.image_url),
  );
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyState, setHistoryState] = useState<HistoryPanelState>({
    status: "idle",
  });
  const [manualTagState, setManualTagState] = useState<
    "idle" | "saving" | "error"
  >("idle");
  const [newManualTag, setNewManualTag] = useState("");
  const [newManualTagCategory, setNewManualTagCategory] =
    useState<ManualPropertyTagCategory>(DEFAULT_TAG_CATEGORY);
  const [manualFactsOpen, setManualFactsOpen] = useState(false);
  const [manualFactValues, setManualFactValues] = useState<
    Partial<Record<ManualFactField, string>>
  >({});
  const [manualFactState, setManualFactState] = useState<
    "idle" | "saving" | "error"
  >("idle");

  const toggleManualTag = async (tag: ManualPropertyTag, checked: boolean) => {
    const tags = checked
      ? [...property.manual_tags, tag]
      : property.manual_tags.filter((current) => current !== tag);
    setManualTagState("saving");
    try {
      await onManualTagsChange(tags, {
        ...property.manual_tag_categories,
      });
      setManualTagState("idle");
    } catch {
      setManualTagState("error");
    }
  };

  const addManualTag = async () => {
    const entered = newManualTag.trim().replace(/\s+/g, " ");
    if (!entered) return;
    const tag =
      [...availableTags, ...property.manual_tags].find(
        (candidate) =>
          candidate.toLocaleLowerCase() === entered.toLocaleLowerCase(),
      ) ?? entered;
    if (property.manual_tags.includes(tag)) {
      setNewManualTag("");
      return;
    }
    setManualTagState("saving");
    try {
      await onManualTagsChange([...property.manual_tags, tag], {
        ...property.manual_tag_categories,
        [tag]: newManualTagCategory,
      });
      setNewManualTag("");
      setNewManualTagCategory(DEFAULT_TAG_CATEGORY);
      setManualTagState("idle");
    } catch {
      setManualTagState("error");
    }
  };

  const openManualFacts = () => {
    const values: Partial<Record<ManualFactField, string>> = {};
    for (const option of MANUAL_FACT_OPTIONS) {
      const field = option.key;
      const manualValue = property.manual_values[field];
      const resolvedValue = (property as unknown as Record<string, unknown>)[
        field
      ];
      const currentValue =
        manualValue ??
        (field === "image_url"
          ? property.image_url
          : typeof resolvedValue === "object" && resolvedValue !== null
            ? (resolvedValue as { display_value?: string }).display_value
            : undefined);
      if (currentValue !== undefined && currentValue !== null) {
        values[field] = String(currentValue);
      }
    }
    setManualFactValues(values);
    setManualFactState("idle");
    setManualFactsOpen(true);
  };

  const saveManualFactValues = async () => {
    const facts: ManualPropertyFacts = {};
    for (const option of MANUAL_FACT_OPTIONS) {
      const field = option.key;
      if (field === "lot_size_sqft") {
        const sqft = manualFactValues.lot_size_sqft?.trim() ?? "";
        const acres = manualFactValues.lot_size_acres?.trim() ?? "";
        if (sqft || property.manual_values.lot_size_sqft !== undefined) {
          facts.lot_size_sqft = sqft || null;
        }
        if (acres) facts.lot_size_acres = acres;
        continue;
      }
      const value = manualFactValues[field]?.trim() ?? "";
      if (value || property.manual_values[field] !== undefined) {
        facts[field] = value || null;
      }
    }
    setManualFactState("saving");
    try {
      await onManualFactsChange(facts);
      setManualFactState("idle");
      setManualFactsOpen(false);
    } catch {
      setManualFactState("error");
    }
  };

  useEffect(() => {
    setImageAvailable(Boolean(property.image_url));
  }, [property.image_url]);

  const toggleHistory = async () => {
    const opening = !historyOpen;
    setHistoryOpen(opening);
    if (!opening || historyState.status !== "idle") return;
    setHistoryState({ status: "loading" });
    try {
      const [history, comparables] = await Promise.all([
        loadPropertyHistory(property.id),
        loadPropertyComparables(property.id),
      ]);
      setHistoryState({ status: "ready", history, comparables });
    } catch (error) {
      setHistoryState({
        status: "error",
        message:
          error instanceof Error
            ? error.message
            : "History could not be loaded",
      });
    }
  };

  return (
    <article
      id={`property-${property.id}`}
      className={`property-card${selected ? " property-selected" : ""}`}
    >
      <span className={`retrieval-pill retrieval-${property.retrieval_status}`}>
        {property.retrieval_status === "retrieved" ? "Retrieved" : "Partial"}
      </span>
      {property.image_url && imageAvailable ? (
        <img
          className="property-image"
          src={property.image_url}
          alt={`Lead listing image for ${address}`}
          loading="lazy"
          decoding="async"
          referrerPolicy="no-referrer"
          onError={() => setImageAvailable(false)}
        />
      ) : (
        <div className="property-image-placeholder">No listing image</div>
      )}
      <div className="property-card-heading">
        <label className="property-select">
          <input
            type="checkbox"
            checked={selected}
            onChange={onToggle}
            aria-label={`Select ${address}`}
          />
        </label>
        <div>
          <p className="property-town">{property.municipality}, MA</p>
          <h3>
            {address}（
            {property.price.display_value
              ? wholeCurrency(property.price.display_value)
              : "-"}
            ）
          </h3>
        </div>
        <div className="property-card-actions">
          <strong className="property-price">
            {property.price.display_value
              ? wholeCurrency(property.price.display_value)
              : "-"}
          </strong>
          <div className="listing-links">
            {property.sources.map((source) => (
              <a
                key={source.source}
                className="listing-link"
                href={source.url}
                target="_blank"
                rel="noreferrer"
              >
                {sourceLabel(source.source)} ↗
              </a>
            ))}
          </div>
        </div>
      </div>
      <div className="property-facts">
        <Fact label="Beds" fact={property.bedrooms} />
        <Fact label="Baths" fact={property.bathrooms} />
        <Fact label="Sq ft" fact={property.living_area_sqft} />
        <Fact
          label="Lot"
          fact={property.lot_size_sqft}
          format={formatLotSize}
        />
        <Fact label="Status" fact={property.status} />
        <Fact label="Type" fact={property.property_type} />
        <Fact label="Built" fact={property.year_built} />
      </div>
      <div className="property-tag-editor">
        <div className="property-tag-row" aria-label={`Tags for ${address}`}>
          {property.manual_tags.map((tag) => (
            <span
              key={tag}
              className={`property-tag-pill property-tag-${property.manual_tag_categories?.[tag] ?? DEFAULT_TAG_CATEGORY}`}
            >
              {tag}
            </span>
          ))}
        </div>
        <details
          ref={tagDropdownRef}
          className="tag-dropdown property-tag-dropdown"
        >
          <summary>Tags ({property.manual_tags.length})</summary>
          <div className="tag-dropdown-menu">
            {availableTags.map((tag) => (
              <label key={tag}>
                <input
                  type="checkbox"
                  checked={property.manual_tags.includes(tag)}
                  disabled={manualTagState === "saving"}
                  aria-label={`${tag} for ${address}`}
                  onChange={(event) =>
                    toggleManualTag(tag, event.target.checked)
                  }
                />
                {tag}
              </label>
            ))}
            <div className="tag-add-form">
              <input
                type="text"
                maxLength={50}
                value={newManualTag}
                disabled={manualTagState === "saving"}
                aria-label={`Add tag for ${address}`}
                placeholder="New tag"
                onChange={(event) => setNewManualTag(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key !== "Enter") return;
                  event.preventDefault();
                  void addManualTag();
                }}
              />
              <button
                type="button"
                disabled={manualTagState === "saving" || !newManualTag.trim()}
                onClick={() => void addManualTag()}
              >
                Add
              </button>
              <div
                className="tag-category-options"
                aria-label="New tag category"
              >
                {(
                  Object.keys(
                    TAG_CATEGORY_LABELS,
                  ) as ManualPropertyTagCategory[]
                ).map((category) => (
                  <label key={category}>
                    <input
                      type="radio"
                      name={`tag-category-${property.id}`}
                      checked={newManualTagCategory === category}
                      onChange={() => setNewManualTagCategory(category)}
                    />
                    {TAG_CATEGORY_LABELS[category]}
                  </label>
                ))}
              </div>
            </div>
            {manualTagState === "saving" && <small>Saving…</small>}
            {manualTagState === "error" && (
              <small className="property-warning">Could not save tags.</small>
            )}
          </div>
        </details>
      </div>
      <div className="manual-facts-entry">
        <button type="button" onClick={openManualFacts}>
          Manual input
        </button>
        {property.missing_fields.length > 0 && (
          <small>
            Missing from crawl:{" "}
            {property.missing_fields.map(manualFactLabel).join(", ")}
          </small>
        )}
      </div>
      {manualFactsOpen && (
        <div className="manual-facts-panel">
          <strong>Manual fallback values</strong>
          <p>
            A later crawl replaces these values when it returns the same fields.
            If the crawl still omits them, these values remain.
          </p>
          <div className="manual-facts-grid">
            {MANUAL_FACT_OPTIONS.map((option) =>
              option.key === "lot_size_sqft" ? (
                <div key={option.key} className="manual-lot-size-inputs">
                  <label>
                    Lot size (sq ft)
                    <input
                      type="number"
                      min="0"
                      step="1"
                      value={manualFactValues.lot_size_sqft ?? ""}
                      disabled={manualFactState === "saving"}
                      onChange={(event) =>
                        setManualFactValues((current) => ({
                          ...current,
                          lot_size_sqft: event.target.value,
                          lot_size_acres: "",
                        }))
                      }
                    />
                  </label>
                  <label>
                    Lot size (acres)
                    <input
                      type="number"
                      min="0"
                      step="0.01"
                      value={manualFactValues.lot_size_acres ?? ""}
                      disabled={manualFactState === "saving"}
                      onChange={(event) =>
                        setManualFactValues((current) => ({
                          ...current,
                          lot_size_acres: event.target.value,
                          lot_size_sqft: "",
                        }))
                      }
                    />
                  </label>
                </div>
              ) : (
                <label key={option.key}>
                  {option.label}
                  <input
                    type={option.type}
                    min={option.type === "number" ? "0" : undefined}
                    step={option.step}
                    value={manualFactValues[option.key] ?? ""}
                    disabled={manualFactState === "saving"}
                    onChange={(event) =>
                      setManualFactValues((current) => ({
                        ...current,
                        [option.key]: event.target.value,
                      }))
                    }
                  />
                </label>
              ),
            )}
          </div>
          {manualFactState === "error" && (
            <small className="property-warning">
              Could not save manual values.
            </small>
          )}
          <div className="manual-facts-actions">
            <button
              type="button"
              className="history-toggle"
              disabled={manualFactState === "saving"}
              onClick={() => setManualFactsOpen(false)}
            >
              Cancel
            </button>
            <button
              type="button"
              disabled={manualFactState === "saving"}
              onClick={() => void saveManualFactValues()}
            >
              {manualFactState === "saving" ? "Saving…" : "Save manual values"}
            </button>
          </div>
        </div>
      )}
      <div className="property-finance">
        <span>Estimated per month</span>
        {property.financials ? (
          <>
            <strong>
              {moneyRange(property.financials.estimated_monthly_housing_total)}
            </strong>
            <small>
              Down {currency(property.financials.down_payment.amount)} · Loan{" "}
              {currency(property.financials.loan_amount)}
            </small>
          </>
        ) : (
          <>
            <strong>-</strong>
            <small>Down - · Loan -</small>
          </>
        )}
      </div>
      {property.conflict_fields.length > 0 && (
        <p className="property-warning">
          Source conflict: {property.conflict_fields.join(", ")}
        </p>
      )}
      {property.possible_duplicate_ids.length > 0 && (
        <p className="property-warning">
          Possible duplicate kept separate: #
          {property.possible_duplicate_ids.join(", #")}
        </p>
      )}
      <div className="property-card-controls">
        <button
          className="property-llm-button"
          type="button"
          disabled={analysisDisabled}
          onClick={onAnalyze}
        >
          {analysisRunning ? "Analyzing…" : "LLM analysis"}
        </button>
        <button
          className="history-toggle"
          type="button"
          onClick={toggleHistory}
        >
          {historyOpen ? "Hide history" : "History & sold comparables"}
        </button>
      </div>
      {historyOpen && <PropertyHistoryPanel state={historyState} />}
      {analysis?.result && (
        <div className="property-analysis">
          <strong>
            LLM analysis · {analysis.provider} · {analysis.freshness}
          </strong>
          <p>{analysis.result.summary}</p>
          {analysis.result.must_have.map((item) => (
            <small key={item.id}>
              <b>{item.result.replaceAll("_", " ")}</b> · {item.evidence}
            </small>
          ))}
          {analysis.result.good_to_have.map((item) => (
            <small key={item.id}>
              <b>{item.score}/100</b> · {item.evidence}
            </small>
          ))}
          {analysis.result.missing_information.length > 0 && (
            <small>
              Missing: {analysis.result.missing_information.join(", ")}
            </small>
          )}
          <small>
            Analyzed {new Date(analysis.analyzed_at).toLocaleString()}
          </small>
          {analysis.last_attempt_status === "failed" && (
            <small className="property-warning">
              Last reanalysis failed:{" "}
              {analysis.last_attempt_error ?? "provider error"}
            </small>
          )}
        </div>
      )}
      {analysisLoaded && !analysis && (
        <div className="property-analysis">
          <strong>LLM analysis · missing</strong>
          <small>This property has not been analyzed.</small>
        </div>
      )}
    </article>
  );
}

function PropertyHistoryPanel({ state }: { state: HistoryPanelState }) {
  if (state.status === "idle" || state.status === "loading") {
    return <p className="history-message">Loading history…</p>;
  }
  if (state.status === "error") {
    return <p className="property-warning">{state.message}</p>;
  }
  return (
    <div className="property-history">
      <section>
        <h4>Listing history</h4>
        {state.history.events.length ? (
          <ol className="history-list">
            {state.history.events.map((event) => (
              <li key={event.id}>
                <span>{new Date(event.occurred_at).toLocaleDateString()}</span>
                <strong>{event.event_type.replaceAll("_", " ")}</strong>
                <span>{formatEventChange(event)}</span>
                {event.source_url ? (
                  <a href={event.source_url} target="_blank" rel="noreferrer">
                    {sourceLabel(event.source ?? "source")} ↗
                  </a>
                ) : (
                  <span>{sourceLabel(event.source ?? "source")}</span>
                )}
              </li>
            ))}
          </ol>
        ) : (
          <p className="history-message">No recorded changes yet.</p>
        )}
      </section>
      <section>
        <h4>Sold comparables</h4>
        <p className="history-disclaimer">{state.comparables.disclaimer}</p>
        {state.comparables.expanded_to_nearby_towns && (
          <p className="history-message">
            Expanded beyond the same town due to limited records.
          </p>
        )}
        {state.comparables.comparables.length ? (
          <div className="comparable-list">
            {state.comparables.comparables.map((item) => (
              <article key={item.id} className="comparable-card">
                <div>
                  <strong>
                    {item.street_address ?? "Address unavailable"}
                  </strong>
                  <span>{item.municipality ?? "-"}</span>
                </div>
                <div>
                  <span>Sold {item.sale_date ?? "-"}</span>
                  <strong>
                    {item.sale_price ? wholeCurrency(item.sale_price) : "-"}
                  </strong>
                </div>
                <small>
                  Original list{" "}
                  {item.original_listing_price
                    ? wholeCurrency(item.original_listing_price)
                    : "-"}
                  {" · "}difference{" "}
                  {signedCurrency(item.difference_from_original)}
                </small>
                <small>
                  Final list{" "}
                  {item.final_listing_price
                    ? wholeCurrency(item.final_listing_price)
                    : "-"}
                  {" · "}difference {signedCurrency(item.difference_from_final)}
                </small>
                <small>
                  {item.bedrooms ?? "-"} bd · {item.bathrooms ?? "-"} ba ·{" "}
                  {item.living_area_sqft?.toLocaleString() ?? "-"} sq ft ·{" "}
                  {item.distance_miles ?? "-"} mi
                </small>
                <small>
                  {item.similarity_reasons.join(" · ") ||
                    "Similarity evidence unavailable"}
                </small>
                <small>
                  Retrieved {new Date(item.retrieved_at).toLocaleString()}
                </small>
                <a href={item.url} target="_blank" rel="noreferrer">
                  {sourceLabel(item.source)} ↗
                </a>
                {item.missing_fields.length > 0 && (
                  <small>Missing: {item.missing_fields.join(", ")}</small>
                )}
              </article>
            ))}
          </div>
        ) : (
          <p className="history-message">
            No sold comparable records collected yet.
          </p>
        )}
      </section>
    </div>
  );
}

type MapObject = { fitBounds: (bounds: BoundsObject) => void };
type BoundsObject = { extend: (point: { lat: number; lng: number }) => void };
type MapsNamespace = {
  Map: new (element: HTMLElement, options: object) => MapObject;
  LatLngBounds: new () => BoundsObject;
  Marker: new (options: object) => {
    addListener: (name: string, callback: () => void) => void;
  };
  InfoWindow: new (options: object) => { open: (options: object) => void };
};

declare global {
  interface Window {
    google?: { maps: MapsNamespace };
  }
}

let mapsScript: Promise<void> | null = null;
function loadGoogleMaps(apiKey: string): Promise<void> {
  if (window.google?.maps) return Promise.resolve();
  if (mapsScript) return mapsScript;
  mapsScript = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(apiKey)}`;
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () =>
      reject(new Error("Google Maps JavaScript could not be loaded"));
    document.head.appendChild(script);
  });
  return mapsScript;
}

function MapPanel({
  properties,
  onClose,
}: {
  properties: PropertyResult[];
  onClose: () => void;
}) {
  const container = useRef<HTMLDivElement>(null);
  const mapObject = useRef<MapObject | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [message, setMessage] = useState("");
  const [nearby, setNearby] = useState<NearbyResult[]>([]);
  const [nearbyRunning, setNearbyRunning] = useState(false);
  const [force, setForce] = useState(false);
  const ids = useMemo(
    () => properties.map((property) => property.id),
    [properties],
  );

  useEffect(() => {
    let active = true;
    Promise.all([loadMapConfig(), loadNearby(ids)])
      .then(async ([config, cached]) => {
        if (!config.enabled || !config.available || !config.api_key)
          throw new Error(
            "Enable Maps and configure its browser key locally first",
          );
        await loadGoogleMaps(config.api_key);
        if (!active || !container.current || !window.google) return;
        const maps = window.google.maps;
        const map = new maps.Map(container.current, {
          zoom: 13,
          mapTypeControl: false,
        });
        const bounds = new maps.LatLngBounds();
        for (const property of properties) {
          if (!property.latitude || !property.longitude) continue;
          const point = {
            lat: Number(property.latitude),
            lng: Number(property.longitude),
          };
          bounds.extend(point);
          const marker = new maps.Marker({
            map,
            position: point,
            title: property.street_address,
          });
          const content = document.createElement("div");
          const strong = document.createElement("strong");
          strong.textContent = property.street_address;
          content.appendChild(strong);
          const link = document.createElement("a");
          link.href = `#property-${property.id}`;
          link.textContent = " View local card";
          content.appendChild(link);
          const info = new maps.InfoWindow({ content });
          marker.addListener("click", () => info.open({ map, anchor: marker }));
        }
        map.fitBounds(bounds);
        mapObject.current = map;
        setNearby(cached.results);
        setState("ready");
      })
      .catch((error: unknown) => {
        if (active) {
          setState("error");
          setMessage(error instanceof Error ? error.message : "Map failed");
        }
      });
    return () => {
      active = false;
    };
  }, [ids, properties]);

  useEffect(() => {
    if (!mapObject.current || !window.google || nearby.length === 0) return;
    const maps = window.google.maps;
    for (const place of nearby)
      new maps.Marker({
        map: mapObject.current,
        position: { lat: Number(place.latitude), lng: Number(place.longitude) },
        title: `${place.category}: ${place.name}`,
      });
  }, [nearby]);

  const runNearby = async () => {
    if (
      !window.confirm(
        `Send coordinates for ${properties.length} selected properties and 5 nearby-place categories to Google?`,
      )
    )
      return;
    setNearbyRunning(true);
    setMessage("");
    try {
      const result = await analyzeNearby(ids, force);
      setNearby(result.results);
      setMessage(`Nearby analysis: ${result.status}`);
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Nearby analysis failed",
      );
    } finally {
      setNearbyRunning(false);
      setForce(false);
    }
  };

  return (
    <div
      className="map-dialog"
      role="dialog"
      aria-modal="true"
      aria-label="Selected properties map"
    >
      <div className="map-panel">
        <div className="map-heading">
          <div>
            <h2>Selected properties</h2>
            <p>
              {properties.length} properties. Opening this view sends their
              coordinates and map activity to Google.
            </p>
          </div>
          <button type="button" onClick={onClose}>
            Close
          </button>
        </div>
        {state === "error" && <p className="calculation-error">{message}</p>}
        <div className="google-map" ref={container}>
          {state === "loading" ? "Loading map…" : ""}
        </div>
        <div className="map-actions">
          <button
            type="button"
            disabled={nearbyRunning || state !== "ready"}
            onClick={runNearby}
          >
            {nearbyRunning ? "Checking…" : "Check walkable places"}
          </button>
          <label>
            <input
              type="checkbox"
              checked={force}
              onChange={(event) => setForce(event.target.checked)}
            />{" "}
            Force refresh
          </label>
        </div>
        {message && state !== "error" && (
          <p className="field-note">{message}</p>
        )}
        <div className="nearby-results">
          {nearby.map((place) => (
            <article
              key={`${place.property_id}-${place.category}-${place.name}`}
            >
              <strong>{place.name}</strong>
              <span>
                {place.category.replaceAll("_", " ")} ·{" "}
                {place.route_status === "success" &&
                place.walking_duration_seconds !== null
                  ? `${Math.ceil(place.walking_duration_seconds / 60)} min walk · ${Math.round((place.walking_distance_meters ?? 0) / 160.934) / 10} mi`
                  : "walking route unavailable"}
              </span>
              <small>
                {place.property_address} · retrieved{" "}
                {new Date(place.retrieved_at).toLocaleString()}
              </small>
              {place.google_maps_uri && (
                <a
                  href={place.google_maps_uri}
                  target="_blank"
                  rel="noreferrer"
                >
                  Google Maps ↗
                </a>
              )}
            </article>
          ))}
        </div>
      </div>
    </div>
  );
}

function Fact({
  label,
  fact,
  format = (value) => value,
}: {
  label: string;
  fact: ResolvedFact;
  format?: (value: string) => string;
}) {
  return (
    <span>
      <small>{label}</small>
      <strong>{fact.display_value ? format(fact.display_value) : "-"}</strong>
    </span>
  );
}

function formatLotSize(value: string): string {
  const squareFeet = Number(value);
  if (!Number.isFinite(squareFeet)) return value;
  const formattedSquareFeet = Math.round(squareFeet).toLocaleString("en-US");
  if (squareFeet >= 4356) {
    return `${(squareFeet / 43560).toFixed(2)} ac / ${formattedSquareFeet} sq ft`;
  }
  return `${formattedSquareFeet} sq ft`;
}

function currency(value: string): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(Number(value));
}

function wholeCurrency(value: string): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(Number(value));
}

function signedCurrency(value: string | null): string {
  if (value === null) return "-";
  const amount = Number(value);
  if (!Number.isFinite(amount)) return value;
  if (amount === 0) return wholeCurrency("0");
  return `${amount > 0 ? "+" : "−"}${wholeCurrency(String(Math.abs(amount)))}`;
}

function formatEventChange(event: PropertyHistory["events"][number]): string {
  const field = event.event_type === "price_change" ? "price" : "status";
  const oldValue = event.old_value?.[field];
  const newValue = event.new_value?.[field];
  const format = (value: unknown) => {
    if (value === null || value === undefined) return "-";
    return field === "price" ? wholeCurrency(String(value)) : String(value);
  };
  if (oldValue !== undefined || newValue !== undefined) {
    return `${format(oldValue)} → ${format(newValue)}`;
  }
  const firstPrice = event.new_value?.price;
  return firstPrice ? wholeCurrency(String(firstPrice)) : "";
}

function sourceLabel(source: string): string {
  return source
    .split(/[-_]/)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function moneyRange(range: { low: string; high: string }): string {
  if (range.low === range.high) return currency(range.low);
  return `${currency(range.low)} – ${currency(range.high)}`;
}

function percentRange(range: { low: string; high: string } | null): string {
  if (!range) return "Unknown (gross income is zero)";
  if (range.low === range.high) return `${range.low}%`;
  return `${range.low}% – ${range.high}%`;
}

function FinancialBreakdown({ result }: { result: FinancialResult }) {
  return (
    <div className="financial-results" aria-live="polite">
      <div className="result-highlight">
        <span>
          {result.total_is_partial
            ? "Partial estimated monthly housing cost"
            : "Estimated monthly housing cost"}
        </span>
        <strong>{moneyRange(result.estimated_monthly_housing_total)}</strong>
        {result.total_is_partial && (
          <small>
            Excludes unknown: {result.unknown_components.join(", ")}.
          </small>
        )}
      </div>
      <dl className="breakdown-grid">
        <Result label="Down payment">
          {currency(result.down_payment.amount)} ({result.down_payment.percent}
          %)
        </Result>
        <Result label="Loan amount">{currency(result.loan_amount)}</Result>
        <Result label="Estimated closing cost">
          {moneyRange(result.estimated_closing_cost)}
        </Result>
        <Result label="30-year principal + interest / month">
          {moneyRange(result.monthly_principal_and_interest)}
        </Result>
        <Result label="Property tax / month">
          {result.monthly_property_tax === null
            ? "Unknown"
            : currency(result.monthly_property_tax)}
        </Result>
        <Result label="Insurance / month">
          {moneyRange(result.monthly_insurance)}
        </Result>
        <Result label="HOA / month">
          {result.monthly_hoa === null
            ? "Unknown"
            : currency(result.monthly_hoa)}
        </Result>
        <Result label="Maintenance / month">
          {moneyRange(result.monthly_maintenance)}
        </Result>
        <Result label="Known housing subtotal / month">
          {moneyRange(result.known_monthly_housing_subtotal)}
        </Result>
        <Result label="Housing / current gross income">
          {percentRange(result.current_income.housing_percent)}
        </Result>
        <Result label="Housing / minimum future gross income">
          {percentRange(result.minimum_future_income.housing_percent)}
        </Result>
        <Result label="Current monthly gross pre-tax balance">
          {moneyRange(
            result.current_income
              .monthly_gross_balance_after_housing_and_travel,
          )}
        </Result>
        <Result label="Minimum future monthly gross pre-tax balance">
          {moneyRange(
            result.minimum_future_income
              .monthly_gross_balance_after_housing_and_travel,
          )}
        </Result>
      </dl>
      <p className="gross-warning">
        Gross, pre-tax figures only—not disposable income or a risk rating.
        Taxes, debt, food, childcare, healthcare, and other living costs are not
        deducted.
      </p>
    </div>
  );
}

function Result({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

function MoneyField({
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
      <span className="input-prefix">
        <span>$</span>
        <input
          type="number"
          min="0"
          step="1"
          value={value}
          onChange={(event) => onChange(event.target.value)}
        />
      </span>
    </label>
  );
}
