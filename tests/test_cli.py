from typer.testing import CliRunner

from bdix_check.cli import app

runner = CliRunner()


def test_help_shows_options():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "--export" in result.output
    assert "--filter" in result.output
    assert "media, livetv, or all" in result.output


def test_invalid_filter_rejected():
    result = runner.invoke(app, ["--filter", "nope", "all"])
    assert result.exit_code != 0
    assert "filter must be one of" in result.output


def test_invalid_pages_rejected():
    result = runner.invoke(app, ["bogus"])
    assert result.exit_code != 0
    assert "pages must be one of" in result.output
