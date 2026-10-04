import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../main";

const validation = {
  filename: "roads.geojson",
  layer: null,
  feature_count: 2,
  valid_feature_count: 2,
  invalid_feature_count: 0,
  issue_counts: {},
  findings: [],
  findings_truncated: false,
};

const repair = {
  filename: "roads.geojson",
  layer: null,
  mode: "preview",
  total: 1,
  repaired: 1,
  unchanged: 0,
  failed: 0,
  action_counts: { duplicate_vertex: 1 },
  total_area_delta: 0,
  max_shape_shift: 0,
  findings: [{
    feature_index: 0,
    status: "repaired",
    geometry_type: "LineString",
    actions: [{ issue_type: "duplicate_vertex", strategy: "deduplicate", detail: "Removed duplicate." }],
    area_before: 0,
    area_after: 0,
    shape_shift: 0,
    before_wkt: "LINESTRING (0 0, 0 0, 1 1)",
    after_wkt: "LINESTRING (0 0, 1 1)",
  }],
  findings_truncated: false,
  original_geojson: '{"type":"FeatureCollection","features":[]}',
  repaired_geojson: '{"type":"FeatureCollection","features":[]}',
};

function response(body: object, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: new Headers({ "content-type": "application/json" }),
    json: async () => body,
  } as Response;
}

async function uploadDataset(user: ReturnType<typeof userEvent.setup>): Promise<void> {
  const file = new File(["{}"], "roads.geojson", { type: "application/geo+json" });
  await user.upload(screen.getByLabelText(/drag a dataset/i), file);
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
  vi.stubGlobal("URL", {
    ...URL,
    createObjectURL: vi.fn(() => "blob:geoqc"),
    revokeObjectURL: vi.fn(),
  });
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
  window.matchMedia = vi.fn().mockReturnValue({ matches: false });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

describe("GeoQC browser workflow", () => {
  it("selects a dataset, sends it to validation, and renders the successful empty state", async () => {
    const user = userEvent.setup();
    vi.mocked(fetch).mockResolvedValue(response(validation));
    render(<App />);

    expect(screen.getByRole("button", { name: "Run validation" }).hasAttribute("disabled")).toBe(true);
    await uploadDataset(user);
    expect(screen.getByText("roads.geojson")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Run validation" }).hasAttribute("disabled")).toBe(false);

    await user.click(screen.getByRole("button", { name: "Run validation" }));

    expect(await screen.findByText("Passed")).toBeTruthy();
    expect(screen.getByText("No geometry issues were found in this dataset.")).toBeTruthy();
    expect(fetch).toHaveBeenCalledWith(
      "/api/geometry/validate",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("shows loading state while validation is pending", async () => {
    const user = userEvent.setup();
    vi.mocked(fetch).mockReturnValue(new Promise<Response>(() => undefined));
    render(<App />);
    await uploadDataset(user);

    await user.click(screen.getByRole("button", { name: "Run validation" }));

    expect(screen.getByText(/Reading and validating the dataset/)).toBeTruthy();
    expect(screen.getByRole("button", { name: /Validating/ }).hasAttribute("disabled")).toBe(true);
  });

  it("renders an actionable API validation error", async () => {
    const user = userEvent.setup();
    vi.mocked(fetch).mockResolvedValue(response({ detail: "Dataset geometry is invalid." }, 422));
    render(<App />);
    await uploadDataset(user);

    await user.click(screen.getByRole("button", { name: "Run validation" }));

    expect((await screen.findByRole("alert")).textContent).toContain("Dataset geometry is invalid.");
  });

  it("previews a repair, applies it, and undoes the applied preview", async () => {
    const user = userEvent.setup();
    vi.mocked(fetch).mockResolvedValue(response(repair));
    render(<App />);
    await uploadDataset(user);

    await user.click(screen.getByRole("button", { name: "Preview topology repair" }));
    expect(await screen.findByRole("region", { name: "Topology repair preview" })).toBeTruthy();
    expect(screen.getByText("Non-destructive preview")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "Apply preview" }));
    expect(screen.getByText(/Applied in this browser session/)).toBeTruthy();
    const undoButtons = screen.getAllByRole("button", { name: "Undo" });
    await user.click(undoButtons[0]);
    expect(screen.getByText("Non-destructive preview")).toBeTruthy();
  });

  it("downloads validation JSON, a repair report, and applied repaired data", async () => {
    const user = userEvent.setup();
    vi.mocked(fetch)
      .mockResolvedValueOnce(response(validation))
      .mockResolvedValueOnce(response(repair));
    render(<App />);
    await uploadDataset(user);

    await user.click(screen.getByRole("button", { name: "Run validation" }));
    await user.click(await screen.findByRole("button", { name: "Download JSON" }));
    await user.click(screen.getByRole("button", { name: "Preview topology repair" }));
    await user.click(await screen.findByRole("button", { name: "Download report" }));
    await user.click(screen.getByRole("button", { name: "Apply preview" }));
    await user.click(screen.getByRole("button", { name: "Download repaired GeoJSON" }));

    await waitFor(() => expect(URL.createObjectURL).toHaveBeenCalledTimes(3));
    expect(HTMLAnchorElement.prototype.click).toHaveBeenCalledTimes(3);
  });

  it("rejects an incomplete Shapefile component selection without a request", async () => {
    render(<App />);
    const input = screen.getByLabelText(/drag a dataset/i);
    fireEvent.change(input, { target: { files: [new File(["x"], "roads.shp")] } });

    expect(screen.getByRole("alert").textContent).toContain("complete Shapefile component set");
    expect(fetch).not.toHaveBeenCalled();
  });
});
