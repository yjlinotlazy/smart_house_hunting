import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { ConfigPage } from "./ConfigPage";

const privateConfig = {
  server: { host: "localhost", port: 7004 },
  profile_file: "private/profile.yaml",
  search: {
    state: "MA",
    municipalities: ["Belmont", "Newton"],
    included_property_types: ["single_family"],
    minimum_bedrooms: "0",
    minimum_bathrooms: "0",
    maximum_price: "2000000",
  },
  finance: {
    mortgage_years: 30,
    default_down_payment_percent: "20",
    annual_interest_rate: { low: "0.06", high: "0.075" },
    annual_insurance_rate: { low: "0.002", high: "0.005" },
    annual_maintenance_rate: { low: "0.005", high: "0.015" },
    closing_cost_rate: { low: "0.02", high: "0.05" },
  },
  sources: {
    redfin: { enabled: true },
    zillow: { enabled: true },
    realtor: { enabled: true },
  },
  llm: {
    default_provider: "google",
    timeout_seconds: 180,
    max_concurrency: 2,
    providers: {
      google: {
        base_url: "https://example.invalid/google",
        api_key_env: "GOOGLE_API_KEY",
        model: "example-model",
      },
    },
  },
  maps: {
    enabled: false,
    demo_api_key_env: "GOOGLE_MAPS_API_KEY",
    browser_api_key_env: "GOOGLE_MAPS_BROWSER_API_KEY",
    backend_api_key_env: "GOOGLE_MAPS_BACKEND_API_KEY",
    nearby_search_radius_meters: 2500,
    cache_days: 14,
  },
  logging: {
    level: "INFO",
    include_profile_content: false,
    retain_source_payloads: false,
  },
};

afterEach(() => {
  vi.restoreAllMocks();
});

test("edits config in form and YAML modes", async () => {
  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/settings/yaml")) {
        return Response.json({
          content:
            init?.method === "PUT"
              ? JSON.parse(String(init.body)).content
              : "server:\n  port: 7004\n",
        });
      }
      return Response.json(
        init?.method === "PUT" ? JSON.parse(String(init.body)) : privateConfig,
      );
    },
  );
  vi.stubGlobal("fetch", fetchMock);

  render(<ConfigPage />);
  expect(await screen.findByLabelText("Single family")).toBeChecked();
  expect(screen.getByLabelText("Condo")).not.toBeChecked();
  fireEvent.click(screen.getByLabelText("Condo"));
  fireEvent.click(screen.getByRole("button", { name: "Save config" }));

  await waitFor(() =>
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/settings",
      expect.objectContaining({ method: "PUT" }),
    ),
  );
  await waitFor(() =>
    expect(
      screen.getAllByText("Config validated and saved locally.").length,
    ).toBeGreaterThan(0),
  );

  fireEvent.click(screen.getByRole("button", { name: "YAML" }));
  const editor = screen.getByLabelText("Config contents");
  fireEvent.change(editor, { target: { value: "server:\n  port: 7005\n" } });
  fireEvent.click(screen.getByRole("button", { name: "Save config" }));

  await waitFor(() =>
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/settings/yaml",
      expect.objectContaining({ method: "PUT" }),
    ),
  );
});
