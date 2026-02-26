from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import ConfigError
from ..transport_runtime import TransportRuntime

SWARM_PLUGIN_ID = "swarm"
DEFAULT_INBOX_FILENAME = "telegram_swarm_inbox.jsonl"
DEFAULT_POLL_INTERVAL_S = 0.35


@dataclass(frozen=True, slots=True)
class SwarmIngressConfig:
    inbox_path: Path
    poll_interval_s: float


def _resolve_inbox_path(value: object, *, config_path: Path) -> Path:
    if value is None:
        return config_path.with_name(DEFAULT_INBOX_FILENAME)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(
            f"Invalid `plugins.{SWARM_PLUGIN_ID}.inbox_path` in {config_path}; "
            "expected a non-empty string."
        )
    raw_path = Path(value).expanduser()
    if raw_path.is_absolute():
        return raw_path
    return config_path.parent / raw_path


def _resolve_poll_interval(value: object, *, config_path: Path) -> float:
    if value is None:
        return DEFAULT_POLL_INTERVAL_S
    if not isinstance(value, int | float):
        raise ConfigError(
            f"Invalid `plugins.{SWARM_PLUGIN_ID}.poll_interval_s` in {config_path}; "
            "expected a number."
        )
    poll_interval = float(value)
    if poll_interval <= 0:
        raise ConfigError(
            f"Invalid `plugins.{SWARM_PLUGIN_ID}.poll_interval_s` in {config_path}; "
            "expected a value > 0."
        )
    return poll_interval


def parse_swarm_ingress_config(
    raw: dict[str, Any] | None,
    *,
    config_path: Path,
) -> SwarmIngressConfig | None:
    if raw is None:
        return None
    enabled = raw.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ConfigError(
            f"Invalid `plugins.{SWARM_PLUGIN_ID}.enabled` in {config_path}; "
            "expected true/false."
        )
    if not enabled:
        return None

    inbox_path = _resolve_inbox_path(raw.get("inbox_path"), config_path=config_path)
    poll_interval_s = _resolve_poll_interval(
        raw.get("poll_interval_s"), config_path=config_path
    )
    return SwarmIngressConfig(inbox_path=inbox_path, poll_interval_s=poll_interval_s)


def resolve_swarm_ingress_config(runtime: TransportRuntime) -> SwarmIngressConfig | None:
    config_path = runtime.config_path
    if config_path is None:
        return None
    return parse_swarm_ingress_config(
        runtime.plugin_config(SWARM_PLUGIN_ID),
        config_path=config_path,
    )


def resolve_swarm_ingress_config_from_plugins(
    plugin_configs: dict[str, Any] | None,
    *,
    config_path: Path,
) -> SwarmIngressConfig | None:
    if not plugin_configs:
        return None
    raw = plugin_configs.get(SWARM_PLUGIN_ID)
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ConfigError(
            f"Invalid `plugins.{SWARM_PLUGIN_ID}` in {config_path}; expected a table."
        )
    return parse_swarm_ingress_config(raw, config_path=config_path)
