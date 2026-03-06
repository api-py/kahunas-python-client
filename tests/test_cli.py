"""Tests for the CLI."""

from __future__ import annotations

from click.testing import CliRunner

from kahunas_client.cli.main import cli


class TestCLI:
    def test_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Kahunas" in result.output

    def test_version(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.output

    def test_workouts_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["workouts", "--help"])
        assert result.exit_code == 0
        assert "list" in result.output
        assert "show" in result.output

    def test_exercises_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["exercises", "--help"])
        assert result.exit_code == 0
        assert "list" in result.output
        assert "search" in result.output

    def test_clients_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["clients", "--help"])
        assert result.exit_code == 0
        assert "list" in result.output

    def test_export_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["export", "--help"])
        assert result.exit_code == 0
        assert "client" in result.output
        assert "all-clients" in result.output
        assert "exercises" in result.output
        assert "workouts" in result.output

    def test_serve_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["serve", "--help"])
        assert result.exit_code == 0
        assert "MCP" in result.output
