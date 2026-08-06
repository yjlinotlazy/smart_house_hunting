export type PublicConfig = {
  server: { host: string; port: number };
  search: {
    state: "MA";
    municipalities: string[];
    included_property_types: string[];
    minimum_bedrooms: string;
    minimum_bathrooms: string;
    maximum_price: string;
  };
  llm: { default_provider: string; providers: string[] };
  ui_filters: PropertyFilters;
};

export type DownPaymentMode = "amount" | "percent";

export type HouseholdProfile = {
  family: string;
  must_have: string;
  good_to_have: string;
  finance: {
    current_annual_gross_income: string;
    minimum_future_annual_gross_income: string;
    annual_travel_spending: string;
    down_payment: {
      mode: DownPaymentMode;
      value: string;
    };
  };
};

export type ProfileResponse = {
  profile: HouseholdProfile;
  exists: boolean;
  version: string;
  backup_created?: boolean;
};

export type DecimalRange = { low: string; high: string };

export type FinancialResult = {
  listing_price: string;
  down_payment: {
    authoritative_mode: DownPaymentMode;
    amount: string;
    percent: string;
  };
  loan_amount: string;
  estimated_closing_cost: DecimalRange;
  monthly_principal_and_interest: DecimalRange;
  monthly_property_tax: string | null;
  monthly_insurance: DecimalRange;
  monthly_hoa: string | null;
  monthly_maintenance: DecimalRange;
  known_monthly_housing_subtotal: DecimalRange;
  estimated_monthly_housing_total: DecimalRange;
  total_is_partial: boolean;
  unknown_components: string[];
  current_income: IncomeImpact;
  minimum_future_income: IncomeImpact;
};

type IncomeImpact = {
  housing_percent: DecimalRange | null;
  monthly_gross_balance_after_housing_and_travel: DecimalRange;
};

export type PropertyFinancialInputs = {
  listing_price: string;
  annual_property_tax: string | null;
  monthly_hoa: string | null;
};

export type SourceRun = {
  source: string;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  counters: Record<string, unknown>;
  error_summary: string | null;
};

export type ScanJob = {
  id: number;
  status: string;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  counters: Record<string, unknown>;
  error_summary: string | null;
  source_runs: SourceRun[];
};

export type ScanStatus = {
  latest_attempt: ScanJob | null;
  last_success: ScanJob | null;
  active_job: ScanJob | null;
};

export type ResolvedFact = {
  display_value: string | null;
  source_values: { source: string; value: string | null }[];
  conflict: boolean;
  resolution_rule: string;
};

export type PropertySource = {
  source: string;
  url: string;
  status: string | null;
  price: string | null;
  bedrooms: string | null;
  bathrooms: string | null;
  living_area_sqft: number | null;
  lot_size_sqft: string | null;
  property_tax_annual: string | null;
  hoa_monthly: string | null;
  detail_error: string | null;
};

export type ManualPropertyTag = string;
export type ManualPropertyTagCategory = "good" | "bad" | "neutral";

export type ManualFactField =
  | "price"
  | "bedrooms"
  | "bathrooms"
  | "living_area_sqft"
  | "lot_size_sqft"
  | "lot_size_acres"
  | "property_tax_annual"
  | "hoa_monthly"
  | "status"
  | "property_type"
  | "year_built"
  | "image_url";

export type ManualPropertyFacts = Partial<
  Record<ManualFactField, string | number | null>
>;

export type PropertyResult = {
  id: number;
  street_address: string;
  unit_number: string | null;
  municipality: string;
  state: "MA";
  postal_code: string | null;
  latitude: string | null;
  longitude: string | null;
  image_url: string | null;
  manual_tags: ManualPropertyTag[];
  manual_tag_categories: Record<ManualPropertyTag, ManualPropertyTagCategory>;
  manual_values: Partial<Record<ManualFactField, string | number>>;
  retrieval_status: "retrieved" | "partially_retrieved";
  missing_fields: ManualFactField[];
  price: ResolvedFact;
  bedrooms: ResolvedFact;
  bathrooms: ResolvedFact;
  living_area_sqft: ResolvedFact;
  lot_size_sqft: ResolvedFact;
  property_tax_annual: ResolvedFact;
  hoa_monthly: ResolvedFact;
  status: ResolvedFact;
  property_type: ResolvedFact;
  year_built: ResolvedFact;
  sources: PropertySource[];
  conflict_fields: string[];
  possible_duplicate_ids: number[];
  financials: FinancialResult | null;
  financial_error: string | null;
};

export type PropertyFilters = {
  municipality?: string;
  max_price?: string;
  min_bedrooms?: string;
  min_bathrooms?: string;
  built_after?: string;
  sort?: "price_asc" | "price_desc" | "town";
};

export type PropertyEvent = {
  id: number;
  event_type: string;
  source: string | null;
  source_url: string | null;
  occurred_at: string;
  old_value: Record<string, unknown> | null;
  new_value: Record<string, unknown> | null;
};

export type PropertyHistory = {
  property_id: number;
  events: PropertyEvent[];
};

export type SoldComparable = {
  id: number;
  source: string;
  url: string;
  street_address: string | null;
  municipality: string | null;
  sale_date: string | null;
  sale_price: string | null;
  original_listing_price: string | null;
  final_listing_price: string | null;
  difference_from_original: string | null;
  difference_from_final: string | null;
  property_type: string | null;
  bedrooms: string | null;
  bathrooms: string | null;
  living_area_sqft: number | null;
  distance_miles: string | null;
  similarity_score: number;
  similarity_reasons: string[];
  scope: "same_town" | "nearby_town_expansion";
  retrieved_at: string;
  missing_fields: string[];
};

export type PropertyComparables = {
  property_id: number;
  comparables: SoldComparable[];
  expanded_to_nearby_towns: boolean;
  disclaimer: string;
};

export type PrivateConfig = {
  server: { host: string; port: number };
  profile_file: string;
  search: {
    state: "MA";
    municipalities: string[];
    included_property_types: string[];
    minimum_bedrooms: string;
    minimum_bathrooms: string;
    maximum_price: string;
  };
  finance: {
    mortgage_years: 30;
    default_down_payment_percent: string;
    annual_interest_rate: DecimalRange;
    annual_insurance_rate: DecimalRange;
    annual_maintenance_rate: DecimalRange;
    closing_cost_rate: DecimalRange;
  };
  sources: Record<"redfin" | "zillow" | "realtor", { enabled: boolean }>;
  llm: {
    default_provider: string;
    timeout_seconds: number;
    max_concurrency: number;
    analysis_template: string;
    output_schema: string;
    providers: Record<
      string,
      { base_url: string; api_key_env: string; model: string }
    >;
  };
  maps: {
    enabled: boolean;
    demo_api_key_env: string | null;
    browser_api_key_env: string;
    backend_api_key_env: string;
    nearby_search_radius_meters: number;
    cache_days: number;
  };
  logging: {
    level: string;
    include_profile_content: false;
    retain_source_payloads: boolean;
  };
};

export type NearbyResult = {
  property_id: number;
  property_address: string;
  category: string;
  name: string;
  primary_type: string | null;
  formatted_address: string | null;
  latitude: string;
  longitude: string;
  google_maps_uri: string | null;
  walking_distance_meters: number | null;
  walking_duration_seconds: number | null;
  route_status: string;
  retrieved_at: string;
};

export type AnalysisResult = {
  property_id: number;
  status: string;
  last_attempt_status: string;
  last_attempt_error: string | null;
  freshness: "fresh" | "stale";
  provider: string;
  model: string;
  prompt: string;
  result: {
    must_have: { id: string; result: string; evidence: string }[];
    good_to_have: { id: string; score: number; evidence: string }[];
    summary: string;
    missing_information: string[];
  } | null;
  analyzed_at: string;
};

export type ListingDigest = {
  status: string;
  last_attempt_status: string;
  last_attempt_error: string | null;
  freshness: "fresh" | "stale";
  property_ids: number[];
  provider: string;
  model: string;
  result: {
    overview: string;
    top_choices: {
      property_id: number;
      address: string;
      reason: string;
      strengths: string[];
      concerns: string[];
    }[];
    disqualifiers: {
      property_id: number;
      address: string;
      finding: string;
    }[];
    tradeoffs: string[];
    financial_comparison: string;
    shared_unknowns: string[];
  } | null;
  generated_at: string;
};

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public code?: string,
  ) {
    super(message);
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as {
      detail?: string | { code?: string; message?: string };
    } | null;
    const detail = body?.detail;
    throw new ApiError(
      typeof detail === "string"
        ? detail
        : (detail?.message ?? `Request failed with status ${response.status}`),
      response.status,
      typeof detail === "object" ? detail.code : undefined,
    );
  }
  return (await response.json()) as T;
}

export function loadConfig(): Promise<PublicConfig> {
  return request<PublicConfig>("/api/config");
}

export function saveUiFilters(
  filters: PropertyFilters,
): Promise<PropertyFilters> {
  return request<PropertyFilters>("/api/settings/ui-filters", {
    method: "PUT",
    body: JSON.stringify(filters),
  });
}

export function saveConfig(municipalities: string[]): Promise<PublicConfig> {
  return request<PublicConfig>("/api/config", {
    method: "PUT",
    body: JSON.stringify({ municipalities }),
  });
}

export function loadProfile(): Promise<ProfileResponse> {
  return request<ProfileResponse>("/api/profile");
}

export function saveProfile(
  profile: HouseholdProfile,
): Promise<ProfileResponse> {
  return request<ProfileResponse>("/api/profile", {
    method: "PUT",
    body: JSON.stringify(profile),
  });
}

export function calculateFinance(
  finance: HouseholdProfile["finance"],
  property: PropertyFinancialInputs,
  signal?: AbortSignal,
): Promise<FinancialResult> {
  return request<FinancialResult>("/api/finance/calculate", {
    method: "POST",
    body: JSON.stringify({ finance, property }),
    signal,
  });
}

export function loadSettings(): Promise<PrivateConfig> {
  return request<PrivateConfig>("/api/settings");
}

export function saveSettings(config: PrivateConfig): Promise<PrivateConfig> {
  return request<PrivateConfig>("/api/settings", {
    method: "PUT",
    body: JSON.stringify(config),
  });
}

export function loadSettingsYaml(): Promise<{ content: string }> {
  return request<{ content: string }>("/api/settings/yaml");
}

export function saveSettingsYaml(
  content: string,
): Promise<{ content: string }> {
  return request<{ content: string }>("/api/settings/yaml", {
    method: "PUT",
    body: JSON.stringify({ content }),
  });
}

export function loadScanStatus(): Promise<ScanStatus> {
  return request<ScanStatus>("/api/scans/status");
}

export function startScan(
  forceRefresh = false,
): Promise<{ job: ScanJob; reused_active: boolean }> {
  return request<{ job: ScanJob; reused_active: boolean }>("/api/scans", {
    method: "POST",
    body: JSON.stringify({
      force_refresh: forceRefresh,
    }),
  });
}

export function loadProperties(
  filters: PropertyFilters = {},
  signal?: AbortSignal,
): Promise<{ properties: PropertyResult[]; count: number }> {
  const parameters = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value) parameters.set(key, value);
  }
  const query = parameters.size ? `?${parameters.toString()}` : "";
  return request<{ properties: PropertyResult[]; count: number }>(
    `/api/properties${query}`,
    { signal },
  );
}

export function loadPropertyHistory(id: number): Promise<PropertyHistory> {
  return request<PropertyHistory>(`/api/properties/${id}/history`);
}

export function updatePropertyManualTags(
  id: number,
  tags: ManualPropertyTag[],
  categories: Record<ManualPropertyTag, ManualPropertyTagCategory> = {},
): Promise<PropertyResult> {
  return request<PropertyResult>(`/api/properties/${id}/manual-tags`, {
    method: "PUT",
    body: JSON.stringify(
      Object.keys(categories).length > 0 ? { tags, categories } : { tags },
    ),
  });
}

export function updatePropertyManualFacts(
  id: number,
  facts: ManualPropertyFacts,
): Promise<PropertyResult> {
  return request<PropertyResult>(`/api/properties/${id}/manual-facts`, {
    method: "PATCH",
    body: JSON.stringify(facts),
  });
}

export function loadPropertyComparables(
  id: number,
): Promise<PropertyComparables> {
  return request<PropertyComparables>(`/api/properties/${id}/comparables`);
}

export function loadMapConfig(): Promise<{
  enabled: boolean;
  available: boolean;
  api_key: string | null;
}> {
  return request("/api/maps/browser-config");
}

export function loadNearby(
  propertyIds: number[],
): Promise<{ results: NearbyResult[] }> {
  return request(`/api/maps/nearby?property_ids=${propertyIds.join(",")}`);
}

export function analyzeNearby(
  propertyIds: number[],
  forceRefresh: boolean,
): Promise<{ status: string; results: NearbyResult[] }> {
  return request("/api/maps/nearby-analyses", {
    method: "POST",
    body: JSON.stringify({
      property_ids: propertyIds,
      force_refresh: forceRefresh,
      confirm_google: true,
    }),
  });
}

export function runLLMAnalysis(
  propertyIds: number[],
  force: boolean,
  generateDigest: boolean,
): Promise<{ status: string }> {
  return request("/api/analyses", {
    method: "POST",
    body: JSON.stringify({
      property_ids: propertyIds.length ? propertyIds : null,
      force,
      generate_digest: generateDigest,
    }),
  });
}

export function loadLatestAnalysis(): Promise<{
  results: AnalysisResult[];
  digest: ListingDigest | null;
}> {
  return request("/api/analyses/latest");
}
