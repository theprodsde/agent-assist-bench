"""Unit tests for the configuration management module."""

import os
from pathlib import Path
from unittest.mock import patch

from benchmark.config.settings import Settings


class TestSettingsDefaults:
    """Test that default values are applied correctly (Req 11.3)."""

    def test_default_host(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert settings.host == "127.0.0.1"

    def test_default_port(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert settings.port == 8000

    def test_default_delay_seconds(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert settings.delay_seconds == 2.0

    def test_default_timeout_seconds(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert settings.timeout_seconds == 300.0

    def test_default_db_path(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert settings.db_path == "storage/benchmark.db"

    def test_default_export_dir(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert settings.export_dir == "storage/exports"

    def test_default_log_level(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert settings.log_level == "INFO"

    def test_default_api_keys_are_empty(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert settings.hermes_api_key.get_secret_value() == ""
        assert settings.openclaw_api_key.get_secret_value() == ""


class TestSettingsFromEnvVars:
    """Test that BENCH_ prefixed env vars override defaults (Req 11.1)."""

    def test_host_from_env(self) -> None:
        with patch.dict(os.environ, {"BENCH_HOST": "0.0.0.0"}, clear=True):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert settings.host == "0.0.0.0"

    def test_port_from_env(self) -> None:
        with patch.dict(os.environ, {"BENCH_PORT": "9090"}, clear=True):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert settings.port == 9090

    def test_delay_seconds_from_env(self) -> None:
        with patch.dict(os.environ, {"BENCH_DELAY_SECONDS": "5.5"}, clear=True):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert settings.delay_seconds == 5.5

    def test_timeout_seconds_from_env(self) -> None:
        with patch.dict(os.environ, {"BENCH_TIMEOUT_SECONDS": "600"}, clear=True):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert settings.timeout_seconds == 600.0

    def test_db_path_from_env(self) -> None:
        with patch.dict(os.environ, {"BENCH_DB_PATH": "/tmp/test.db"}, clear=True):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert settings.db_path == "/tmp/test.db"

    def test_export_dir_from_env(self) -> None:
        with patch.dict(os.environ, {"BENCH_EXPORT_DIR": "/tmp/exports"}, clear=True):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert settings.export_dir == "/tmp/exports"

    def test_log_level_from_env(self) -> None:
        with patch.dict(os.environ, {"BENCH_LOG_LEVEL": "DEBUG"}, clear=True):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert settings.log_level == "DEBUG"

    def test_hermes_api_key_from_env(self) -> None:
        with patch.dict(os.environ, {"BENCH_HERMES_API_KEY": "sk-hermes-123"}, clear=True):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert settings.hermes_api_key.get_secret_value() == "sk-hermes-123"

    def test_openclaw_api_key_from_env(self) -> None:
        with patch.dict(os.environ, {"BENCH_OPENCLAW_API_KEY": "sk-openclaw-456"}, clear=True):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert settings.openclaw_api_key.get_secret_value() == "sk-openclaw-456"


class TestSettingsDotEnvFile:
    """Test .env file loading and precedence (Req 11.2)."""

    def test_loads_values_from_dotenv(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("BENCH_HOST=10.0.0.1\nBENCH_PORT=3000\n")

        with patch.dict(os.environ, {}, clear=True):
            settings = Settings(_env_file=str(env_file))  # type: ignore[call-arg]

        assert settings.host == "10.0.0.1"
        assert settings.port == 3000

    def test_explicit_env_vars_override_dotenv(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("BENCH_HOST=10.0.0.1\nBENCH_PORT=3000\n")

        with patch.dict(os.environ, {"BENCH_HOST": "192.168.1.1"}, clear=True):
            settings = Settings(_env_file=str(env_file))  # type: ignore[call-arg]

        # Explicit env var takes precedence
        assert settings.host == "192.168.1.1"
        # .env value still applied for other fields
        assert settings.port == 3000

    def test_api_keys_from_dotenv(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text(
            "BENCH_HERMES_API_KEY=key-from-file\nBENCH_OPENCLAW_API_KEY=key2-from-file\n"
        )

        with patch.dict(os.environ, {}, clear=True):
            settings = Settings(_env_file=str(env_file))  # type: ignore[call-arg]

        assert settings.hermes_api_key.get_secret_value() == "key-from-file"
        assert settings.openclaw_api_key.get_secret_value() == "key2-from-file"


class TestSettingsApiKeySecrecy:
    """Test that API keys use SecretStr to prevent accidental exposure (Req 11.4)."""

    def test_hermes_key_repr_is_masked(self) -> None:
        with patch.dict(os.environ, {"BENCH_HERMES_API_KEY": "super-secret"}, clear=True):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
        # SecretStr repr should not expose the value
        assert "super-secret" not in repr(settings.hermes_api_key)

    def test_openclaw_key_repr_is_masked(self) -> None:
        with patch.dict(os.environ, {"BENCH_OPENCLAW_API_KEY": "top-secret"}, clear=True):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert "top-secret" not in repr(settings.openclaw_api_key)

    def test_api_keys_not_in_model_dump(self) -> None:
        with patch.dict(
            os.environ,
            {"BENCH_HERMES_API_KEY": "secret1", "BENCH_OPENCLAW_API_KEY": "secret2"},
            clear=True,
        ):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
        dumped = settings.model_dump()
        # SecretStr values in dump are SecretStr objects, not plain strings
        assert dumped["hermes_api_key"] != "secret1"
        assert dumped["openclaw_api_key"] != "secret2"
