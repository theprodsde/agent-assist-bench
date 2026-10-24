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

    # LLM token prices in USD per 1 million tokens (optional).
    # Used to estimate per-request cost when the endpoint does not report one
    # (standard OpenAI-compatible endpoints never do). Example: 0.60 = $0.60/1M.
    hermes_input_price_per_mtok: float | None = None
    hermes_output_price_per_mtok: float | None = None
    openclaw_input_price_per_mtok: float | None = None
    openclaw_output_price_per_mtok: float | None = None
    nvidia_input_price_per_mtok: float | None = None
    nvidia_output_price_per_mtok: float | None = None

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

    # Comma-separated Telegram chat IDs allowed to trigger benchmarks.
    # Required to start the bot: anyone who can message an unrestricted bot
    # can burn your API quota. Find your chat ID via @userinfobot in Telegram.
    # Example: BENCH_TELEGRAM_ALLOWED_CHAT_IDS=123456789,987654321
    telegram_allowed_chat_ids: str = ""

    # Explicit opt-in to run the Telegram bot with no chat ID restriction
    # (a deliberately public bot). Ignored when allowed chat IDs are set.
    telegram_allow_all_chats: bool = False

    # Generic agents — define any number of OpenAI-compatible agents in JSON.
    # Each item must have: name, endpoint, model (str); optional: api_key, deployment_type,
    # cpu_cores, memory_mb, cost_per_hour.
    # Example (single-line, no real newlines inside the JSON value):
    #   BENCH_AGENTS_JSON=[{"name":"librechat","endpoint":"http://localhost:9000/v1","model":"gpt-4o","api_key":"sk-...","deployment_type":"local_docker"}]
    # Agents defined here are registered in addition to any Hermes/OpenClaw keys above.
    agents_json: str = ""

    # Logging
    log_level: str = "INFO"
