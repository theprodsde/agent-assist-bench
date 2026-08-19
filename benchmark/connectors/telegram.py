"""Telegram update translation and benchmark dispatch.

This module deliberately models only the Telegram Bot API fields needed by the
benchmark boundary.  An application can adapt any Telegram SDK (or HTTP
client) to :class:`TelegramApiClient` without making this package depend on it.
"""

from __future__ import annotations

import mimetypes
from asyncio import Lock
from pathlib import PurePosixPath
from typing import Literal, Protocol, runtime_checkable

import structlog
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from benchmark.models.domain import Attachment, Benchmark, Execution, InputType

logger = structlog.get_logger(__name__)


class TelegramModel(BaseModel):
    """Permissive typed representation of a Telegram Bot API object."""

    model_config = ConfigDict(extra="allow")


class TelegramChat(TelegramModel):
    """Telegram chat identity used for conversation routing."""

    id: int | str


class TelegramPhotoSize(TelegramModel):
    """One size variant in Telegram's photo-size array."""

    file_id: str
    file_unique_id: str | None = None
    width: int | None = None
    height: int | None = None
    file_size: int | None = None


class TelegramPhoto(TelegramPhotoSize):
    """Photo attachment; Telegram supplies multiple size variants."""


class TelegramAudio(TelegramModel):
    """Telegram audio attachment metadata."""

    file_id: str
    file_unique_id: str | None = None
    duration: int | None = None
    file_name: str | None = None
    mime_type: str | None = None
    file_size: int | None = None


class TelegramVideo(TelegramModel):
    """Telegram video attachment metadata."""

    file_id: str
    file_unique_id: str | None = None
    width: int | None = None
    height: int | None = None
    duration: int | None = None
    file_name: str | None = None
    mime_type: str | None = None
    file_size: int | None = None


class TelegramAttachment(TelegramModel):
    """Generic attachment metadata for SDK adapters and custom update shapes."""

    file_id: str
    file_unique_id: str | None = None
    file_name: str | None = None
    mime_type: str | None = None
    file_size: int | None = None
    type: Literal["image", "audio", "video", "document"] | None = None


class TelegramFile(TelegramModel):
    """Result of resolving a Telegram ``file_id`` through the Bot API."""

    file_id: str | None = None
    file_unique_id: str | None = None
    file_size: int | None = None
    file_path: str | None = None
    url: str | None = None
    mime_type: str | None = None


class TelegramMessage(TelegramModel):
    """Subset of a Telegram message accepted by the connector."""

    message_id: int | str | None = None
    chat: TelegramChat | None = None
    chat_id: int | str | None = None
    message_thread_id: int | str | None = None
    text: str | None = None
    caption: str | None = None
    photo: list[TelegramPhotoSize] = Field(default_factory=list)
    audio: TelegramAudio | None = None
    voice: TelegramAudio | None = None
    video: TelegramVideo | None = None
    document: TelegramAttachment | None = None
    attachments: list[TelegramAttachment] = Field(default_factory=list)

    def conversation_id(self) -> str | None:
        """Return stable chat/thread identity in the shared string form."""
        chat_id = self.chat.id if self.chat is not None else self.chat_id
        if chat_id is None:
            return None
        identity = str(chat_id)
        if self.message_thread_id is not None:
            identity = f"{identity}:{self.message_thread_id}"
        return identity


class TelegramUpdate(TelegramModel):
    """Incoming Telegram update envelope."""

    update_id: int | str
    message: TelegramMessage | None = None


@runtime_checkable
class TelegramApiClient(Protocol):
    """Minimal injectable Telegram file client; no Telegram SDK is required."""

    async def download_file(self, file_id: str) -> bytes | None:
        """Download bytes, or return ``None`` when URL-only mode is preferred."""
        ...

    async def resolve_file_url(self, file_id: str) -> str | None:
        """Resolve a file ID to an HTTPS URL, or return ``None``."""
        ...


@runtime_checkable
class TelegramResponseClient(Protocol):
    """Minimal injectable response client; no Telegram SDK is required."""

    async def send_message(self, conversation_id: str, text: str) -> object:
        """Send text to a Telegram conversation and return the API result."""
        ...


@runtime_checkable
class TelegramIdempotency(Protocol):
    """Atomic update-claim store supplied by the application."""

    async def claim(self, update_id: str) -> bool:
        """Return true only for the first claim of an update ID."""
        ...


@runtime_checkable
class TelegramResponseIdempotency(Protocol):
    """Atomic claim store preventing duplicate response delivery."""

    async def claim(self, response_key: str) -> bool:
        """Return true only for the first delivery attempt for a benchmark."""
        ...


@runtime_checkable
class BenchmarkStorage(Protocol):
    """Storage boundary required by the connector."""

    async def save_benchmark(self, benchmark: Benchmark) -> None: ...

    async def get_executions(self, benchmark_id: str) -> list[Execution]:
        """Return persisted execution records in runner order."""
        ...


@runtime_checkable
class BenchmarkDispatcher(Protocol):
    """Runner boundary required by the connector."""

    async def run(self, benchmark: Benchmark) -> object: ...


class InMemoryTelegramIdempotency:
    """Small process-local idempotency store suitable for one bot process.

    Production deployments can inject a database- or cache-backed implementation
    with the same protocol to retain claims across restarts and replicas.
    """

    def __init__(self) -> None:
        self._claimed: set[str] = set()
        self._lock = Lock()

    async def claim(self, update_id: str) -> bool:
        async with self._lock:
            if update_id in self._claimed:
                return False
            self._claimed.add(update_id)
            return True


class InMemoryTelegramResponseIdempotency:
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


class TelegramConnectorError(BaseModel):
    """Structured, token-safe connector failure."""

    code: Literal[
        "invalid_update",
        "missing_message",
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
    update_id: str | None = None
    attachment_index: int | None = None
    file_id: str | None = None
    modality: str | None = None


class TelegramDispatchResult(BaseModel):
    """Outcome of processing one Telegram update."""

    accepted: bool
    duplicate: bool = False
    delivered: bool = False
    benchmark: Benchmark | None = None
    error: TelegramConnectorError | None = None


class _AttachmentError(Exception):
    """Internal exception carrying a structured attachment failure."""

    def __init__(self, error: TelegramConnectorError) -> None:
        super().__init__(error.message)
        self.error = error


class TelegramConnector:
    """Translate Telegram updates, persist, dispatch, and deliver results."""

    def __init__(
        self,
        storage: BenchmarkStorage,
        runner: BenchmarkDispatcher,
        telegram: TelegramApiClient,
        idempotency: TelegramIdempotency | None = None,
        response_client: TelegramResponseClient | None = None,
        response_idempotency: TelegramResponseIdempotency | None = None,
    ) -> None:
        self._storage = storage
        self._runner = runner
        self._telegram = telegram
        self._idempotency = idempotency or InMemoryTelegramIdempotency()
        self._response_client = response_client
        self._response_idempotency = response_idempotency or InMemoryTelegramResponseIdempotency()

    async def handle_update(
        self, update: TelegramUpdate | dict[str, object]
    ) -> TelegramDispatchResult:
        """Process an update at the storage/runner boundary.

        Parsing, attachment retrieval, persistence, and dispatch failures are
        returned as stable structured errors. Exception text is intentionally
        excluded from logs and returned errors so bot tokens in SDK messages
        cannot leak.
        """
        parsed, parse_error = self._parse_update(update)
        if parse_error is not None:
            return TelegramDispatchResult(accepted=False, error=parse_error)
        assert parsed is not None

        update_id = str(parsed.update_id)
        try:
            benchmark = await self._to_benchmark(parsed)
        except _AttachmentError as exc:
            return TelegramDispatchResult(accepted=False, error=exc.error)

        if not await self._idempotency.claim(update_id):
            logger.info("telegram_update_duplicate", update_id=update_id)
            return TelegramDispatchResult(accepted=False, duplicate=True)

        try:
            await self._storage.save_benchmark(benchmark)
        except Exception as exc:
            error = TelegramConnectorError(
                code="storage_failure",
                message="Unable to persist Telegram benchmark",
                update_id=update_id,
            )
            logger.error(
                "telegram_benchmark_persist_failed",
                update_id=update_id,
                error_type=type(exc).__name__,
            )
            return TelegramDispatchResult(accepted=False, error=error)

        try:
            await self._runner.run(benchmark)
        except Exception as exc:
            error = TelegramConnectorError(
                code="dispatch_failure",
                message="Unable to dispatch Telegram benchmark",
                update_id=update_id,
            )
            logger.error(
                "telegram_benchmark_dispatch_failed",
                update_id=update_id,
                benchmark_id=benchmark.id,
                error_type=type(exc).__name__,
            )
            return TelegramDispatchResult(accepted=False, benchmark=benchmark, error=error)

        delivered, delivery_error = await self._deliver_results(benchmark, update_id)
        if delivery_error is not None:
            return TelegramDispatchResult(
                accepted=False,
                benchmark=benchmark,
                error=delivery_error,
            )

        logger.info(
            "telegram_benchmark_dispatched",
            update_id=update_id,
            benchmark_id=benchmark.id,
            conversation_id=benchmark.conversation_id,
            attachment_count=len(benchmark.attachments),
            response_delivered=delivered,
        )
        return TelegramDispatchResult(
            accepted=True,
            delivered=delivered,
            benchmark=benchmark,
        )

    async def _deliver_results(
        self, benchmark: Benchmark, update_id: str
    ) -> tuple[bool, TelegramConnectorError | None]:
        """Read persisted executions and send one comparison-safe Telegram message."""
        get_executions = getattr(self._storage, "get_executions", None)
        if not callable(get_executions):
            # Keep the connector compatible with the pre-delivery test boundary;
            # real storage implementations must expose this method.
            logger.warning(
                "telegram_execution_lookup_unavailable",
                benchmark_id=benchmark.id,
            )
            return False, None

        try:
            executions = await get_executions(benchmark.id)
        except Exception as exc:
            logger.error(
                "telegram_execution_lookup_failed",
                update_id=update_id,
                benchmark_id=benchmark.id,
                error_type=type(exc).__name__,
            )
            return False, TelegramConnectorError(
                code="execution_lookup_failure",
                message="Unable to retrieve Telegram benchmark results",
                update_id=update_id,
            )

        response_client = self._response_client
        if response_client is None:
            candidate = getattr(self._telegram, "send_message", None)
            if callable(candidate):
                response_client = self._telegram  # type: ignore[assignment]
        if response_client is None:
            logger.warning(
                "telegram_response_delivery_unconfigured",
                benchmark_id=benchmark.id,
            )
            return False, None
        if not executions or benchmark.conversation_id is None:
            return False, None

        try:
            if not await self._response_idempotency.claim(benchmark.id):
                logger.info(
                    "telegram_response_duplicate",
                    benchmark_id=benchmark.id,
                )
                return False, None
            text = self._format_executions(executions)
            await response_client.send_message(benchmark.conversation_id, text)
        except Exception as exc:
            logger.error(
                "telegram_response_delivery_failed",
                update_id=update_id,
                benchmark_id=benchmark.id,
                error_type=type(exc).__name__,
            )
            return False, TelegramConnectorError(
                code="delivery_failure",
                message="Unable to deliver Telegram benchmark results",
                update_id=update_id,
            )
        return True, None

    @staticmethod
    def _format_executions(executions: list[Execution]) -> str:
        """Format all persisted executions for Telegram delivery.

        Each agent gets a header block. Responses are preserved verbatim so
        the human can compare them side-by-side.
        """
        sections: list[str] = []
        for execution in executions:
            latency = f"{execution.deployment.total_latency_ms / 1000:.1f}s"
            status = "✅" if execution.success else "❌"
            header = f"{status} *{execution.agent_name}* ({latency})"
            lines = [header]
            # Include agent details
            lines.append(f"Agent: {execution.agent_name}")
            # Map deployment type to user-friendly format
            deployment_map = {
                "local_docker": "local_docker",
                "virtual_machine": "vm",
                "managed_container": "managed",
            }
            deployment_display = deployment_map.get(
                execution.deployment.deployment_type.value, execution.deployment.deployment_type.value
            )
            lines.append(f"Deployment: {deployment_display}")
            # Include status for failed executions
            if not execution.success:
                lines.append("Status: failed")
            # Include response
            if execution.result.raw_response:
                lines.append(execution.result.raw_response.strip())
            # Include errors
            if execution.result.errors:
                lines.append("Errors: " + "; ".join(execution.result.errors))
            sections.append("\n".join(lines))
        return "\n\n---\n\n".join(sections)

    async def process_update(
        self, update: TelegramUpdate | dict[str, object]
    ) -> TelegramDispatchResult:
        """Alias for integrations that call inbound connector operations process."""
        return await self.handle_update(update)

    @staticmethod
    def _parse_update(
        update: TelegramUpdate | dict[str, object],
    ) -> tuple[TelegramUpdate | None, TelegramConnectorError | None]:
        if isinstance(update, TelegramUpdate):
            parsed = update
        else:
            try:
                parsed = TelegramUpdate.model_validate(update)
            except ValidationError:
                return None, TelegramConnectorError(
                    code="invalid_update",
                    message="Telegram update does not match the supported shape",
                )
        if parsed.message is None:
            return None, TelegramConnectorError(
                code="missing_message",
                message="Telegram update does not contain a message",
                update_id=str(parsed.update_id),
            )
        return parsed, None

    async def _to_benchmark(self, update: TelegramUpdate) -> Benchmark:
        assert update.message is not None
        message = update.message
        update_id = str(update.update_id)
        conversation_id = message.conversation_id()
        if conversation_id is None:
            raise _AttachmentError(
                TelegramConnectorError(
                    code="missing_conversation",
                    message="Telegram message has no chat identity",
                    update_id=update_id,
                )
            )

        attachments = await self._attachments(message, update_id)
        prompt = message.text or message.caption
        if not prompt:
            if attachments:
                prompt = "[Telegram attachment]"
            else:
                raise _AttachmentError(
                    TelegramConnectorError(
                        code="empty_message",
                        message="Telegram message has neither text nor supported attachment",
                        update_id=update_id,
                    )
                )

        return Benchmark(
            source="telegram",
            prompt=prompt,
            conversation_id=conversation_id,
            attachments=attachments,
        )

    async def _attachments(self, message: TelegramMessage, update_id: str) -> list[Attachment]:
        sources: list[tuple[str, object]] = []
        if message.photo:
            # Telegram photo arrays are size variants of one attachment.
            sources.append(("image", max(message.photo, key=self._photo_area)))
        if message.audio is not None:
            sources.append(("audio", message.audio))
        if message.voice is not None:
            sources.append(("audio", message.voice))
        if message.video is not None:
            sources.append(("video", message.video))
        if message.attachments:
            sources.extend((item.type or "unknown", item) for item in message.attachments)
        if message.document is not None:
            raise _AttachmentError(
                TelegramConnectorError(
                    code="unsupported_attachment",
                    message="Telegram document attachments are not supported",
                    update_id=update_id,
                    attachment_index=len(sources),
                    file_id=message.document.file_id,
                    modality="document",
                )
            )

        result: list[Attachment] = []
        for index, (modality, source) in enumerate(sources):
            if modality not in {"image", "audio", "video"}:
                raise _AttachmentError(
                    TelegramConnectorError(
                        code="unsupported_attachment",
                        message=f"Telegram {modality} attachments are not supported",
                        update_id=update_id,
                        attachment_index=index,
                        file_id=getattr(source, "file_id", None),
                        modality=modality,
                    )
                )
            try:
                result.append(await self._attachment(modality, source, index, update_id))
            except _AttachmentError:
                raise
            except Exception as exc:
                logger.error(
                    "telegram_attachment_processing_failed",
                    update_id=update_id,
                    attachment_index=index,
                    error_type=type(exc).__name__,
                )
                raise _AttachmentError(
                    TelegramConnectorError(
                        code="attachment_content_unavailable",
                        message="Unable to process Telegram attachment",
                        update_id=update_id,
                        attachment_index=index,
                        modality=modality,
                    )
                ) from exc
        return result

    @staticmethod
    def _photo_area(photo: TelegramPhotoSize) -> int:
        return (photo.width or 0) * (photo.height or 0)

    async def _attachment(
        self,
        modality: str,
        source: object,
        index: int,
        update_id: str,
    ) -> Attachment:
        """Resolve one Telegram file into the shared Attachment model."""
        file_id = getattr(source, "file_id", None)
        if not isinstance(file_id, str) or not file_id:
            raise _AttachmentError(
                TelegramConnectorError(
                    code="attachment_content_unavailable",
                    message="Telegram attachment has no file ID",
                    update_id=update_id,
                    attachment_index=index,
                    modality=modality,
                )
            )

        file_name = getattr(source, "file_name", None)
        supplied_mime = getattr(source, "mime_type", None)
        supplied_size = getattr(source, "file_size", None)
        resolved: TelegramFile | None = None
        content: bytes | None = None
        url: str | None = None

        # Downloading is preferred for exact byte preservation. A client may
        # intentionally return None to use URL-only mode.
        try:
            content = await self._telegram.download_file(file_id)
        except (AttributeError, NotImplementedError):
            content = None
        except Exception as exc:
            logger.warning(
                "telegram_file_download_unavailable",
                file_id=file_id,
                error_type=type(exc).__name__,
            )
        if content is None:
            try:
                url = await self._telegram.resolve_file_url(file_id)
            except (AttributeError, NotImplementedError):
                url = None
            except Exception as exc:
                logger.warning(
                    "telegram_file_url_resolution_unavailable",
                    file_id=file_id,
                    error_type=type(exc).__name__,
                )

        if content is None and not url:
            raise _AttachmentError(
                TelegramConnectorError(
                    code="attachment_content_unavailable",
                    message="Telegram attachment has neither bytes nor a URL",
                    update_id=update_id,
                    attachment_index=index,
                    file_id=file_id,
                    modality=modality,
                )
            )

        # A client can expose richer Bot API file metadata via an optional
        # get_file method without making that SDK-specific method mandatory.
        get_file = getattr(self._telegram, "get_file", None)
        if get_file is not None:
            try:
                candidate = await get_file(file_id)
                if isinstance(candidate, TelegramFile):
                    resolved = candidate
                elif isinstance(candidate, dict):
                    resolved = TelegramFile.model_validate(candidate)
            except Exception as exc:
                logger.warning(
                    "telegram_file_metadata_unavailable",
                    file_id=file_id,
                    error_type=type(exc).__name__,
                )

        file_name = file_name or self._filename(resolved, file_id)
        mime_type = self._mime_type(
            modality,
            supplied_mime or (resolved.mime_type if resolved else None),
            file_name,
            resolved.file_path if resolved else None,
        )
        size = len(content) if content is not None else supplied_size
        if size is None and resolved is not None:
            size = resolved.file_size

        metadata = {
            "connector_file_id": file_id,
            "telegram_file_unique_id": getattr(source, "file_unique_id", None)
            or (resolved.file_unique_id if resolved else None),
        }
        if resolved is not None and resolved.file_path:
            metadata["telegram_file_path"] = resolved.file_path
        metadata = {key: value for key, value in metadata.items() if value is not None}
        return Attachment(
            type=InputType(modality),
            filename=file_name,
            mime_type=mime_type,
            size_bytes=size,
            content_bytes=content,
            url=url,
            **metadata,
        )

    @staticmethod
    def _filename(resolved: TelegramFile | None, file_id: str) -> str:
        if resolved is not None and resolved.file_path:
            name = PurePosixPath(resolved.file_path).name
            if name:
                return name
        return file_id

    @staticmethod
    def _mime_type(
        modality: str,
        supplied: str | None,
        filename: str | None,
        file_path: str | None,
    ) -> str:
        prefix = f"{modality}/"
        if supplied and supplied.startswith(prefix):
            return supplied
        guessed, _ = mimetypes.guess_type(filename or file_path or "")
        if guessed and guessed.startswith(prefix):
            return guessed
        defaults = {
            "image": "image/jpeg",
            "audio": "audio/mpeg",
            "video": "video/mp4",
        }
        return defaults[modality]
