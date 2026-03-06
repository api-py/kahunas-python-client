"""Tests for configuration loading."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from kahunas_client.config import KahunasConfig


class TestKahunasConfig:
    def test_defaults(self) -> None:
        cfg = KahunasConfig()
        assert cfg.api_base_url == "https://api.kahunas.io/api"
        assert cfg.web_base_url == "https://kahunas.io"
        assert cfg.timeout == 30.0
        assert cfg.max_retries == 3
        assert cfg.email == ""
        assert cfg.password == ""
        assert cfg.auth_token == ""

    def test_direct_args(self) -> None:
        cfg = KahunasConfig(email="a@b.com", password="secret", auth_token="tok123")
        assert cfg.email == "a@b.com"
        assert cfg.password == "secret"
        assert cfg.auth_token == "tok123"

    def test_from_yaml(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.dump({"email": "yaml@test.com", "password": "yamlpass", "timeout": 60.0})
        )

        cfg = KahunasConfig.from_yaml(config_file)
        assert cfg.email == "yaml@test.com"
        assert cfg.password == "yamlpass"
        assert cfg.timeout == 60.0

    def test_from_yaml_missing_file(self, tmp_path: Path) -> None:
        cfg = KahunasConfig.from_yaml(tmp_path / "nonexistent.yaml")
        assert cfg.email == ""

    def test_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("KAHUNAS_EMAIL", "env@test.com")
        monkeypatch.setenv("KAHUNAS_PASSWORD", "envpass")
        monkeypatch.delenv("KAHUNAS_CONFIG_FILE", raising=False)
        cfg = KahunasConfig.from_env()
        assert cfg.email == "env@test.com"
        assert cfg.password == "envpass"

    def test_from_env_with_config_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({"email": "file@test.com"}))
        monkeypatch.setenv("KAHUNAS_CONFIG_FILE", str(config_file))
        cfg = KahunasConfig.from_env()
        assert cfg.email == "file@test.com"
