"""Tests for the initial domain exception hierarchy."""

from geoqc.domain.exceptions import GeoQCError


def test_geoqc_error_is_a_standard_exception() -> None:
    """Domain failures must integrate with Python exception handling."""
    assert issubclass(GeoQCError, Exception)
