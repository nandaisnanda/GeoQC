# 0007: QGIS plugin

Status: Proposed

Items marked **[CONFIRM]** are open. The status stays Proposed until the
owner settles them. They are collected in "Open decisions" at the end.

## Context

GeoQC has a Python API and a CLI. `README.md` promises results that open in
QGIS, and `AGENTS.md` lists a QGIS plugin as a fourth surface on one engine.
`tools/qgis_spike/` holds a spike that answers one question: can QGIS install
and run GeoQC without breaking either side?

What the spike does today:

- It builds `geoqc_spike.zip` from three files (`build.py`).
- It creates a venv under the QGIS settings directory, installs `geoqc` into
  it with `uv pip` or `pip`, and runs `geoqc --version` as a subprocess
  (`plugin.py`). It never imports `geoqc` into QGIS's interpreter.
- It needs Python 3.12 or newer for the venv, because `pyproject.toml` sets
  `requires-python = ">=3.12"`. It looks for `uv`, then `python3`/`python`.
  On Windows it skips `sys.executable` because that is `qgis-bin.exe`.
- It declares `qgisMinimumVersion=3.28` and marks itself experimental.

What the spike leaves open:

- `TESTING.md` asks testers for the QGIS version, OS and message text. No
  results are recorded in the repository. Nothing here is verified on
  Windows, macOS or Linux.
- `run()` installs and runs on the UI thread. A first install can take up to
  600 s (`install_geoqc` timeout) and freezes QGIS for that long.
- `GEOQC_SPEC` defaults to `geoqc`, which assumes a published package.
  **[CONFIRM C6]**
- `metadata.txt` has placeholder `tracker` and `repository` URLs.
- `plugin.py` uses `Qgis.Critical` and `Qgis.Success`. QGIS 4 moves to scoped
  enums, so these lines need a Qt6 compatibility check.

## Decision

### 1. Plugin structure

The plugin graduates from `tools/qgis_spike/` to its own directory. The code
splits in two halves so most of it tests without QGIS.

```
<plugin root>/geoqc_qgis/
  metadata.txt
  __init__.py            classFactory only
  plugin.py              menu, toolbar, provider registration
  tasks.py               QgsTask subclasses
  processing/
    provider.py          QgsProcessingProvider
    check_algorithm.py   QgsProcessingAlgorithm: check
    repair_algorithm.py  QgsProcessingAlgorithm: repair to a new file
  runtime/               no qgis imports
    installer.py         find Python, create venv, install, verify version
    runner.py            build CLI arguments, run subprocess, parse output
```

- `runtime/` imports nothing from `qgis`. It is the only code that touches
  the subprocess and the venv.
- `build.py` grows from a fixed three-file list to a recursive zip of the
  package directory.
- Location of the plugin root: `tools/qgis_spike/` renamed, or a new
  top-level `integrations/qgis/`. **[CONFIRM C2]** The repository rules
  forbid new modules without a task, so the move belongs in the
  implementation PR, not in this one.

### 2. Minimum QGIS version

Use the current LTR as the floor and write the plugin against `qgis.PyQt`
only, so one code base loads on QGIS 3 (Qt5) and QGIS 4 (Qt6).

- Floor: **3.44 LTR**. **[CONFIRM C1]** The spike's 3.28 is two LTRs old and
  QGIS no longer patches it.
- QGIS 4.0 shipped on 2026-03-06. The 4.2 release is announced as the first
  4.x LTR, scheduled for October 2026. When it reaches the LTR repository,
  set `qgisMaximumVersion` to allow 4.x and add it to the test matrix.
- Sources: [QGIS 4.0 and LTR plans](https://blog.qgis.org/2025/10/07/update-on-qgis-4-0-release-schedule-and-ltr-plans/),
  [QGIS roadmap](https://qgis.org/resources/roadmap/),
  [plugin migration to QGIS 4](https://plugins.qgis.org/docs/migrate-qgis4).
  Search results disagreed on the exact 3.44 point release and whether 4.2
  carries the LTR label yet. Check the roadmap page before merging.

The interpreter inside QGIS does not limit GeoQC, because GeoQC runs in its
own venv (section 3). The floor depends on Processing and `QgsTask` APIs, not
on GeoQC's Python 3.12 requirement.

### 3. Installing geoqc and its dependencies

Keep the spike's approach: a private venv in the QGIS profile, `geoqc`
installed with `uv pip` when `uv` exists and `pip` otherwise, run as a
subprocess. The plugin never imports `geoqc`.

| Platform | Python for the venv | Notes |
|----------|---------------------|-------|
| Windows | `uv`, or a system Python 3.12+ on `PATH` | `sys.executable` is `qgis-bin.exe`. Skip `WindowsApps` stubs, as the spike does. |
| macOS | `uv`, or Homebrew/python.org 3.12+ | Apple Silicon and Intel need matching wheels. The venv Python picks the right ones. |
| Linux | `uv`, or system Python 3.12+ | Ubuntu 22.04 ships 3.10. Without `uv` the install fails with a clear message. |

Steps the installer takes: locate or fetch Python 3.12, create the venv,
install a pinned geoqc version range, run `geoqc --version`, and compare it
with the range the plugin expects. A mismatch asks the user to repair the
environment through a menu action. The installer never runs at QGIS startup;
it runs on the first algorithm call or from an explicit menu action, inside
a `QgsTask`.

Offline machines: support `GEOQC_SPEC` pointing at a wheel or a wheelhouse
directory, as the spike does for local builds. A documented offline path is
needed before an Indonesian agency deployment. **[CONFIRM C5]**

### 4. QgsTask

Every call that waits on a subprocess runs in a `QgsTask` registered with
`QgsApplication.taskManager()`.

- `InstallTask` wraps `runtime.installer`.
- `CheckTask` and `RepairTask` wrap `runtime.runner`.
- The task starts the subprocess, polls it, and checks `isCanceled()`. On
  cancel it terminates the child and its process tree (on Windows,
  `taskkill /T`).
- Progress stays indeterminate until the CLI offers machine-readable
  progress. No parsing of human output.
- Results load in `finished()`, which runs on the main thread. Worker code
  never touches layers or the project.

### 5. Processing provider

The Processing provider is the main surface. A `GeoQC` provider registers
two algorithms:

- `Check layer`: inputs are a vector layer, an optional preset, and an output
  folder. Outputs are the findings layer and a report path.
- `Repair layer`: writes a repaired copy. The source layer is never modified,
  per `AGENTS.md`. The user previews the output before using it.

The menu entry and toolbar button open these algorithms through the standard
Processing dialog. v1 has no custom dialog. **[CONFIRM C3]**

Algorithms live in the Processing toolbox, the Graphical Modeler, batch mode
and `qgis_process`, so the same checks run headless on a server.

Layer to file: a layer that is not file-backed (memory layer, database
layer) is exported to a temporary GeoPackage by QGIS before the run. That is
I/O, not QC.

### 6. Zero QC logic in the UI

The plugin contains no rule, threshold, geometry test, CRS comparison or
repair step. It does five things: collect parameters, call the CLI, show
progress, load output files, and show messages.

- The plugin never imports `geoqc`, `shapely`, `geopandas`, `pyogrio` or
  `pyproj`. The subprocess boundary enforces the rule structurally.
- Severity wording, counts and verdicts come from the CLI's JSON report.
  The plugin prints them without recomputing.
- A CI check fails the build if any file in the plugin package imports a
  banned module. Adding it touches `.github`, so it is a separate task.
- A new check or repair ships in the engine and reaches QGIS through a
  version bump of the pinned range. No plugin release is needed for a new
  rule.

### 7. Test strategy

| Layer | What it covers | Needs QGIS |
|-------|----------------|------------|
| Unit | `runtime/` argument building, Python discovery logic with a faked `PATH`, report parsing, version-range check | No |
| Processing | `processing.run` for both algorithms on `examples/sample_defects.gpkg`, run under `QgsApplication` in offscreen mode | Yes, headless |
| Parity | Plugin output equals CLI output on the same input: same findings, same counts | Yes, headless |
| Installer | Venv creation and install on Windows, macOS and Linux runners | No, uses real `uv` and `pip` |
| Manual | `TESTING.md` smoke on one real desktop per OS before each plugin release | Yes |

- Headless runs use the official QGIS LTR container on Linux. Windows and
  macOS run the unit and installer layers on hosted runners. The desktop
  smoke test covers QGIS on those two systems.
- Run the Processing and parity layers on 3.44 LTR now, and on 4.2 once it
  is the LTR.
- Existing tests stay untouched. New plugin tests live beside the plugin.

## Alternatives considered

### Installing geoqc into QGIS's own Python

Run `pip install geoqc` against the interpreter QGIS ships.

- Gain: no subprocess, direct API calls, shared memory with layers.
- Cost: GeoQC pins `numpy>=2.3`, `shapely>=2.1`, `pyarrow>=23` and
  `pyproj>=3.7`. QGIS bundles its own numpy, GDAL bindings and PROJ, and
  installers differ per platform. A wheel upgrade can break QGIS itself.
  On Windows OSGeo4W installs are often read-only without admin rights.
- Rejected. A conflict damages the user's QGIS, not just GeoQC.

### Vendoring dependencies inside the plugin zip

Ship wheels or compiled packages in the plugin.

- Gain: no network at install time and no external Python.
- Cost: compiled packages (numpy, shapely, pyarrow, pyproj, pyogrio) need one
  build per OS, CPU architecture and Python ABI. The zip grows to tens of
  megabytes, and the QGIS plugin repository limits upload size. Vendored
  copies still clash with QGIS's own numpy once loaded into its process.
- Rejected for v1. Reconsider a per-platform wheelhouse for offline use
  (C5).

### Private venv with a subprocess (chosen)

- Gain: dependency isolation, GeoQC upgrades independently of QGIS, same
  binary as the CLI users run, crash in GeoQC cannot crash QGIS.
- Cost: first run downloads packages, needs `uv` or Python 3.12, adds
  process start-up latency, and the plugin must manage the venv.

### Bundling `uv` in the plugin

- Gain: removes the Python 3.12 requirement on Linux and Windows.
- Cost: a platform-specific binary in the zip, and Gatekeeper and antivirus
  prompts for unsigned executables.
- Not adopted. Use `uv` when it is on `PATH`; otherwise ask the user to
  install it. **[CONFIRM C4]**

### Custom dock widget instead of Processing

- Gain: tailored layout, inline result table.
- Cost: UI code to maintain, no modeler, batch or headless use, and a
  stronger pull to put logic in the widget.
- Rejected for v1. A results dock can follow once the Processing path is
  stable.

### Blocking calls on the UI thread (current spike)

- Gain: the shortest code.
- Cost: QGIS freezes during install and long checks.
- Rejected. The spike accepts this to answer a feasibility question only.

## Consequences

- The plugin stays small and has no QC code. Engine changes reach QGIS
  without a plugin release.
- Users need network access once, plus `uv` or Python 3.12 outside QGIS.
- Support cost grows: the plugin must diagnose a broken venv, a missing
  Python and a version mismatch, and report each in plain text.
- Two version axes exist: the QGIS floor and the geoqc range. Both go in
  `metadata.txt` and the release notes.
- Results arrive as files (GeoPackage, JSON report). This matches the
  `README.md` promise that results open in QGIS.
- No code changes in this PR. The implementation follows in later PRs, one
  per section.

## Open decisions

| Id | Question | Proposed answer |
|----|----------|-----------------|
| C1 | QGIS minimum version | 3.44 LTR, with 4.2 added once it is LTR |
| C2 | Plugin location in the repo | `integrations/qgis/geoqc_qgis/` |
| C3 | v1 surface | Processing provider only, no custom dialog |
| C4 | Bundle `uv` or require it | Require `uv` or Python 3.12, do not bundle |
| C5 | Offline install path | Wheelhouse via `GEOQC_SPEC`, documented before agency use |
| C6 | Is `geoqc` published on PyPI under that name? | Needs a yes or no. The spike assumes yes. |
