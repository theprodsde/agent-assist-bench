"""Configuration management using pydantic-settings.

Reads configuration from environment variables with the BENCH_ prefix,
with support for .env file loading from CWD. Explicit env vars take
precedence over .env file values.
"""

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    All settings use the BENCH_ prefix. For example, BENCH_HOST sets the host.
    A .env file in the current working directory is loaded automatically,
    but explicit environment variables always take precedence.
    """

    model_config = SettingsConfigDict(
        env_prefix="BENCH_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # API / Server
    host: str = "127.0.0.1"
    port: int = 8000

    # Runner
    delay_seconds: float = 2.0
    timeout_seconds: float = 300.0

    # Storage
    db_path: str = "storage/benchmark.db"
    export_dir: str = "storage/exports"

    # Agent endpoints (VM, ACA, or local Docker URLs)
    hermes_endpoint: str = "http://localhost:8001"
    openclaw_endpoint: str = "http://localhost:8002"

    # Agent deployment types: "local_docker", "virtual_machine", or "managed_container"
    hermes_deployment_type: str = "local_docker"
    openclaw_deployment_type: str = "local_docker"

    # Agent deployment resource configuration (optional, for cost/metrics tracking)
    hermes_cpu_cores: float | None = None
    hermes_memory_mb: float | None = None
    hermes_cost_per_hour: float | None = None
    openclaw_cpu_cores: float | None = None
    openclaw_memory_mb: float | None = None
    openclaw_cost_per_hour: float | None = None

    # Agent API keys (secrets — never persisted in DB or exports)
    hermes_api_key: SecretStr = SecretStr("")
    openclaw_api_key: SecretStr = SecretStr("")
    # NVIDIA direct API key — only needed for optional nemotron-reasoning/concise agents.
    # Leave empty to benchmark only the framework agents (Hermes vs OpenClaw).
    nvidia_api_key: SecretStr = SecretStr("")

    # Request signing key — shared secret for HMAC-SHA256 request authentication.
    # When set, the benchmark runner signs every outbound request and agents
    # verify the signature before processing. Prevents unauthorized callers.
    signing_key: SecretStr = SecretStr("")

    # Connector bot tokens (secrets — enable Telegram/Discord wiring when set)
    telegram_bot_token: SecretStr = SecretStr("")
    discord_bot_token: SecretStr = SecretStr("")

    # Cost per hour for each agent container (used to estimate per-request infra cost).
    # Formula: (latency_ms / 3_600_000) * cost_per_hour
    # On Azure ACA consumption (2 vCPU / 4 GB): ~$0.12/hr each.
    # Accurate for relative comparison — does not include idle/storage costs.
    hermes_cost_per_hour: float | None = None
    openclaw_cost_per_hour: float | None = None

    # Logging
    log_level: str = "INFO"
