"""GeoQC dependency spike. geoqc is only ever run as a subprocess, never imported."""

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from qgis.core import Qgis, QgsApplication
from qgis.PyQt.QtWidgets import QAction

MENU = "&GeoQC"
TIMEOUT = 120


def _run(args: list[str], timeout: int = TIMEOUT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)


def _venv_dir() -> Path:
    return Path(QgsApplication.qgisSettingsDirPath()) / "geoqc_spike" / "venv"


def _venv_python(venv: Path) -> Path:
    sub = "Scripts/python.exe" if os.name == "nt" else "bin/python"
    return venv / sub


def _base_python() -> str:
    """Interpreter for `python -m venv`. On Windows sys.executable is qgis-bin.exe."""
    for name in ("python3", "python"):
        found = shutil.which(name)
        if found:
            return found
    return sys.executable


def ensure_venv() -> Path:
    venv = _venv_dir()
    python = _venv_python(venv)
    if python.exists():
        return python
    venv.parent.mkdir(parents=True, exist_ok=True)
    uv = shutil.which("uv")
    if uv:
        result = _run([uv, "venv", str(venv)])
        if result.returncode == 0 and python.exists():
            return python
    result = _run([_base_python(), "-m", "venv", str(venv)])
    if result.returncode != 0 or not python.exists():
        raise RuntimeError(
            f"venv creation failed: {result.stderr.strip() or result.stdout.strip()}"
        )
    return python


def install_geoqc(python: Path) -> None:
    spec = os.environ.get("GEOQC_SPEC", "geoqc")
    uv = shutil.which("uv")
    if uv:
        cmd = [uv, "pip", "install", "--python", str(python), spec]
    else:
        cmd = [str(python), "-m", "pip", "install", "--disable-pip-version-check", spec]
    result = _run(cmd, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(f"install of {spec} failed: {result.stderr.strip()[-400:]}")


def geoqc_version() -> str:
    python = ensure_venv()
    exe = python.parent / ("geoqc.exe" if os.name == "nt" else "geoqc")
    if not exe.exists():
        install_geoqc(python)
    result = _run([str(exe), "--version"])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"exit code {result.returncode}")
    return result.stdout.strip()


class GeoQCSpike:
    def __init__(self, iface: Any) -> None:  # noqa: ANN401
        self.iface = iface
        self.action: Any = None

    def initGui(self) -> None:
        self.action = QAction("GeoQC: version check", self.iface.mainWindow())
        self.action.triggered.connect(self.run)
        self.iface.addPluginToMenu(MENU, self.action)

    def unload(self) -> None:
        if self.action is not None:
            self.iface.removePluginMenu(MENU, self.action)
            self.action = None

    def run(self) -> None:
        bar = self.iface.messageBar()
        try:
            text = geoqc_version()
        except subprocess.TimeoutExpired:
            bar.pushMessage("GeoQC", f"Timed out after {TIMEOUT} s.", level=Qgis.Critical)
        except (OSError, RuntimeError) as error:
            bar.pushMessage("GeoQC", str(error), level=Qgis.Critical)
        else:
            bar.pushMessage("GeoQC", text, level=Qgis.Success)
