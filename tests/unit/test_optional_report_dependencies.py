"""The core package must work without the optional ``report`` extra."""

import subprocess
import sys
import textwrap


def _run_without_report_extra(body: str) -> subprocess.CompletedProcess[str]:
    """Run code in a fresh interpreter where folium and jinja2 cannot be imported."""
    program = "import sys\nsys.modules['folium'] = None\nsys.modules['jinja2'] = None\n"
    program += textwrap.dedent(body)
    return subprocess.run(
        [sys.executable, "-I", "-c", program],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


def test_import_geoqc_works_without_folium_or_jinja2() -> None:
    result = _run_without_report_extra(
        """
        import geoqc
        print(len(geoqc.__all__))
        """
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "91"


def test_core_audit_runs_without_folium_or_jinja2() -> None:
    result = _run_without_report_extra(
        """
        import geoqc
        from shapely.geometry import box
        audit = geoqc.audit_geometries([box(0, 0, 2, 2), box(1, 0, 3, 2)], preset="parcel")
        print(sorted({issue.code for issue in audit.issues}))
        """
    )

    assert result.returncode == 0, result.stderr
    assert "TOP-NO-OVERLAP" in result.stdout or "overlap" in result.stdout.lower()


def test_benchmark_report_names_stay_importable_without_the_extra() -> None:
    result = _run_without_report_extra(
        """
        from geoqc.infrastructure.reporting import BenchmarkFormat, write_benchmark_report
        print(BenchmarkFormat.__name__, callable(write_benchmark_report))
        """
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["BenchmarkFormat", "True"]


def test_map_renderers_need_the_extra_and_say_so_by_failing_to_import() -> None:
    result = _run_without_report_extra(
        """
        import geoqc
        try:
            import geoqc.infrastructure.reporting.enterprise_spatial_map
        except ImportError as error:
            print("ImportError", error.name)
        """
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["ImportError", "folium"]
