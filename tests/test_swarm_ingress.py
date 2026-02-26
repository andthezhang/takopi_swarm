from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import anyio
import pytest

from takopi.telegram.bridge import run_main_loop
from takopi.telegram.chat_prefs import ChatPrefsStore, resolve_prefs_path
from takopi.transport_runtime import TransportRuntime
from takopi.runners.mock import Return, ScriptRunner
from takopi.swarm.config import (
    parse_swarm_ingress_config,
    resolve_swarm_ingress_config_from_plugins,
)
from takopi.swarm.inbox import (
    append_swarm_envelope,
    new_swarm_envelope,
    poll_swarm_inbox,
)
from tests.telegram_fakes import _empty_projects, _make_router, make_cfg, FakeTransport


def test_parse_swarm_ingress_config_enabled(tmp_path: Path) -> None:
    config_path = tmp_path / "takopi.toml"
    parsed = parse_swarm_ingress_config(
        {
            "enabled": True,
            "inbox_path": "state/swarm.jsonl",
            "poll_interval_s": 0.2,
        },
        config_path=config_path,
    )
    assert parsed is not None
    assert parsed.inbox_path == config_path.parent / "state/swarm.jsonl"
    assert parsed.poll_interval_s == 0.2


def test_resolve_swarm_ingress_config_from_plugins_none_when_disabled(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "takopi.toml"
    parsed = resolve_swarm_ingress_config_from_plugins(
        {"swarm": {"enabled": False}},
        config_path=config_path,
    )
    assert parsed is None


@pytest.mark.anyio
async def test_poll_swarm_inbox_yields_trigger_message(tmp_path: Path) -> None:
    inbox = tmp_path / "swarm-inbox.jsonl"
    trigger = new_swarm_envelope(
        intent="trigger",
        chat_id=123,
        thread_id=19,
        text="hello from swarm",
        origin_agent="manager",
    )
    control = new_swarm_envelope(
        intent="control",
        chat_id=123,
        thread_id=19,
        text="control only",
        origin_agent=None,
    )
    append_swarm_envelope(inbox, control)
    append_swarm_envelope(inbox, trigger)

    cfg = parse_swarm_ingress_config(
        {"enabled": True, "inbox_path": str(inbox), "poll_interval_s": 0.01},
        config_path=tmp_path / "takopi.toml",
    )
    assert cfg is not None

    stream = poll_swarm_inbox(cfg)
    with anyio.fail_after(1):
        message = await anext(stream)
    await stream.aclose()

    assert message.chat_id == 123
    assert message.thread_id == 19
    assert message.text == "hello from swarm"
    assert message.ingress_source == "swarm"
    assert message.ingress_intent == "trigger"
    assert message.origin_agent == "manager"


@pytest.mark.anyio
async def test_run_main_loop_consumes_swarm_trigger_with_mentions_mode(
    tmp_path: Path,
) -> None:
    transport = FakeTransport()
    runner = ScriptRunner([Return(answer="ok")], engine="codex")
    cfg = make_cfg(transport, runner)

    config_path = tmp_path / "takopi.toml"
    config_path.write_text("", encoding="utf-8")
    inbox_path = tmp_path / "swarm-inbox.jsonl"

    runtime = TransportRuntime(
        router=_make_router(runner),
        projects=_empty_projects(),
        config_path=config_path,
        plugin_configs={
            "swarm": {
                "enabled": True,
                "inbox_path": str(inbox_path),
                "poll_interval_s": 0.01,
            }
        },
    )
    cfg = replace(cfg, runtime=runtime, allowed_user_ids=(999,))

    prefs = ChatPrefsStore(resolve_prefs_path(config_path))
    await prefs.set_trigger_mode(cfg.chat_id, "mentions")

    stop = anyio.Event()

    async def poller(_cfg):
        await stop.wait()
        if False:
            yield  # pragma: no cover

    trigger = new_swarm_envelope(
        intent="trigger",
        chat_id=cfg.chat_id,
        thread_id=19,
        text="run this despite mentions mode",
        origin_agent="manager",
    )

    async with anyio.create_task_group() as tg:
        tg.start_soon(run_main_loop, cfg, poller)
        try:
            append_swarm_envelope(inbox_path, trigger)
            with anyio.fail_after(2):
                while not runner.calls:
                    await anyio.sleep(0.01)
            assert runner.calls[0][0] == "run this despite mentions mode"
        finally:
            stop.set()
            tg.cancel_scope.cancel()
