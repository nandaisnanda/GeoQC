# Phase 0 dead and duplicate code audit

Task T2 of the Phase 0 plan. This document records one verdict per module for the
families that overlap, plus the evidence behind every verdict. It is the input to
T3 (consolidation) and a constraint on T4 (typed rule contract).

| Field | Value |
| --- | --- |
| Commit audited | `85227bd` |
| Branch | `chore/t1-dev-setup` |
| Audit date | 2026-11-02 |
| Source size | 142 modules / 13,483 LOC under `src/geoqc` |
| Test size | 94 files / 7,012 LOC under `tests` |
| Public API surface | 91 names in `geoqc.__all__` |

## 1. Scope and method

The audit covers the module families that plausibly duplicate each other: the
topology rules family, the dataset workflow family, the reporting family, the
spatial-intelligence and enterprise-spatial adapters, and the compatibility
facades left behind by the P0 to canonical workflow migration described in
[ADR-0005](../adr/0005-canonical-dataset-audit.md).

For every module the audit records:

- **LOC** — physical lines, from `Get-Content | Measure-Object -Line`.
- **Cover** — statement and branch coverage from the `.coverage` data file
  regenerated on 2026-11-02 15:10.
- **Callers (src)** — every importing file inside `src/geoqc`, as `file:line`.
  Matching was done on dotted module paths so a hit is a real import, never a
  substring of a docstring.
- **Tests** — test files that import the module by path. A test that reaches the
  module only through the `geoqc` package namespace is called out as *indirect*.

Two method notes matter for reproducing the numbers:

1. `coverage report --include=` with a comma-separated list only honours the
   last pattern in this environment. The full report was therefore generated and
   filtered afterwards, instead of relying on the `--include` filter.
2. Repository-wide regex search over the tree times out because of
   `node_modules` and `.venv`. Searches were scoped to `src`, `tests`, `tools`,
   `examples`, and `docs`. The exact commands are in the
   [evidence appendix](#14-evidence-appendix).

Coverage is a duplication signal here, not a quality gate. A module at 100%
coverage can still be dead: `application/streaming/processor.py` is fully
exercised by no test at all and sits at 63.64% precisely because nothing calls
it.

## 2. Verdict legend

| Verdict | Meaning | Behaviour change allowed? |
| --- | --- | --- |
| **keep** | Stays as is. Maybe a test gap to close. | No |
| **keep + rename** | Content is right, the name misleads. Internal importers only. | Import paths only |
| **merge** | Module boundary buys nothing; fold into the caller. | Import paths only |
| **delete facade** | Pure re-export module. Repoint importers to the real modules. | Import paths only |
| **deprecate** | Keep working, warn, remove on a published schedule. | None yet |
| **delete** | Unreachable or superseded. Remove with the batch that owns it. | Removal |

Two rules apply to every verdict:

1. **No public name is removed in T3.** `geoqc.__all__` has 91 entries and must
   still have 91 entries when T3 lands. Renames and facade removals are
   internal, or they come with a shim.
2. **No rule module is collapsed.** T4 replaces the ad-hoc check functions with
   a typed `Rule`/`Finding` contract that also becomes the tool schema for the
   AI layer and the QGIS plugin. Collapsing `topology_geometry_rules`,
   `topology_network_rules`, and `topology_relation_rules` now would force that
   migration twice.

## 3. Summary

Of 36 modules audited:

| Verdict | Count | Modules |
| --- | --- | --- |
| keep | 24 | rules family (8), dataset family (6), reporting (4), spatial adapters and models (6) |
| keep + rename | 2 | `topology_rules_v2`, `legacy` |
| merge | 1 | `dataset_scoring` |
| delete facade | 2 | `gis/quality_workflow`, `domain/models/quality_workflow` |
| deprecate | 1 | `dataset_compat` |
| delete | 3 | `application/services/spatial_intelligence`, `application/ports/spatial_intelligence`, `application/streaming/processor` |
| keep, split deferred to T4 | 1 | `finding_builders` |
| keep, dedupe | 2 | `enterprise_spatial_map`, `spatial_intelligence_map` |

Counted by module, the rows sum to 36. The dead `DatasetAuditReport` shim in
[section 10](#10-dead-code) is a symbol, not a module, so it is not in this
table.

The single most important finding is not a duplicate module. It is that the
`Rule`/`RuleEngine` contract in `domain/rules` is **never instantiated in
production code** — `RuleEngine(` appears only in
`tests/unit/domain/rules/test_engine.py` and
`tests/property/test_checks_never_crash.py`. The canonical audit path
(`dataset_audit` to `finding_builders`) hardcodes its checks and never touches
the engine. That gap is exactly what T4 closes, and it is why the "v2" naming
in the topology family is a real hazard rather than cosmetic.

## 4. Topology family

The topology family is a three-layer split: a service, a dispatcher, and three
rule groups behind a shared helper module. It is correctly factored. The only
defect is the name `topology_rules_v2`, which implies a `topology_rules_v1` that
never existed and has no counterpart in git history.

| Module | LOC | Cover | Callers (src) | Tests | Verdict |
| --- | --- | --- | --- | --- | --- |
| `gis/topology_service.py` | 69 | 86.89% (4 stmts) | `gis/quality_workflow.py:7` | `test_area_units.py:12` | **keep** |
| `gis/topology_rules_v2.py` | 62 | 96.43% | `gis/topology_service.py:16` | none | **keep + rename** |
| `gis/topology_geometry_rules.py` | 127 | 100% | `gis/topology_rules_v2.py:8` | none | **keep** |
| `gis/topology_network_rules.py` | 139 | 98.13% | `gis/topology_rules_v2.py:15` | none | **keep** |
| `gis/topology_relation_rules.py` | 164 | 95.16% | `gis/topology_rules_v2.py:20` | none | **keep** |
| `gis/topology_rule_helpers.py` | 104 | 100% | `topology_geometry_rules.py:14`, `topology_network_rules.py:15`, `topology_relation_rules.py:22` | none | **keep** |
| `gis/shapely_topology_repairer.py` | 323 | 87.87% (23 stmts) | `public_geometry.py:15` | `test_shapely_topology_repairer.py` | **keep** |
| `domain/models/topology.py` | 251 | 90.74% | many | `test_dataset_audit.py`, `test_topology_repair.py` | **keep** |
| `domain/models/topology_repair.py` | 177 | 98.35% | many | `test_topology_repair.py` | **keep** |

Rationale:

- `topology_service.evaluate_topology_rules` is on the live canonical path:
  `dataset_audit.py:40` imports it through the `quality_workflow` facade, and
  `dataset_audit.py:42` calls it. It is the entry point every audit uses. Its
  4 uncovered statements are the rule-selection branches; a direct unit test is
  worth adding in T3.
- `topology_rules_v2.py` has exactly one importer, so renaming it to
  `topology_rule_dispatch.py` costs one edited import and needs no shim. The
  name is the only thing wrong with it: it holds the `TopologyRuleType` to
  implementation dispatch table.
- The three rule modules and the helper are the natural seams for T4. Each rule
  module already groups by context (geometry-only, network, cross-layer), which
  maps onto the rule categories the typed contract needs. Splitting or merging
  them now would be undone within one task.
- `shapely_topology_repairer.py` is the largest repair adapter at 323 LOC with
  23 uncovered statements — the weakest coverage on the repair path. It is not
  dead (public `repair_geometries` reaches it), but T3 should add tests before
  any refactor touches it.
- The family has **no duplication**: `topology_rule_helpers.py` is imported by
  all three rule modules and is the only shared code, which is the correct
  direction of dependency.

## 5. Dataset workflow family

This family is the product of splitting one large module into parts. The split
is sound, but it left two problems: a pure re-export facade that shadows the
real module names, and an 8-statement module that only exists because the split
happened.

| Module | LOC | Cover | Callers (src) | Tests | Verdict |
| --- | --- | --- | --- | --- | --- |
| `gis/dataset_audit.py` | 294 | 95.16% | `dataset_compat.py:12`, `dataset_workflow.py:3-5`, `cli/delivery.py:20`, `tools/benchmark/run.py:17`, `tools/validation/run_check.py:15` | `test_checks_never_crash.py:40`, `test_road_endpoint_merge.py:12`, `test_road_endpoint_messages.py:10` | **keep** |
| `gis/dataset_checks.py` | 354 | 97.93% | `dataset_audit.py:22`, `cli/main.py:43` | `test_checks_never_crash.py:41` | **keep** |
| `gis/dataset_scoring.py` | 37 | 100% | `dataset_audit.py:35` | none | **merge** |
| `gis/dataset_values.py` | 40 | 78.43% (6 stmts) | `dataset_audit.py:36`, `dataset_checks.py:27` | none | **keep** |
| `gis/dataset_export.py` | 99 | 93.88% | `dataset_audit.py:34`, `dataset_workflow.py:8-9`, `profile_loading.py:18` | none | **keep** |
| `gis/dataset_compat.py` | 54 | 83.33% | `dataset_workflow.py:6-7` | none | **deprecate** |
| `gis/dataset_workflow.py` | 14 | 100% | `parallel_audit.py:14`, `geoqc/__init__.py:68` | none | **keep** |
| `domain/models/dataset_audit.py` | 152 | 94.69% | `domain/models/__init__.py:30`, `audit_result.py:8` | `test_dataset_audit.py` | **keep**+[§10](#10-dead-code) |

Rationale:

- `dataset_audit.py` is the canonical orchestrator and the right home for the
  workflow. It is imported by the CLI, two tool scripts, and the compatibility
  facades. Keep.
- `dataset_checks.py` at 354 LOC is the largest module in the family and holds
  the private check helpers (`_crs_issues`, `_attribute_issues`,
  `_geometry_type_issues`, and friends) that `dataset_audit.py:22` pulls in. It
  is **not** a duplicate of `finding_builders.py`: `dataset_checks` decides
  *whether* a check runs and how it is scored, `finding_builders` decides *what*
  a finding looks like. The naming does not make that distinction obvious, which
  is worth a module docstring in T3.
- `dataset_scoring.py` is 37 LOC exposing one private function, `_rebuild_result`,
  whose only job is to deduplicate and re-score a result after merging. Eight
  statements do not justify a module. Fold it into `dataset_audit.py`.
- `dataset_values.py` has the lowest coverage in the family at 78.43%. The 6
  missed statements are the attribute-coercion fallbacks. It is genuinely
  shared (two importers), so keep it and add tests for the fallbacks.
- `dataset_export.py` creates a layering smell: it is an *export* module, yet
  `profile_loading.py:18` imports it to reach `dump_quality_profile`. Profile
  loading should not depend on the export adapter. T6 should move
  `dump_quality_profile` next to the profile schema and reverse that arrow.
- `dataset_workflow.py` is a 14-line facade, but unlike the two `quality_workflow`
  facades it is documented as the stable import surface
  ([quality-workflow.md](../quality-workflow.md)) and is imported by
  `parallel_audit.py`. Keep it.
- `dataset_compat.py` already emits `DeprecationWarning` and both of its names
  are still in `geoqc.__all__`, so removing it in T3 would break the 91-name
  surface. Deprecate on a schedule instead.
- `run_quality_workflow()` in `dataset_compat.py` re-implements orchestration
  that already exists as the exporter methods on `DatasetAuditResult`. That is
  the duplication to retire, and it retires with the deprecation.

## 6. Reporting family

| Module | LOC | Cover | Callers (src) | Tests | Verdict |
| --- | --- | --- | --- | --- | --- |
| `reporting/benchmark_report.py` | 166 | 97.06% | `reporting/__init__.py:5`, `cli/main.py:56` | `test_benchmark_report.py` (indirect) | **keep** |
| `reporting/html_report.py` | 36 | 100% | `reporting/__init__.py:15,37`, `dataset_export.py:92` | `test_html_report.py`, `test_impact.py` (indirect) | **keep** |
| `reporting/interactive_map.py` | 121 | 95.74% | `reporting/__init__.py:16,41`, `html_report.py:10` | `test_interactive_map.py` (indirect) | **keep** |
| `reporting/enterprise_spatial_map.py` | 100 | 100% | none in `src` | `test_enterprise_spatial_map.py:14` | **keep, dedupe** |
| `reporting/spatial_intelligence_map.py` | 90 | 95.08% | none in `src` | `test_spatial_intelligence_map.py:11` | **keep, dedupe** |
| `public_reporting.py` | 66 | 81.25% (5 stmts) | `geoqc/__init__.py:95`, `dataset_export.py:91` | none | **keep** |

Rationale:

- `reporting/__init__.py` uses a `__getattr__` lazy import so that
  `BenchmarkFormat` and `write_benchmark_report` stay importable without the
  optional `report` extra (jinja2/folium). That design is deliberate and
  documented in the module docstring; none of the three renderers should be
  merged, because each pulls a different optional dependency.
- The two spatial map modules are the only real duplication in this family; see
  [section 9](#9-duplication-findings) item 1.
- Both map modules have **no importer inside `src`**. They are reached only from
  `public_reporting`/`public_spatial`, which are the public entry points, and
  from their own tests. They are not dead — they are public-API-only adapters —
  but this is why the duplication was never noticed: nothing internal forces the
  two implementations to converge.
- `public_reporting.py` is at 81.25% with 5 missed statements, all in the
  CRS-less and `CRSError` fallbacks. Those are the error paths a user actually
  hits with unprojected data, so T3 should test them.
- `benchmark_report.py` imports cleanly from the CLI (`cli/main.py:56`), so its
  format inference is exercised end to end by the benchmark CLI tests.

## 7. Spatial intelligence and enterprise family

This family contains the clearest dead weight in the repository, and also the
distinction that makes it easy to delete the wrong thing: the **engines** are on
the live path, the **application service and port around them** are not.

| Module | LOC | Cover | Callers (src) | Tests | Verdict |
| --- | --- | --- | --- | --- | --- |
| `gis/shapely_spatial_intelligence.py` | 13 | 100% | `finding_builders.py:26`, `road_dataset_repair.py:17`, `public_spatial.py:37` | `test_shapely_spatial_intelligence.py:16` | **keep** |
| `gis/shapely_enterprise_spatial.py` | 303 | 87.12% (21 stmts) | `public_spatial.py:32` | `test_enterprise_spatial.py` (indirect) | **keep** |
| `application/services/repair_recommendation.py` | 41 | 100% | `public_spatial.py:7` | none | **keep** |
| `application/services/spatial_intelligence.py` | 46 | 100% | **none** | `test_spatial_intelligence_service.py` | **delete** |
| `application/ports/spatial_intelligence.py` | 29 | 100% | `services/spatial_intelligence.py` only | none | **delete** |
| `public_spatial.py` | 117 | 100% | `geoqc/__init__.py:96` | none | **keep** |
| `domain/models/spatial_intelligence.py` | 246 | 97.34% | many | `test_spatial_intelligence.py` | **keep** |
| `domain/models/enterprise_spatial.py` | 190 | 86.47% | `shapely_enterprise_spatial.py` | `test_enterprise_spatial.py` | **keep** |

Rationale:

- `shapely_spatial_intelligence.py` is a 13-line adapter and is imported by
  `finding_builders.py:26`, so spatial intelligence already runs inside every
  dataset audit. The engine layer is genuinely used.
- `application/services/spatial_intelligence.py` has **zero importers in
  `src`**. `public_spatial.py:46-54` constructs the same engine set directly
  instead of going through the service. So the service is a second, unexercised
  way to do what the public API already does, and its 100% coverage comes
  entirely from its own unit test — coverage of a code path no product reaches.
- `application/ports/spatial_intelligence.py` exists only to type the service's
  constructor. Delete both together; keeping the port after removing the service
  would leave an interface with no implementation.
- `repair_recommendation.py` is the counter-example and must be kept: it is
  small, but `public_spatial.py:7` uses it, so it is on the live path. Do not
  sweep it up with the service deletion because it sits in the same package.
- `shapely_enterprise_spatial.py` at 303 LOC and 86.47% has 21 uncovered
  statements, mostly in the shape-similarity branches. It is reached from
  `public_spatial.py:32`, so it is live; the coverage gap is a T3 test task, not
  a deletion.
- The enterprise models (`domain/models/enterprise_spatial.py` at 86.47%) are
  the weaker of the two model modules. They are documented in
  [enterprise-spatial.md](../enterprise-spatial.md), so they stay in Phase 0, but
  they should not grow before T4 fixes the finding contract.

## 8. Compatibility facades, legacy arguments, and the rule-engine adapter

| Module | LOC | Cover | Callers (src) | Tests | Verdict |
| --- | --- | --- | --- | --- | --- |
| `gis/legacy.py` | 56 | 92.59% (1 stmt) | `dataset_audit.py:38` | none | **keep + rename** |
| `gis/quality_workflow.py` | 13 | 100% | 4 in `src`, listed below | 3 (indirect) | **delete facade** |
| `domain/models/quality_workflow.py` | 57 | 100% | 9 in `src`, listed below | none | **delete facade** |
| `application/streaming/processor.py` | 18 | 63.64% | **none** | none | **delete** |
| `gis/finding_builders.py` | 534 | 96.45% | `audit_service.py:11`, `dataset_audit.py:37`, `topology_service.py:8` | `test_area_units.py:7` | **keep, split in T4** |

### 8.1 `gis/quality_workflow.py` is a shim over five real modules

Its entire body is five re-exports and an `__all__`:

- `score_issues` from `application/scoring_service.py`
- `audit_geometries` from `gis/audit_service.py`
- `assess_crs` from `gis/crs_analysis.py`
- `issues_to_geodataframe` from `gis/issue_serializer.py`
- `evaluate_topology_rules` from `gis/topology_service.py`

Importers in `src`: `gis/dataset_audit.py:40`, `gis/dataset_export.py:17`,
`gis/dataset_scoring.py:10`, and `geoqc/__init__.py:81`. Tests reach it through
the package namespace at three call sites.

Deleting it is a mechanical 4-file repoint. The subtle part is
`geoqc/__init__.py:81`: the public package currently imports these five names
*through* the facade. Repointing means importing each name from its real module.
The exported names do not change, so `geoqc.__all__` is untouched, but the
`geoqc/__init__.py` diff must be reviewed carefully because it is the one file
where a mistake becomes a public API break.

### 8.2 `domain/models/quality_workflow.py` is a second shim, same disease

It re-exports from four real modules — `audit_result`, `quality_profile`,
`scoring`, and `topology`. Its nine importers are all internal:
`domain/models/dataset_audit.py:14,155`, `domain/models/__init__.py:56`,
`gis/dataset_export.py:15`, and five topology modules
(`topology_geometry_rules.py:10`, `topology_network_rules.py:9`,
`topology_relation_rules.py:11`, `topology_rules_v2.py:7`,
`topology_rule_helpers.py:10`). No test imports it by path.

Two modules in two different layers, both named `quality_workflow`, both pure
re-export, is the single largest source of "which one do I import?" confusion in
the codebase. Deleting the domain-side facade costs nine mechanical import
edits and removes the collision outright.

The earlier hypothesis for this module — that it was the home of
`AuditResultExporter` — was **wrong**. `AuditResultExporter` is defined in
`domain/models/audit_result.py:24`; the facade merely re-exports it. Renaming
the facade to `audit_export` would have preserved the confusion with a new name,
so the verdict is delete rather than rename.

### 8.3 `gis/legacy.py` is not legacy, and the name is actively misleading

The file is the live deprecation funnel for the `checks=` and `schema=`
keyword arguments: `profile_from_legacy_arguments()` translates those into a
`QualityProfile` and is called from `dataset_audit.py:38` on the canonical path.
It has one uncovered statement, the branch that warns only once.

Deleting it is not an option while the deprecated arguments are supported, and
renaming it to `deprecated_audit_arguments.py` costs one edited import. A
developer who reads "legacy" as "safe to delete" is the exact failure mode this
audit exists to prevent, so the rename is worth the diff.

### 8.4 `application/streaming/processor.py` is unreachable

`RuleEngineChunkProcessor` is referenced only by its own module and by
`application/streaming/__init__.py:14,20` (a re-export). Nothing constructs it.
Its 63.64% coverage is a symptom: four of eleven statements are never executed
because the class is never used. The streaming audit path uses
`GeometryChunkProcessor` instead, and `automatic_geometry_engine` selects it
directly.

This is the clearest evidence for the T4 finding in
[section 3](#3-summary): `RuleEngine` itself is instantiated only in
`tests/unit/domain/rules/test_engine.py` and in
`tests/property/test_checks_never_crash.py:471-473`. The adapter was written
ahead of the wiring and the wiring never happened.

Recommendation: delete the adapter now, and let T4 re-add a typed chunk adapter
once `Rule` has stable IDs and the engine is actually composed into the
production path. Keeping it means maintaining a class whose only consumer is its
own import statement.

### 8.5 `gis/finding_builders.py` — keep, but it is T4's main obstacle

At 534 LOC it is the largest module in `src/geoqc`, and it has three importers
across two layers (`audit_service.py:11`, `dataset_audit.py:37`,
`topology_service.py:8`). It is not a grab-bag by accident — it is the single
place where a geometry check becomes a user-visible finding, so everything
converges there.

That is also why it cannot be split in T3. Splitting it now, before the typed
`Finding` contract exists, would produce three modules with the same implicit
contract. T4 should rewrite it to emit typed `Finding` objects with stable rule
IDs and split along rule category at the same time.

Rationale for keeping every facade name in the public surface during T3: the
release-notes promise is that only names exported directly from `geoqc` are
stable during `0.x`. All five facade names *are* exported from
`geoqc/__init__.py:81`, so they are public. Deleting the module is safe;
deleting the names is not.

## 9. Duplication findings

Six distinct duplications. Each is listed with the mechanism, the evidence, and
the task that retires it.

### 9.1 Geometry-map helpers duplicated across two folium modules

`reporting/enterprise_spatial_map.py` and `reporting/spatial_intelligence_map.py`
both define a module-private `_geojson` converter and a `_map` builder. The
`_geojson` bodies are identical — the only difference is the parameter name. The
`_map` functions follow the same construction sequence (a `folium.Map` on a
dark tile layer, a `GeoJson` layer, then `fit_bounds`) and differ only in the
layer label and colour.

Neither module imports the other in `src`, so the compiler cannot catch the
divergence, and the copies have already drifted in naming. Retired by **T3 PR C**.

### 9.2 An application service parallel to the public entry point

`application/services/spatial_intelligence.py` (46 LOC, 23 statements) wraps the
spatial engines in a service object with a port behind it. `public_spatial.py:46-54`
builds the same engine set directly and never calls the service. Two ways to do
one thing, and only one is reachable.

The tell is the coverage split: the service shows 100% because
`test_spatial_intelligence_service.py` drives it directly, while `public_spatial.py`
also shows 100% because it has its own path. Two 100% modules, one product path.

Retired by **T3 PR A**.

### 9.3 Two `quality_workflow` modules

`gis/quality_workflow.py` (re-export of five infrastructure/application names)
and `domain/models/quality_workflow.py` (re-export of four domain model modules)
share a name and nothing else. Importing the wrong one fails at runtime with an
`ImportError`, not at review time. Detailed in
[sections 8.1 and 8.2](#81-gisqualityworkflowpy-is-a-shim-over-five-real-modules).
Retired by **T3 PR A**.

### 9.4 `dataset_compat.run_quality_workflow` re-implements orchestration

`run_quality_workflow()` performs the audit, then writes artifacts by calling
`write_audit_report`/`write_issue_layers` directly. The canonical
`DatasetAuditResult` already exposes `to_json`, `to_html`, and `write_findings`
for the same files. Two orchestration paths over one result type, one of them
deprecated in name only (it emits `DeprecationWarning` but still ships).

Retired by **T3 PR A** (mark the surface, add the shim test) and removal in
0.3.0 per [section 13](#13-open-decisions).

### 9.5 Double re-export indirection from the public package

`geoqc/__init__.py:81` imports five names *from* `gis/quality_workflow.py`,
which imports them from their real modules. `domain/models/__init__.py:56`
does the same through `domain/models/quality_workflow.py`. So a name like
`evaluate_topology_rules` has three hops before it resolves, and the middle hop
adds no behaviour.

This is the reason both facades survived: nothing looks broken, because the
indirection is invisible at every call site. Retired by **T3 PR A**.

### 9.6 Two serialization paths off `DatasetAuditResult`

- **Canonical**: `to_json`/`to_html`/`write_findings` →
  `_require_exporter()` (`audit_result.py:175`) → `AuditResultExporter` protocol
  → `dataset_export._ResultExporter`, injected by `audit_path` at
  `dataset_audit.py:275`.
- **Legacy**: `dataset_compat.run_quality_workflow` →
  `dataset_export.write_audit_report` / `write_issue_layers` directly.

Both end in `dataset_export`, but one goes through an injected protocol and the
other through module-level free functions. The protocol exists so that domain
does not import infrastructure, which is correct, but the injection has a side
effect worth recording: a result from `audit_geodataframe()` has
`_exporter=None`, so calling `to_json()` on it raises
`RuntimeError("Exports require a file audit result returned by geoqc.audit_dataset()")`.
One of the seven public audit entry points cannot export its own result.

The fix belongs to **T6** (single serialization path and documented public API),
not T3; T3 only records it and must not make the gap wider.

## 10. Dead code

Exactly one dead symbol was found outside the deleted modules above, and it
matters because it is the kind of thing a coverage report hides.

### 10.1 `DatasetAuditReport` in `domain/models/dataset_audit.py:143`

`DatasetAuditReport` (N802-suppressed, carrying a `DeprecationWarning` telling
callers to use `audit_dataset()`) is:

- defined at `domain/models/dataset_audit.py:143`;
- imported at `domain/models/__init__.py:35`;
- **absent** from `domain/models.__all__` (which starts at line 93);
- **absent** from `geoqc/__init__.py` (no reference at all);
- referenced by no test, no tool, and no document.

So it cannot be reached by `from geoqc import ...`, is not advertised, and has
no caller. Its only purpose was the P0-to-canonical transition, which is the
same transition `dataset_compat` already covers on the public side.

Verdict: **delete with the `dataset_compat` removal in 0.3.0**, not in T3. The
reason for the delay is consistency, not risk: it emits a deprecation warning,
so a user may legitimately still import it from `geoqc.domain.models`, and both
removals should land in the same release with one CHANGELOG line. Deleting it in
T3 alone would split one deprecation story across two releases.

### 10.2 Everything else that looked dead is not

A sweep of every `def` and `class` in the audited modules for a reference count
of two or less returned only "definition plus exactly one call site" pairs:
`legacy._normalize_checks`, `dataset_values._attribute_value`,
`finding_builders._safe_intersects`, `finding_builders._geometry_kind`,
`spatial_intelligence_map.boundary_snap`,
`spatial_intelligence_map.small_polygons`, `public_reporting._map_locator`, and
five private helpers in `shapely_enterprise_spatial.py`. All are live.

`interfaces/api/*` (15 files, roughly 1.9k LOC) is **not** dead either. See
[section 12](#12-out-of-scope-observations).

## 11. T3 work packages

Three PRs, each independently reviewable and revertable. They are ordered so that
PR A is pure import-path churn and can land first, while B and C are additive
tests plus a localised refactor.

Every PR must satisfy the same gate before review:

```
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest
```

Plus, for any PR touching `apps/web`: `npm --prefix apps/web run check`.

And one invariant that is checked by a test added in PR A:
`len(geoqc.__all__) == 91` and the set is unchanged.

### PR A — remove facades, the dead service, and rename the misleading module

| Action | Target | Edits |
| --- | --- | --- |
| delete facade | `gis/quality_workflow.py` | 4 `src` importers + 3 test importers |
| delete facade | `domain/models/quality_workflow.py` | 9 `src` importers |
| delete | `application/services/spatial_intelligence.py` | 0 production importers |
| delete | `application/ports/spatial_intelligence.py` | 1 importer (the service above) |
| delete | `tests/.../test_spatial_intelligence_service.py` | its subject is gone |
| delete | `application/streaming/processor.py` | 1 re-export in `streaming/__init__.py` |
| merge | `gis/dataset_scoring.py` into `gis/dataset_audit.py` | 1 importer |
| rename | `gis/legacy.py` to `gis/deprecated_audit_arguments.py` | 1 importer |

Acceptance criteria:

1. `geoqc.__all__` is byte-identical to `85227bd`; a new test asserts the 91
   names so a future facade deletion cannot silently drop one.
2. `from geoqc import audit_dataset, audit_geodataframe, evaluate_topology_rules,
   assess_crs, issues_to_geodataframe, score_issues` all still work.
3. No `DeprecationWarning` newly emitted, and no new `RuntimeWarning` from
   duplicate module basenames.
4. `pytest` green with **only** import-line edits in test files. If a test needs
   a behavioural change, the premise of PR A is wrong and it stops.
5. CHANGELOG `### Changed` entry naming the three renamed or removed modules.
6. Coverage of `gis/dataset_audit.py` does not fall after absorbing
   `dataset_scoring`; the 8 statements move with their coverage.

### PR B — rename the dispatch table and close the coverage gaps

| Action | Target |
| --- | --- |
| rename | `gis/topology_rules_v2.py` to `gis/topology_rule_dispatch.py` (1 importer) |
| tests | `gis/shapely_topology_repairer.py` — 23 missed statements |
| tests | `gis/shapely_enterprise_spatial.py` — 21 missed statements |
| tests | `gis/dataset_values.py` — 6 missed statements |
| tests | `public_reporting.py` — 5 missed statements (CRS-less and `CRSError`) |
| tests | `gis/topology_service.py` — 4 missed statements (rule selection) |
| tests | `gis/deprecated_audit_arguments.py` — 1 missed warn-once branch |

Acceptance criteria:

1. Each target module reaches at least 95% statement coverage, or the miss is
   documented in a comment next to the test that cannot reach it.
2. The new tests fail if the covered branch is reverted — verified by
   temporarily reverting one branch locally, not by counting assertions.
3. The rename lands with no `topology_rules_v2` string left in `src`, `tests`,
   `docs`, or `tools`.
4. No production behaviour change: the same audit output on the existing
   integration fixtures, asserted by a diffed result serialisation.

### PR C — one folium geometry-map helper

Replace the duplicated `_geojson`/`_map` pair in
`reporting/enterprise_spatial_map.py` and `reporting/spatial_intelligence_map.py`
with a single shared helper module under `reporting/`.

Acceptance criteria:

1. The two map modules contain no `_geojson` or `_map` definition of their own.
2. `test_enterprise_spatial_map.py` and `test_spatial_intelligence_map.py` pass
   with **no changes**, proving the rendered output is equivalent.
3. The shared helper is covered by at least one test that builds each of the two
   map types.
4. No new entry in `reporting/__init__.py`'s `__all__`; the helper stays private.

## 12. Out-of-scope observations

Recorded so they are not re-discovered later, but deliberately not acted on in
T3.

- **`interfaces/api/*` is not dead.** 15 files, roughly 1.9k LOC, documented in
  [api.md](../api.md). However, `apps/web/src/RepairStudio.tsx` contains no
  `fetch` call and no `/api` reference, so the in-repo web client is a static
  demo: nothing in the repository exercises the HTTP layer end to end. That is a
  documentation-truth question for T6, not a deletion candidate.
- **`dataset_export` is a dependency of `profile_loading`.** `profile_loading.py:18`
  imports `dump_quality_profile` from the export adapter, so profile loading
  depends on an output adapter. Reversing that arrow is a genuine improvement but
  it is not a duplication fix. Recommended for T6.
- **`audit_geodataframe` results cannot export.** See
  [section 9.6](#96-two-serialization-paths-off-datasetauditresult). T6 owns it;
  T3 must not widen it.
- **T8 columns are intentionally empty.** No precision or recall numbers appear
  in this document, because the Indonesian sample datasets are not in `data/` yet
  and the OSM download sources and dates are unconfirmed. This audit does not
  estimate them.

## 13. Open decisions

The calls that need a human, each with a recommendation. Everything above assumes
the recommendation holds.

| ID | Decision | Recommendation | Blocking? |
| --- | --- | --- | --- |
| D1 | Delete `application/services/spatial_intelligence.py` and its port? | Yes — zero production callers, `public_spatial` bypasses it | No |
| D2 | Delete `application/streaming/processor.py` now? | Yes, and re-add a typed chunk adapter in T4 | No |
| D3 | When to remove `dataset_compat` and `DatasetAuditReport`? | 0.3.0, one CHANGELOG line, both in the same release | No |
| D4 | Split `finding_builders.py` (534 LOC) in T3? | No — split it in T4 with the typed `Finding` rewrite | No |
| D5 | Keep and rename `gis/legacy.py`, or delete it? | Keep and rename; it is the live `checks=`/`schema=` funnel | No |
| D6 | Fix the `profile_loading` to `dataset_export` arrow in T3? | No — defer to T6 so T3 stays import-only | No |

None of the six blocks T3. D3 and D6 are scheduled after it.

## 14. Evidence appendix

Commands used, in order, from the repository root.

Coverage, regenerated on 2026-11-02 15:10:

```
uv run coverage run -m pytest
uv run coverage report
```

The full report is filtered afterwards, because a comma-separated
`coverage report --include=` list only honours the last pattern in this
environment — a trap that silently drops modules from the table.

Callers per module, matching dotted module paths so that a docstring mentioning
`infrastructure.gis.legacy` cannot produce a false positive:

```
Get-ChildItem -Path src,tests,tools,examples -Recurse -Include *.py -File |
  Select-String -Pattern 'infrastructure\.gis\.legacy'
```

Dead-symbol sweep: every `def` and `class` in the audited modules is extracted
with `ast`, then counted across `src`, `tests`, `tools`, and `examples`. The
sweep reports symbols with two or fewer references, and each hit is read by hand,
because the normal result for a live private helper is exactly two: the
definition and its single call site.

Line counts:

```
Get-ChildItem src\geoqc -Recurse -Include *.py -File |
  Get-Content | Measure-Object -Line
```

Search caveat: a whole-repository regex search times out because of
`node_modules` and `.venv`. Scope every search to the four source trees above.

Gate before any T3 PR merges, per [AGENTS.md](../../AGENTS.md):

```
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest
```