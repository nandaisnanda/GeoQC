"""`geoqc --help` shows five everyday commands; advanced ones stay runnable."""

import re

import pytest
from typer.testing import CliRunner

from geoqc.interfaces.cli.main import app

_VISIBLE = ["check", "fix", "audit", "repair-roads", "presets"]
_HIDDEN = ["batch", "html-report", "crs-scan", "axis-order", "datum-shift"]


def _listed_commands(output: str) -> list[str]:
    block = re.split(r"[-─] Commands", output, maxsplit=1)[1]
    return re.findall(r"^[|│] (\S+)\s", block, flags=re.MULTILINE)


def test_help_lists_five_commands_in_order() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert _listed_commands(result.stdout) == _VISIBLE


@pytest.mark.parametrize("name", _HIDDEN)
def test_hidden_commands_still_have_help(name: str) -> None:
    result = CliRunner().invoke(app, [name, "--help"])

    assert result.exit_code == 0, result.output
    assert "Usage" in result.stdout


def test_hidden_command_still_runs() -> None:
    result = CliRunner().invoke(app, ["axis-order", "--bounds", "106.7", "-6.3", "106.9", "-6.1"])

    assert result.exit_code == 0, result.output
