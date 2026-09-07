"""Tests for the CLI."""

from __future__ import annotations

from collections.abc import Coroutine
from typing import Any

import pytest
from click.testing import CliRunner

from kahunas_client.cli.main import cli
from kahunas_client.mcp.transport import TRANSPORTS


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


class TestCredentialHandling:
    """A password on the command line is visible to other local users.

    The group callback runs only when a subcommand is dispatched, so these
    invoke a real command with the async runner stubbed out.
    """

    @staticmethod
    def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
        def close_without_running(coro: Coroutine[Any, Any, Any]) -> None:
            coro.close()

        monkeypatch.setattr("kahunas_client.cli.main._run", close_without_running)

    def test_warns_when_password_given_as_an_argument(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._no_network(monkeypatch)
        result = CliRunner().invoke(cli, ["--password", "hunter2", "workouts", "list"])
        assert result.exit_code == 0
        assert "visible to other" in result.output

    def test_no_warning_when_password_comes_from_the_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._no_network(monkeypatch)
        monkeypatch.setenv("KAHUNAS_PASSWORD", "hunter2")
        result = CliRunner().invoke(cli, ["workouts", "list"])
        assert result.exit_code == 0
        assert "visible to other" not in result.output

    def test_no_warning_without_a_password(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._no_network(monkeypatch)
        monkeypatch.delenv("KAHUNAS_PASSWORD", raising=False)
        result = CliRunner().invoke(cli, ["workouts", "list"])
        assert result.exit_code == 0
        assert "visible to other" not in result.output


class TestServeDefaults:
    """The HTTP transport has no authentication, so it binds loopback."""

    def test_host_defaults_to_loopback(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["serve", "--help"])
        assert result.exit_code == 0
        assert "0.0.0.0" not in result.output

    def test_transport_choices_come_from_the_shared_literal_set(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["serve", "--help"])
        for name in TRANSPORTS:
            assert name in result.output
