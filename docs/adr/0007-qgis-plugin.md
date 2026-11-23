# 0007: QGIS plugin

Status: Accepted

The owner settled the six open items (C1 to C6). "Decisions taken" at the end
lists each one with its outcome, followed by the Phase 1 requirements and the
known limitations.

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
  `pip index versions geoqc` on 2026-11-23 lists one version, 0.1.0, by the
  same author and repository. `pyproject.toml` is at 0.2.0. A plain `geoqc`
  install therefore gets 0.1.0, not the current code.
- `metadata.txt` has placeholder `tracker` and `repository` URLs.
- `plugin.py` uses `Qgis.Critical` and `Qgis.Success`. QGIS 4 moves to scoped
  enums, so these lines need a Qt6 compatibility check.

## Decision

### 1. Plugin structure

The plugin graduates from `tools/qgis_spike/` to its own directory. The code
splits in two halves so most of it tests without QGIS.

```
apps/qgis-plugin/geoqc_qgis/
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
- Plugin root: `apps/qgis-plugin/`, next to `apps/web`. The move from
  `tools/qgis_spike/` belongs in the first implementation PR, not in this
  one.

### 2. Minimum QGIS version

The floor is **3.44 LTR**. The plugin must also pass on QGIS 4.x (Qt6). Both
are requirements from the first release. The plugin does not wait for 4.2 to
get the LTR label.

- The spike's 3.28 is two LTRs old and QGIS no longer patches it.
- Write the plugin against `qgis.PyQt` only, and use scoped enums
  (`Qgis.MessageLevel.Critical`, not `Qgis.Critical`), so one code base loads
  on QGIS 3 (Qt5) and QGIS 4 (Qt6).
- `metadata.txt` allows 4.x through `qgisMaximumVersion`. The test matrix
  runs 3.44 LTR and the newest 4.x release.
- A plugin version fails review if the `pyqgis4-checker` scan or the 4.x test
  run fails.
- Sources: [QGIS 4.0 and LTR plans](https://blog.qgis.org/2025/10/07/update-on-qgis-4-0-release-schedule-and-ltr-plans/),
  [QGIS roadmap](https://qgis.org/resources/roadmap/),
  [plugin migration to QGIS 4](https://plugins.qgis.org/docs/migrate-qgis4).
  Sources disagreed on the exact 3.44 point release and on whether 4.2 has
  the LTR label yet. The decision does not depend on either.

The interpreter inside QGIS does not limit GeoQC, because GeoQC runs in its
own venv (section 3). The floor depends on Processing and `QgsTask` APIs, not
on GeoQC's Python 3.12 requirement.

### 3. Installing geoqc and its dependencies

Use a private venv in the QGIS profile, created with `python -m venv` and
filled with `python -m pip install`. The plugin runs `geoqc` as a subprocess
and never imports it. It does not use `uv`: the spike's `uv` branches go
away.

The user needs a system Python 3.12 or newer. The plugin finds one and
reports a missing one in plain text.

| Platform | Python for the venv | Notes |
|----------|---------------------|-------|
| Windows | System Python 3.12+ on `PATH` or the `py` launcher | `sys.executable` is `qgis-bin.exe`, so it cannot build the venv. Skip `WindowsApps` stubs, as the spike does. |
| macOS | python.org or Homebrew 3.12+ | The venv Python picks wheels for Apple Silicon or Intel. |
| Linux | System Python 3.12+ | Ubuntu 22.04 ships 3.10. Without a 3.12 interpreter the install stops with a message that names the version found. |

Steps the installer takes: locate Python 3.12+, create the venv, install a
pinned geoqc version range, run `geoqc --version`, and compare it with the
range the plugin expects. A mismatch asks the user to repair the environment
through a menu action. The installer never runs at QGIS startup. It runs on
the first algorithm call or from an explicit menu action, always inside a
`QgsTask` (see Phase 1 requirements).

`GEOQC_SPEC` stays as an override for a wheel or project path during
development. Offline installs are a known limitation (C5).

PyPI currently serves geoqc 0.1.0 only, while the repository is at 0.2.0.
The plugin's pinned range needs a published release that contains the CLI
commands the plugin calls. Publishing is outside this ADR.

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
Processing dialog. v1 has no custom dialog. A dock panel comes in v2.

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
| Installer | Venv creation and install on Windows, macOS and Linux runners | No, uses real `python -m venv` and `pip` |
| Manual | `TESTING.md` smoke on one real desktop per OS before each plugin release | Yes |

- Headless runs use the official QGIS LTR container on Linux. Windows and
  macOS run the unit and installer layers on hosted runners. The desktop
  smoke test covers QGIS on those two systems.
- Run the Processing and parity layers on 3.44 LTR and on the newest 4.x
  release. The 4.x run does not wait for an LTR label.
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
- Cost: first run downloads packages, needs Python 3.12, adds
  process start-up latency, and the plugin must manage the venv.

### Using or bundling `uv`

- Gain: `uv` can fetch Python 3.12, so users on Ubuntu 22.04 and similar
  need no system interpreter. Installs run faster.
- Cost: a platform-specific binary in the zip, Gatekeeper and antivirus
  prompts for unsigned executables, and two install paths to test.
- Rejected. The plugin uses `python -m venv` and `pip` only. Users without
  Python 3.12 install it themselves.

### Custom dock widget instead of Processing

- Gain: tailored layout, inline result table.
- Cost: UI code to maintain, no modeler, batch or headless use, and a
  stronger pull to put logic in the widget.
- Deferred to v2. The dock panel follows once the Processing path is stable
  and calls the same algorithms.

### Blocking calls on the UI thread (current spike)

- Gain: the shortest code.
- Cost: QGIS freezes during install and long checks.
- Rejected. The spike accepts this to answer a feasibility question only.

## Consequences

- The plugin stays small and has no QC code. Engine changes reach QGIS
  without a plugin release.
- Users need network access once, plus Python 3.12 outside QGIS.
- Support cost grows: the plugin must diagnose a broken venv, a missing
  Python and a version mismatch, and report each in plain text.
- Two version axes exist: the QGIS floor and the geoqc range. Both go in
  `metadata.txt` and the release notes.
- Results arrive as files (GeoPackage, JSON report). This matches the
  `README.md` promise that results open in QGIS.
- No code changes in this PR. The implementation follows in later PRs, one
  per section.

## Decisions taken

| Id | Question | Outcome |
|----|----------|---------|
| C1 | QGIS minimum version | 3.44 LTR. The plugin must also pass on 4.x (Qt6). It does not wait for 4.2 to become LTR. |
| C2 | Plugin location | `apps/qgis-plugin/` |
| C3 | v1 surface | Processing provider only. Dock panel in v2. |
| C4 | `uv` | Not used. `python -m venv` and `pip`. |
| C5 | Offline install | Deferred. Recorded as a known limitation. |
| C6 | Is geoqc on PyPI? | Yes, but only 0.1.0. See below. |

C6 result, from `pip index versions geoqc` on 2026-11-23:

```
geoqc (0.1.0)
Available versions: 0.1.0
```

The PyPI metadata names Ananda Gunawan and links this repository. The
repository is at 0.2.0, so the published package lags the code. A release
that carries the commands the plugin needs comes before the plugin's first
public version.

## Phase 1 requirements

Phase 1 is the first implementation PR series. These are release gates:

1. The first install runs in a `QgsTask`. It never blocks the UI thread. The
   spike's blocking `run()` does not carry over.
2. Every `Qgis.Critical`, `Qgis.Success` and similar unscoped enum becomes
   the scoped form that works on QGIS 3.44 and 4.x
   (`Qgis.MessageLevel.Critical`, `Qgis.MessageLevel.Success`).
3. The plugin passes on QGIS 3.44 LTR and on the newest 4.x release.

## Known limitations

- No offline install. The installer needs network access to PyPI on first
  run (C5). `GEOQC_SPEC` with a local wheel works for developers only.
- Python 3.12 or newer must exist outside QGIS. The plugin does not fetch it.
- The published geoqc is 0.1.0, behind the repository's 0.2.0.
- The spike has no recorded results on Windows, macOS or Linux. Phase 1
  produces the first ones.
- No dock panel until v2.
