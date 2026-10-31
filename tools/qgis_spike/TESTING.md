# Testing the spike

1. `python tools/qgis_spike/build.py` builds `geoqc_spike.zip`.
2. In QGIS: Plugins > Manage and Install Plugins > Install from ZIP, pick the zip.
3. Optional, for a local build: set `GEOQC_SPEC` to a wheel or project path before starting QGIS.
4. Click `GeoQC` menu > `GeoQC: version check`. The first run creates a venv and installs geoqc.
5. Wait up to a few minutes. A green message bar shows the `geoqc --version` output.
6. Report back: QGIS version, OS, the Python version QGIS uses
   (Python console: `import sys; sys.version`), and the exact message-bar text.
7. On a red message, copy it in full.
