import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { App, formatElapsedTimestamp } from "./App";

test("formats scan age in hours and minutes", () => {
  const now = Date.parse("2026-08-05T20:45:30Z");
  expect(formatElapsedTimestamp("2026-08-05T18:30:00Z", now)).toBe(
    "2h 15m ago",
  );
  expect(formatElapsedTimestamp("2026-08-05T20:44:45Z", now)).toBe("just now");
});

const config = {
  server: { host: "localhost", port: 7004 },
  search: {
    state: "MA",
    municipalities: ["Belmont", "Newton"],
    included_property_types: ["single_family"],
    minimum_bedrooms: "0",
    minimum_bathrooms: "0",
    maximum_price: "2000000",
  },
  llm: { default_provider: "google", providers: ["google", "ollama"] },
};

const profile = {
  family: "Existing household context",
  must_have: "Three bedrooms",
  good_to_have: "Morning light",
  finance: {
    current_annual_gross_income: "100",
    minimum_future_annual_gross_income: "80",
    annual_travel_spending: "10",
    down_payment: { mode: "amount", value: "20" },
  },
};

const financialResult = {
  listing_price: "800000.00",
  down_payment: {
    authoritative_mode: "amount",
    amount: "20.00",
    percent: "0.01",
  },
  loan_amount: "799980.00",
  estimated_closing_cost: { low: "16000.00", high: "40000.00" },
  monthly_principal_and_interest: { low: "4800.00", high: "5600.00" },
  monthly_property_tax: null,
  monthly_insurance: { low: "133.33", high: "333.33" },
  monthly_hoa: null,
  monthly_maintenance: { low: "333.33", high: "1000.00" },
  known_monthly_housing_subtotal: { low: "4800.00", high: "5600.00" },
  estimated_monthly_housing_total: { low: "5266.66", high: "6933.33" },
  total_is_partial: true,
  unknown_components: ["property_tax", "hoa"],
  current_income: {
    housing_percent: { low: "63200.00", high: "83200.00" },
    monthly_gross_balance_after_housing_and_travel: {
      low: "-6925.00",
      high: "-5258.33",
    },
  },
  minimum_future_income: {
    housing_percent: { low: "79000.00", high: "104000.00" },
    monthly_gross_balance_after_housing_and_travel: {
      low: "-6927.50",
      high: "-5260.83",
    },
  },
};

const emptyScanStatus = {
  latest_attempt: null,
  last_success: null,
  active_job: null,
};

const queuedScan = {
  id: 1,
  status: "queued",
  created_at: "2026-08-05T20:00:00Z",
  started_at: null,
  completed_at: null,
  counters: {},
  error_summary: null,
  source_runs: [
    {
      source: "fixture",
      status: "queued",
      started_at: null,
      completed_at: null,
      counters: {},
      error_summary: null,
    },
  ],
};

const propertyResult = {
  id: 7,
  street_address: "1 Fixture Ln",
  unit_number: null,
  municipality: "Belmont",
  state: "MA",
  postal_code: "00000",
  latitude: "42.3000000",
  longitude: "-71.2000000",
  image_url: "https://images.example.invalid/lead.jpg",
  manual_tags: [],
  manual_values: {},
  retrieval_status: "partially_retrieved",
  missing_fields: ["hoa_monthly"],
  price: {
    display_value: "800000.00",
    source_values: [
      { source: "fixture-redfin", value: "800000.00" },
      { source: "fixture-zillow", value: "805000.00" },
    ],
    conflict: true,
    resolution_rule: "source priority: Redfin, Zillow, then others",
  },
  bedrooms: {
    display_value: "3.0",
    source_values: [{ source: "fixture-redfin", value: "3.0" }],
    conflict: false,
    resolution_rule: "source priority: Redfin, Zillow, then others",
  },
  bathrooms: {
    display_value: "2.0",
    source_values: [{ source: "fixture-redfin", value: "2.0" }],
    conflict: false,
    resolution_rule: "source priority: Redfin, Zillow, then others",
  },
  living_area_sqft: {
    display_value: "1800",
    source_values: [{ source: "fixture-redfin", value: "1800" }],
    conflict: false,
    resolution_rule: "source priority: Redfin, Zillow, then others",
  },
  lot_size_sqft: {
    display_value: "10890.00",
    source_values: [{ source: "fixture-redfin", value: "10890.00" }],
    conflict: false,
    resolution_rule: "source priority: Redfin, Zillow, then others",
  },
  property_tax_annual: {
    display_value: "9000.00",
    source_values: [{ source: "fixture-redfin", value: "9000.00" }],
    conflict: false,
    resolution_rule: "source priority: Redfin, Zillow, then others",
  },
  hoa_monthly: {
    display_value: null,
    source_values: [{ source: "fixture-redfin", value: null }],
    conflict: false,
    resolution_rule: "source priority: Redfin, Zillow, then others",
  },
  status: {
    display_value: "active",
    source_values: [{ source: "fixture-redfin", value: "active" }],
    conflict: false,
    resolution_rule: "source priority: Redfin, Zillow, then others",
  },
  property_type: {
    display_value: "single_family",
    source_values: [{ source: "fixture-redfin", value: "single_family" }],
    conflict: false,
    resolution_rule: "source priority: Redfin, Zillow, then others",
  },
  year_built: {
    display_value: "1940",
    source_values: [{ source: "fixture-redfin", value: "1940" }],
    conflict: false,
    resolution_rule: "source priority: Redfin, Zillow, then others",
  },
  sources: [
    {
      source: "fixture-redfin",
      url: "https://example.invalid/redfin",
      status: "active",
      price: "800000.00",
      bedrooms: "3.0",
      bathrooms: "2.0",
      living_area_sqft: 1800,
      lot_size_sqft: "10890.00",
      property_tax_annual: "9000.00",
      hoa_monthly: null,
      detail_error: null,
    },
    {
      source: "fixture-zillow",
      url: "https://example.invalid/zillow",
      status: "active",
      price: "805000.00",
      bedrooms: "3.0",
      bathrooms: "2.0",
      living_area_sqft: 1800,
      lot_size_sqft: "10890.00",
      property_tax_annual: "9000.00",
      hoa_monthly: null,
      detail_error: null,
    },
  ],
  conflict_fields: ["price"],
  possible_duplicate_ids: [],
  financials: financialResult,
  financial_error: null,
};

const listingDigest = {
  status: "success",
  last_attempt_status: "success",
  last_attempt_error: null,
  freshness: "fresh",
  property_ids: [7],
  provider: "google",
  model: "example-model",
  result: {
    overview: "This fixture is the current top choice.",
    top_choices: [
      {
        property_id: 7,
        address: "1 Fixture Ln",
        reason: "It is the only analyzed property.",
        strengths: ["Three bedrooms"],
        concerns: [],
      },
    ],
    disqualifiers: [],
    tradeoffs: [],
    financial_comparison: "Only one property is available.",
    shared_unknowns: ["HOA"],
  },
  generated_at: "2026-08-05T20:00:00Z",
};

afterEach(() => {
  vi.restoreAllMocks();
});

test("loads local settings and saves edited profile content", async () => {
  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/finance/calculate")) {
        return Response.json(financialResult);
      }
      if (url.endsWith("/api/scans/status")) {
        return Response.json(emptyScanStatus);
      }
      if (url.endsWith("/api/scans") && init?.method === "POST") {
        return Response.json({ job: queuedScan, reused_active: false });
      }
      if (url.endsWith("/api/analyses/latest")) {
        return Response.json({ results: [], digest: listingDigest });
      }
      if (url.endsWith("/api/analyses") && init?.method === "POST") {
        return Response.json({ status: "success" });
      }
      if (url.endsWith("/api/properties/7/history")) {
        return Response.json({
          property_id: 7,
          events: [
            {
              id: 1,
              event_type: "price_change",
              source: "redfin",
              source_url: "https://example.invalid/redfin",
              occurred_at: "2026-08-05T12:00:00Z",
              old_value: { price: "850000" },
              new_value: { price: "800000" },
            },
          ],
        });
      }
      if (url.endsWith("/api/properties/7/comparables")) {
        return Response.json({
          property_id: 7,
          comparables: [],
          expanded_to_nearby_towns: false,
          disclaimer:
            "Historical comparable sales only; this is not a price prediction.",
        });
      }
      if (
        url.endsWith("/api/properties/7/manual-tags") &&
        init?.method === "PUT"
      ) {
        const tags = JSON.parse(String(init.body)).tags;
        return Response.json({ ...propertyResult, manual_tags: tags });
      }
      if (
        url.endsWith("/api/properties/7/manual-facts") &&
        init?.method === "PATCH"
      ) {
        const facts = JSON.parse(String(init.body));
        return Response.json({
          ...propertyResult,
          manual_values: facts,
          hoa_monthly: {
            ...propertyResult.hoa_monthly,
            display_value: facts.hoa_monthly,
            source_values: [{ source: "manual", value: facts.hoa_monthly }],
          },
        });
      }
      if (url.startsWith("/api/properties")) {
        return Response.json({ properties: [propertyResult], count: 1 });
      }
      const body = url.endsWith("/api/config")
        ? config
        : { profile, exists: true, version: "v1" };
      if (init?.method === "PUT" && url.endsWith("/api/profile")) {
        return Response.json({
          profile: JSON.parse(String(init.body)),
          exists: true,
          version: "v2",
        });
      }
      return Response.json(body);
    },
  );
  vi.stubGlobal("fetch", fetchMock);

  render(<App />);

  await screen.findByLabelText("Cities / towns");
  expect(screen.getByLabelText("Cities / towns")).toHaveValue(
    "Belmont, Newton",
  );
  expect(screen.getByRole("link", { name: "Config" })).toHaveAttribute(
    "href",
    "/config",
  );
  expect(screen.getByRole("button", { name: "Force GO" })).toBeEnabled();
  const mapSelected = screen.getByRole("button", { name: "Map selected" });
  const analyze = screen.getByRole("button", { name: "Analyze" });
  const forceAll = screen.getByRole("checkbox", { name: "Force all" });
  expect(mapSelected.parentElement).toBe(analyze.parentElement);
  expect(forceAll.closest(".results-actions")).toBe(analyze.parentElement);
  expect(mapSelected.parentElement).toHaveClass("results-actions");
  expect(
    await screen.findByRole("heading", {
      name: "1 Fixture Ln（800,000）",
    }),
  ).toBeInTheDocument();
  expect(
    screen.getByAltText("Lead listing image for 1 Fixture Ln"),
  ).toHaveAttribute("src", "https://images.example.invalid/lead.jpg");
  const redfinLink = screen.getByRole("link", { name: "Redfin ↗" });
  const zillowLink = screen.getByRole("link", { name: "Zillow ↗" });
  expect(redfinLink).toHaveAttribute("href", "https://example.invalid/redfin");
  expect(zillowLink).toHaveAttribute("href", "https://example.invalid/zillow");
  expect(redfinLink.parentElement).toBe(zillowLink.parentElement);
  expect(redfinLink.parentElement).toHaveClass("listing-links");
  expect(screen.getByText("Partial")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Manual input" }));
  fireEvent.change(screen.getByLabelText("Lot size (sq ft)"), {
    target: { value: "12345" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save manual values" }));
  await waitFor(() =>
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/properties/7/manual-facts",
      expect.objectContaining({
        method: "PATCH",
        body: expect.stringContaining('"lot_size_sqft":"12345"'),
      }),
    ),
  );
  const propertyTagSummary = screen.getByText("Tags (0)");
  fireEvent.click(propertyTagSummary);
  expect(propertyTagSummary.closest("details")).toHaveAttribute("open");
  fireEvent.pointerDown(
    screen.getByRole("heading", { name: "Matching homes" }),
  );
  expect(propertyTagSummary.closest("details")).not.toHaveAttribute("open");
  fireEvent.click(propertyTagSummary);
  fireEvent.click(
    screen.getByRole("checkbox", { name: "Corner lot for 1 Fixture Ln" }),
  );
  await waitFor(() =>
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/properties/7/manual-tags",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({ tags: ["Corner lot"] }),
      }),
    ),
  );
  expect(
    screen.getByRole("checkbox", { name: "Corner lot for 1 Fixture Ln" }),
  ).toBeChecked();
  fireEvent.change(
    screen.getByRole("textbox", { name: "Add tag for 1 Fixture Ln" }),
    {
      target: { value: "临街噪音" },
    },
  );
  fireEvent.click(screen.getByRole("button", { name: "Add" }));
  await waitFor(() =>
    expect(
      screen.getByRole("checkbox", { name: "临街噪音 for 1 Fixture Ln" }),
    ).toBeChecked(),
  );
  fireEvent.click(screen.getByText("Must have tags"));
  fireEvent.click(
    screen.getByRole("checkbox", { name: "Must have tags: Corner lot" }),
  );
  expect(
    screen.getByRole("heading", { name: "1 Fixture Ln（800,000）" }),
  ).toBeInTheDocument();
  fireEvent.click(screen.getByText("Hide tags"));
  fireEvent.click(
    screen.getByRole("checkbox", { name: "Hide tags: Corner lot" }),
  );
  expect(
    screen.queryByRole("heading", { name: "1 Fixture Ln（800,000）" }),
  ).not.toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("checkbox", { name: "Hide tags: Corner lot" }),
  );
  fireEvent.click(screen.getByRole("button", { name: "LLM analysis" }));
  await waitFor(() =>
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/analyses",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          property_ids: [7],
          force: true,
          generate_digest: false,
        }),
      }),
    ),
  );
  fireEvent.click(screen.getByLabelText("Select 1 Fixture Ln"));
  expect(screen.getByText("1 shown · 1 selected")).toBeInTheDocument();
  expect(
    fetchMock.mock.calls.some(([url]) =>
      String(url).startsWith("/api/maps/browser-config"),
    ),
  ).toBe(false);
  fireEvent.click(mapSelected);
  await waitFor(() =>
    expect(
      fetchMock.mock.calls.some(([url]) =>
        String(url).startsWith("/api/maps/browser-config"),
      ),
    ).toBe(true),
  );
  fireEvent.click(screen.getByRole("button", { name: "Close" }));
  expect(screen.getByText("Source conflict: price")).toBeInTheDocument();
  expect(screen.getByText("0.25 ac / 10,890 sq ft")).toBeInTheDocument();
  expect(screen.getByText("Estimated per month")).toBeInTheDocument();
  expect(
    screen.getByRole("heading", { name: "Listing digest" }),
  ).toBeInTheDocument();
  expect(screen.getByText(listingDigest.result.overview)).toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("button", { name: "History & sold comparables" }),
  );
  expect(await screen.findByText("price change")).toBeInTheDocument();
  expect(screen.getByText("$850,000 → $800,000")).toBeInTheDocument();
  expect(screen.getByText(/not a price prediction/)).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Sort"), {
    target: { value: "price_desc" },
  });
  await waitFor(() =>
    expect(
      fetchMock.mock.calls.some(([url]) =>
        String(url).includes("sort=price_desc"),
      ),
    ).toBe(true),
  );
  await waitFor(() =>
    expect(screen.getByLabelText(/Percentage/)).toHaveValue(0.01),
  );
  expect(
    screen.getByText("Partial estimated monthly housing cost"),
  ).toBeInTheDocument();
  expect(
    screen.getByText(/Excludes unknown: property_tax, hoa/),
  ).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "GO" }));
  await waitFor(() =>
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/scans",
      expect.objectContaining({ method: "POST" }),
    ),
  );
});
