import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../..");

describe("web release integration", () => {
  it("keeps the browser format allowlist aligned with the API", () => {
    const source = readFileSync(resolve(projectRoot, "src/main.tsx"), "utf8");

    for (const extension of [".shp", ".geojson", ".json", ".gpkg", ".fgb", ".parquet"]) {
      expect(source).toContain(extension);
    }
    expect(source).toContain('request("/api/geometry/validate"');
    expect(source).toContain('request("/api/geometry/repair"');
    expect(source).toContain("Preview topology repair");
    expect(source).toContain("Apply preview");
    expect(source).toContain("Undo");
    expect(source).toContain("AbortController");
  });

  it("ships complete discovery and social metadata", () => {
    const html = readFileSync(resolve(projectRoot, "index.html"), "utf8");

    expect(html).toContain('rel="canonical"');
    expect(html).toContain('rel="icon"');
    expect(html).toContain('property="og:title"');
    expect(html).toContain('name="twitter:card"');
    expect(readFileSync(resolve(projectRoot, "public/robots.txt"), "utf8")).toContain(
      "sitemap.xml",
    );
    expect(readFileSync(resolve(projectRoot, "public/sitemap.xml"), "utf8")).toContain(
      "https://geoqc.github.io/geoqc/",
    );
  });
});