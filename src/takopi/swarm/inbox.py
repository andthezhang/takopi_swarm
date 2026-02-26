from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
import uuid

import anyio
import msgspec

from ..logging import get_logger
from ..telegram.types import TelegramIncomingMessage
from .config import SwarmIngressConfig

logger = get_logger(__name__)

SwarmIntent = Literal["control", "trigger"]


class SwarmEnvelope(msgspec.Struct, kw_only=True, forbid_unknown_fields=True):
    version: int = 1
    event_id: str
    intent: SwarmIntent
    chat_id: int
    thread_id: int | None = None
    text: str
    origin_agent: str | None = None
    created_at: str | None = None


def new_swarm_envelope(
    *,
    intent: SwarmIntent,
    chat_id: int,
    thread_id: int | None,
    text: str,
    origin_agent: str | None,
) -> SwarmEnvelope:
    return SwarmEnvelope(
        event_id=uuid.uuid4().hex,
        intent=intent,
        chat_id=chat_id,
        thread_id=thread_id,
        text=text,
        origin_agent=origin_agent,
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )


def append_swarm_envelope(path: Path, envelope: SwarmEnvelope) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = msgspec.json.encode(envelope) + b"\n"
    with path.open("ab") as handle:
        handle.write(line)
        handle.flush()


def _to_synthetic_message(
    envelope: SwarmEnvelope,
    *,
    message_id: int,
) -> TelegramIncomingMessage | None:
    if envelope.intent != "trigger":
        return None
    if not envelope.text.strip():
        logger.debug(
            "swarm.ingress.skip",
            reason="empty_text",
            event_id=envelope.event_id,
            chat_id=envelope.chat_id,
            thread_id=envelope.thread_id,
        )
        return None
    return TelegramIncomingMessage(
        transport="telegram",
        chat_id=envelope.chat_id,
        message_id=message_id,
        text=envelope.text,
        reply_to_message_id=None,
        reply_to_text=None,
        sender_id=None,
        thread_id=envelope.thread_id,
        raw={"swarm": msgspec.to_builtins(envelope)},
        ingress_source="swarm",
        ingress_intent=envelope.intent,
        origin_agent=envelope.origin_agent,
    )


def _read_chunk(path: Path, *, offset: int) -> tuple[bytes, int]:
    with path.open("rb") as handle:
        handle.seek(0, 2)
        size = handle.tell()
        if size < offset:
            offset = 0
        handle.seek(offset)
        chunk = handle.read()
    return chunk, offset + len(chunk)


async def poll_swarm_inbox(
    cfg: SwarmIngressConfig,
    *,
    sleep: Callable[[float], Awaitable[None]] = anyio.sleep,
) -> AsyncIterator[TelegramIncomingMessage]:
    offset = 0
    remainder = b""
    next_message_id = -1
    while True:
        try:
            chunk, offset = _read_chunk(cfg.inbox_path, offset=offset)
        except FileNotFoundError:
            offset = 0
            remainder = b""
            await sleep(cfg.poll_interval_s)
            continue

        if chunk:
            payload = remainder + chunk
            lines = payload.split(b"\n")
            remainder = lines.pop() if lines else b""
            for line in lines:
                raw_line = line.strip()
                if not raw_line:
                    continue
                try:
                    envelope = msgspec.json.decode(raw_line, type=SwarmEnvelope)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "swarm.ingress.decode_failed",
                        path=str(cfg.inbox_path),
                        error=str(exc),
                        error_type=exc.__class__.__name__,
                    )
                    continue
                message = _to_synthetic_message(
                    envelope,
                    message_id=next_message_id,
                )
                if message is None:
                    continue
                next_message_id -= 1
                yield message

        await sleep(cfg.poll_interval_s)
