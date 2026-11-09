"""The domain layer imports no GIS stack, web framework, or outer layer."""

import ast
from pathlib import Path

import pytest

DOMAIN_ROOT = Path(__file__).resolve().parents[2] / "src" / "geoqc" / "domain"

FORBIDDEN_PACKAGES = frozenset(
    {"geopandas", "pyogrio", "shapely", "pyproj", "numpy", "pandas", "folium", "jinja2"}
    | {"fastapi", "starlette", "uvicorn", "qgis", "osgeo"}
)
FORBIDDEN_LAYERS = ("geoqc.infrastructure", "geoqc.interfaces", "geoqc.application")


def _imported_modules(source: str) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.append((node.lineno, node.module))
    return found


def _violations(source: str) -> list[str]:
    bad: list[str] = []
    for lineno, module in _imported_modules(source):
        root = module.split(".")[0]
        if root in FORBIDDEN_PACKAGES or module.startswith(FORBIDDEN_LAYERS):
            bad.append(f"line {lineno}: {module}")
    return bad


def test_scanner_flags_forbidden_imports() -> None:
    source = (
        "import geopandas as gpd\n"
        "from shapely.geometry import Point\n"
        "from geoqc.infrastructure.gis import audit_service\n"
        "import json\n"
    )
    assert _violations(source) == [
        "line 1: geopandas",
        "line 2: shapely.geometry",
        "line 3: geoqc.infrastructure.gis",
    ]


def test_scanner_sees_imports_nested_in_functions_and_type_checking() -> None:
    source = (
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    import fastapi\n"
        "def build():\n"
        "    import folium\n"
    )
    assert _violations(source) == ["line 3: fastapi", "line 5: folium"]


def test_domain_package_is_found() -> None:
    assert len(list(DOMAIN_ROOT.rglob("*.py"))) > 10


@pytest.mark.parametrize(
    "path",
    sorted(DOMAIN_ROOT.rglob("*.py")),
    ids=lambda path: path.relative_to(DOMAIN_ROOT).as_posix(),
)
def test_domain_module_has_no_forbidden_imports(path: Path) -> None:
    assert _violations(path.read_text(encoding="utf-8")) == []
