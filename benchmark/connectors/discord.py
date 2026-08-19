"""Framework-neutral Discord message translation and benchmark dispatch.

The core connector models only the Discord fields needed at the benchmark
boundary. Applications can adapt discord.py, nextcord, or raw HTTP clients to
these protocols without making the benchmark package depend on a Discord SDK.
"""

from __future__ import annotations

import mimetypes
from asyncio import Lock
from typing import Any, Literal, Protocol, cast, runtime_checkable

import structlog
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from benchmark.models.domain import Attachment, Benchmark, Execution, InputType

logger = structlog.get_logger(__name__)


class DiscordModel(BaseModel):
    """Permissive typed representation of a Discord API object."""

    model_config = ConfigDict(extra="allow")


class DiscordUser(DiscordModel):
    """Discord user identity associated with a message."""

    id: str
    username: str | None = None
    display_name: str | None = None


class DiscordChannel(DiscordModel):
    """Discord channel identity, including optional thread-parent metadata."""

    id: str
    name: str | None = None
    parent_id: str | None = None
    type: int | str | None = None


class DiscordThread(DiscordModel):
    """Optional thread identity supplied separately by an event adapter."""

    id: str
    parent_id: str | None = None
    name: str | None = None


class DiscordAttachment(DiscordModel):
    """Discord attachment metadata accepted by the connector."""

    id: str
    filename: str
    content_type: str | None = None
    size: int | None = None
    url: str | None = None
    proxy_url: str | None = None
    type: str | None = None


class DiscordMessage(DiscordModel):
    """Subset of a Discord message accepted by the connector."""

    id: str | None = None
    message_id: str | None = None
    event_id: str | None = None
    channel_id: str | None = None
    channel: DiscordChannel | None = None
    thread_id: str | None = None
    thread: DiscordThread | None = None
    content: str | None = None
    text: str | None = None
    author: DiscordUser | None = None
    attachments: list[DiscordAttachment] = Field(default_factory=list)

    def message_identity(self) -> str | None:
        """Return the stable event/message identity used for idempotency."""
        return self.event_id or self.id or self.message_id

    def conversation_identity(self) -> str | None:
        """Return channel identity, adding a distinct explicit thread ID."""
        channel_id = self.channel.id if self.channel is not None else self.channel_id
        if channel_id is None:
            return None
        thread_id = self.thread.id if self.thread is not None else self.thread_id
        identity = str(channel_id)
        if thread_id is not None and str(thread_id) != identity:
            identity = f"{identity}:{thread_id}"
        return identity

    def prompt_text(self) -> str | None:
        """Return Discord content, accepting ``text`` for adapter neutrality."""
        return self.content if self.content is not None else self.text


class DiscordEvent(DiscordModel):
    """Optional event envelope used by gateway adapters."""

    event_id: str | None = None
    id: str | None = None
    message: DiscordMessage | None = None


@runtime_checkable
class DiscordAttachmentClient(Protocol):
    """Minimal injectable attachment client; no Discord SDK is required."""

    async def download_bytes(self, attachment: DiscordAttachment) -> bytes | None:
        """Download exact bytes, or return ``None`` for URL-only mode."""
        ...

    async def resolve_url(self, attachment: DiscordAttachment) -> str | None:
        """Resolve an attachment URL, or return ``None`` when unavailable."""
        ...


@runtime_checkable
class DiscordResponseClient(Protocol):
    """Minimal injectable response client; no Discord SDK is required."""

    async def send_message(self, conversation_id: str, text: str) -> object:
        """Send text to a Discord channel or thread and return the API result."""
        ...


@runtime_checkable
class DiscordIdempotency(Protocol):
    """Atomic event/message claim store supplied by the application."""

    async def claim(self, event_id: str) -> bool:
        """Return true only for the first claim of an event/message ID."""
        ...


@runtime_checkable
class DiscordResponseIdempotency(Protocol):
    """Atomic claim store preventing duplicate response delivery."""

    async def claim(self, response_key: str) -> bool:
        """Return true only for the first delivery attempt for a benchmark."""
        ...


@runtime_checkable
class DiscordBenchmarkStorage(Protocol):
    """Storage boundary required by the inbound connector."""

    async def save_benchmark(self, benchmark: Benchmark) -> None: ...

    async def get_executions(self, benchmark_id: str) -> list[Execution]:
        """Return persisted execution records in runner order."""
        ...


@runtime_checkable
class DiscordBenchmarkDispatcher(Protocol):
    """Runner boundary required by the inbound connector."""

    async def run(self, benchmark: Benchmark) -> object: ...


class InMemoryDiscordIdempotency:
    """Atomic process-local claim store suitable for tests or one process."""

    def __init__(self) -> None:
        self._claimed: set[str] = set()
        self._lock = Lock()

    async def claim(self, event_id: str) -> bool:
        async with self._lock:
            if event_id in self._claimed:
                return False
            self._claimed.add(event_id)
            return True


class InMemoryDiscordResponseIdempotency:
    """Process-local response claim store for one bot process."""

    def __init__(self) -> None:
        self._claimed: set[str] = set()
        self._lock = Lock()

    async def claim(self, response_key: str) -> bool:
        async with self._lock:
            if response_key in self._claimed:
                return False
            self._claimed.add(response_key)
            return True


class DiscordConnectorError(BaseModel):
    """Structured, token-safe inbound connector failure."""

    code: Literal[
        "invalid_message",
        "missing_message_id",
        "missing_conversation",
        "empty_message",
        "unsupported_attachment",
        "attachment_content_unavailable",
        "storage_failure",
        "dispatch_failure",
        "execution_lookup_failure",
        "delivery_failure",
    ]
    message: str
    event_id: str | None = None
    attachment_index: int | None = None
    attachment_id: str | None = None
    modality: str | None = None


class DiscordDispatchResult(BaseModel):
    """Outcome of processing one inbound Discord message/event."""

    accepted: bool
    duplicate: bool = False
    delivered: bool = False
    benchmark: Benchmark | None = None
    error: DiscordConnectorError | None = None


class _ConnectorError(Exception):
    """Internal exception carrying a structured connector failure."""

    def __init__(self, error: DiscordConnectorError) -> None:
        super().__init__(error.message)
        self.error = error


class DiscordConnector:
    """Translate Discord messages, persist benchmarks, and dispatch the runner."""

    def __init__(
        self,
        storage: DiscordBenchmarkStorage,
        runner: DiscordBenchmarkDispatcher,
        discord: DiscordAttachmentClient,
        idempotency: DiscordIdempotency | None = None,
        response_client: DiscordResponseClient | None = None,
        response_idempotency: DiscordResponseIdempotency | None = None,
    ) -> None:
        self._storage = storage
        self._runner = runner
        self._discord = discord
        self._idempotency = idempotency or InMemoryDiscordIdempotency()
        self._response_client = response_client
        self._response_idempotency = response_idempotency or InMemoryDiscordResponseIdempotency()

    async def handle_message(
        self, message: DiscordMessage | DiscordEvent | dict[str, object]
    ) -> DiscordDispatchResult:
        """Translate, persist, and dispatch one Discord message/event.

        Attachment retrieval happens before persistence so an attachment can
        never disappear silently. Storage and runner exception details are
        logged only by safe type and represented by stable public messages.
        """
        parsed, parse_error = self._parse_message(message)
        if parse_error is not None:
            return DiscordDispatchResult(accepted=False, error=parse_error)
        assert parsed is not None

        event_id = parsed.message_identity()
        if event_id is None:
            return DiscordDispatchResult(
                accepted=False,
                error=DiscordConnectorError(
                    code="missing_message_id",
                    message="Discord message has no event or message ID",
                ),
            )

        try:
            benchmark = await self._to_benchmark(parsed, event_id)
        except _ConnectorError as exc:
            return DiscordDispatchResult(accepted=False, error=exc.error)

        if not await self._idempotency.claim(event_id):
            logger.info("discord_message_duplicate", event_id=event_id)
            return DiscordDispatchResult(accepted=False, duplicate=True)

        try:
            await self._storage.save_benchmark(benchmark)
        except Exception as exc:
            logger.error(
                "discord_benchmark_persist_failed",
                event_id=event_id,
                error_type=type(exc).__name__,
            )
            return DiscordDispatchResult(
                accepted=False,
                error=DiscordConnectorError(
                    code="storage_failure",
                    message="Unable to persist Discord benchmark",
                    event_id=event_id,
                ),
            )

        try:
            await self._runner.run(benchmark)
        except Exception as exc:
            logger.error(
                "discord_benchmark_dispatch_failed",
                event_id=event_id,
                benchmark_id=benchmark.id,
                error_type=type(exc).__name__,
            )
            return DiscordDispatchResult(
                accepted=False,
                benchmark=benchmark,
                error=DiscordConnectorError(
                    code="dispatch_failure",
                    message="Unable to dispatch Discord benchmark",
                    event_id=event_id,
                ),
            )

        delivered, delivery_error = await self._deliver_results(benchmark, event_id)
        if delivery_error is not None:
            return DiscordDispatchResult(
                accepted=False,
                benchmark=benchmark,
                error=delivery_error,
            )

        logger.info(
            "discord_benchmark_dispatched",
            event_id=event_id,
            benchmark_id=benchmark.id,
            conversation_id=benchmark.conversation_id,
            attachment_count=len(benchmark.attachments),
            response_delivered=delivered,
        )
        return DiscordDispatchResult(
            accepted=True,
            delivered=delivered,
            benchmark=benchmark,
        )

    async def _deliver_results(
        self, benchmark: Benchmark, event_id: str
    ) -> tuple[bool, DiscordConnectorError | None]:
        """Read persisted executions and deliver every result to Discord."""
        get_executions = getattr(self._storage, "get_executions", None)
        if not callable(get_executions):
            logger.warning(
                "discord_execution_lookup_unavailable",
                benchmark_id=benchmark.id,
            )
            return False, None

        try:
            executions = await get_executions(benchmark.id)
        except Exception as exc:
            logger.error(
                "discord_execution_lookup_failed",
                event_id=event_id,
                benchmark_id=benchmark.id,
                error_type=type(exc).__name__,
            )
            return False, DiscordConnectorError(
                code="execution_lookup_failure",
                message="Unable to retrieve Discord benchmark results",
                event_id=event_id,
            )

        response_client = self._response_client
        if response_client is None:
            candidate = getattr(self._discord, "send_message", None)
            if callable(candidate):
                response_client = self._discord  # type: ignore[assignment]
        if response_client is None:
            logger.warning(
                "discord_response_delivery_unconfigured",
                benchmark_id=benchmark.id,
            )
            return False, None
        if not executions or benchmark.conversation_id is None:
            return False, None

        try:
            if not await self._response_idempotency.claim(benchmark.id):
                logger.info(
                    "discord_response_duplicate",
                    benchmark_id=benchmark.id,
                )
                return False, None
            text = self._format_executions(executions)
            await response_client.send_message(benchmark.conversation_id, text)
        except Exception as exc:
            logger.error(
                "discord_response_delivery_failed",
                event_id=event_id,
                benchmark_id=benchmark.id,
                error_type=type(exc).__name__,
            )
            return False, DiscordConnectorError(
                code="delivery_failure",
                message="Unable to deliver Discord benchmark results",
                event_id=event_id,
            )
        return True, None

    @staticmethod
    def _format_executions(executions: list[Execution]) -> str:
        """Format all persisted executions without altering response/error text."""
        sections: list[str] = []
        for execution in executions:
            section = [
                f"Agent: {execution.agent_name}",
                f"Deployment: {execution.deployment.deployment_type.value}",
                f"Version: {execution.agent_version}",
                f"Status: {'successful' if execution.success else 'failed'}",
            ]
            if execution.result.raw_response:
                section.extend(["Response:", execution.result.raw_response])
            if execution.result.errors:
                section.append("Errors:")
                section.extend(f"- {error}" for error in execution.result.errors)
            sections.append("\\n".join(section))
        return "\\n\\n---\\n\\n".join(sections)

    async def process_message(
        self, message: DiscordMessage | DiscordEvent | dict[str, object]
    ) -> DiscordDispatchResult:
        """Alias for integrations that call inbound connector operations process."""
        return await self.handle_message(message)

    @staticmethod
    def _parse_message(
        message: DiscordMessage | DiscordEvent | dict[str, object],
    ) -> tuple[DiscordMessage | None, DiscordConnectorError | None]:
        event_id: str | None = None
        if isinstance(message, DiscordMessage):
            parsed = message
        elif isinstance(message, DiscordEvent):
            event_id = message.event_id or message.id
            parsed = message.message
        else:
            try:
                if isinstance(message.get("message"), dict):
                    event = DiscordEvent.model_validate(message)
                    event_id = event.event_id or event.id
                    parsed = event.message
                else:
                    parsed = DiscordMessage.model_validate(message)
            except (ValidationError, AttributeError):
                return None, DiscordConnectorError(
                    code="invalid_message",
                    message="Discord message does not match the supported shape",
                )
        if parsed is None:
            return None, DiscordConnectorError(
                code="invalid_message",
                message="Discord event does not contain a message",
                event_id=event_id,
            )
        if event_id is not None and parsed.event_id is None:
            parsed = parsed.model_copy(update={"event_id": event_id})
        return parsed, None

    async def _to_benchmark(self, message: DiscordMessage, event_id: str) -> Benchmark:
        conversation_id = message.conversation_identity()
        if conversation_id is None:
            raise _ConnectorError(
                DiscordConnectorError(
                    code="missing_conversation",
                    message="Discord message has no channel identity",
                    event_id=event_id,
                )
            )

        attachments = await self._attachments(message.attachments, event_id)
        prompt = message.prompt_text()
        if not prompt:
            if attachments:
                prompt = "[Discord attachment]"
            else:
                raise _ConnectorError(
                    DiscordConnectorError(
                        code="empty_message",
                        message="Discord message has neither text nor supported attachment",
                        event_id=event_id,
                    )
                )

        return Benchmark(
            source="discord",
            prompt=prompt,
            conversation_id=conversation_id,
            attachments=attachments,
        )

    async def _attachments(
        self, sources: list[DiscordAttachment], event_id: str
    ) -> list[Attachment]:
        result: list[Attachment] = []
        for index, source in enumerate(sources):
            modality = self._modality(source)
            if modality is None:
                raise _ConnectorError(
                    DiscordConnectorError(
                        code="unsupported_attachment",
                        message="Discord attachment type is not supported",
                        event_id=event_id,
                        attachment_index=index,
                        attachment_id=source.id,
                        modality=source.content_type or source.type or "unknown",
                    )
                )
            try:
                result.append(await self._attachment(modality, source, index, event_id))
            except _ConnectorError:
                raise
            except Exception as exc:
                logger.error(
                    "discord_attachment_processing_failed",
                    event_id=event_id,
                    attachment_index=index,
                    error_type=type(exc).__name__,
                )
                raise _ConnectorError(
                    DiscordConnectorError(
                        code="attachment_content_unavailable",
                        message="Unable to process Discord attachment",
                        event_id=event_id,
                        attachment_index=index,
                        attachment_id=source.id,
                        modality=modality,
                    )
                ) from exc
        return result

    @staticmethod
    def _modality(source: DiscordAttachment) -> Literal["image", "audio", "video"] | None:
        content_type = (source.content_type or "").lower()
        if content_type.startswith("image/"):
            return "image"
        if content_type.startswith("audio/"):
            return "audio"
        if content_type.startswith("video/"):
            return "video"
        guessed, _ = mimetypes.guess_type(source.filename)
        if guessed is not None:
            if guessed.startswith("image/"):
                return "image"
            if guessed.startswith("audio/"):
                return "audio"
            if guessed.startswith("video/"):
                return "video"
        return None

    async def _attachment(
        self,
        modality: Literal["image", "audio", "video"],
        source: DiscordAttachment,
        index: int,
        event_id: str,
    ) -> Attachment:
        """Retrieve one attachment without dropping metadata or content."""
        content: bytes | None = None
        try:
            content = await self._download(source)
        except Exception as exc:
            logger.warning(
                "discord_attachment_download_unavailable",
                attachment_id=source.id,
                error_type=type(exc).__name__,
            )

        source_url = source.url or source.proxy_url
        if content is None and source_url is None:
            try:
                source_url = await self._resolve_url(source)
            except Exception as exc:
                logger.warning(
                    "discord_attachment_url_resolution_unavailable",
                    attachment_id=source.id,
                    error_type=type(exc).__name__,
                )

        if content is None and not source_url:
            raise _ConnectorError(
                DiscordConnectorError(
                    code="attachment_content_unavailable",
                    message="Discord attachment has neither bytes nor a URL",
                    event_id=event_id,
                    attachment_index=index,
                    attachment_id=source.id,
                    modality=modality,
                )
            )

        mime_type = self._mime_type(modality, source.content_type, source.filename)
        filename = source.filename or source.id
        metadata: dict[str, object] = {
            "discord_attachment_id": source.id,
            "discord_source_url": source.url,
            "discord_proxy_url": source.proxy_url,
            "discord_attachment_type": source.type,
        }
        metadata = {key: value for key, value in metadata.items() if value is not None}
        # Attachment's domain invariant permits one transport source. When
        # bytes are downloaded, retain the source URL in connector metadata;
        # otherwise expose the URL through the canonical URL field.
        return Attachment(
            type=InputType(modality),
            filename=filename,
            mime_type=mime_type,
            size_bytes=source.size if source.size is not None else len(content or b""),
            content_bytes=content,
            url=None if content is not None else source_url,
            **metadata,
        )

    async def _download(self, source: DiscordAttachment) -> bytes | None:
        """Call the canonical client method, with compatibility aliases."""
        client = self._discord
        method = getattr(client, "download_bytes", None)
        if method is None:
            method = getattr(client, "download_attachment", None)
        if not callable(method):
            return None
        try:
            return cast(bytes | None, await method(source))
        except TypeError:
            # Adapters commonly expose the Discord REST shape as
            # download_attachment(attachment_id, url).
            return cast(bytes | None, await method(source.id, source.url or source.proxy_url))

    async def _resolve_url(self, source: DiscordAttachment) -> str | None:
        """Call the canonical URL resolver, with a REST-friendly alias."""
        client = self._discord
        method = getattr(client, "resolve_url", None)
        if method is None:
            method = getattr(client, "resolve_attachment_url", None)
        if not callable(method):
            return None
        try:
            return cast(str | None, await method(source))
        except TypeError:
            return cast(str | None, await method(source.id))

    @staticmethod
    def _mime_type(
        modality: Literal["image", "audio", "video"],
        supplied: str | None,
        filename: str,
    ) -> str:
        prefix = f"{modality}/"
        if supplied and supplied.startswith(prefix):
            return supplied
        guessed, _ = mimetypes.guess_type(filename)
        if guessed and guessed.startswith(prefix):
            return guessed
        return {
            "image": "image/jpeg",
            "audio": "audio/mpeg",
            "video": "video/mp4",
        }[modality]
