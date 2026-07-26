"""Static tests for Clean Architecture dependency direction."""

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[2]
PACKAGE_ROOT = PROJECT_ROOT / "src" / "geoqc"

FORBIDDEN_DOMAIN_ROOTS = frozenset(
    {
        "fastapi",
        "folium",
        "geopandas",
        "jinja2",
        "numpy",
        "pandas",
        "pyogrio",
        "pyproj",
        "shapely",
        "typer",
        "geoqc.application",
        "geoqc.infrastructure",
        "geoqc.interfaces",
    }
)
FORBIDDEN_APPLICATION_ROOTS = frozenset(
    {
        "fastapi",
        "folium",
        "geopandas",
        "jinja2",
        "numpy",
        "pandas",
        "pyogrio",
        "pyproj",
        "shapely",
        "typer",
        "geoqc.infrastructure",
        "geoqc.interfaces",
    }
)


def _imports_in(source_file: Path) -> set[str]:
    """Return absolute imports declared in one Python source file."""
    tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module is not None:
            imports.add(node.module)
    return imports


def _violations(layer: str, forbidden_roots: frozenset[str]) -> list[str]:
    """Find forbidden imports within an architecture layer."""
    violations: list[str] = []
    for source_file in sorted((PACKAGE_ROOT / layer).rglob("*.py")):
        for imported_module in sorted(_imports_in(source_file)):
            if any(
                imported_module == root or imported_module.startswith(f"{root}.")
                for root in forbidden_roots
            ):
                violations.append(f"{source_file.relative_to(PROJECT_ROOT)} -> {imported_module}")
    return violations


def test_domain_has_no_outward_dependencies() -> None:
    """Domain must remain pure and independent from outer layers/frameworks."""
    assert _violations("domain", FORBIDDEN_DOMAIN_ROOTS) == []


def test_application_does_not_depend_on_adapters() -> None:
    """Application may depend on domain, never interfaces or infrastructure."""
    assert _violations("application", FORBIDDEN_APPLICATION_ROOTS) == []
