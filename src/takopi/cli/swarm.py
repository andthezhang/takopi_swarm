from __future__ import annotations

import json
from pathlib import Path

import anyio
import typer

from ..config import ConfigError, ProjectsConfig
from ..engines import list_backend_ids
from ..runtime_loader import resolve_plugins_allowlist
from ..settings import TakopiSettings, load_settings
from ..telegram.client import TelegramClient
from ..telegram.topic_state import TopicStateStore, resolve_state_path
from ..swarm.config import resolve_swarm_ingress_config_from_plugins
from ..swarm.inbox import append_swarm_envelope, new_swarm_envelope
from ..swarm.service import (
    TopicStatus,
    ensure_topic_thread,
    list_topic_statuses,
    normalize_branch,
    send_control_message,
    snapshot_to_status,
)
from .config import _CONFIG_PATH_OPTION, _config_path_display, _exit_config_error


def _load_settings_for_swarm(
    config_path: Path | None,
) -> tuple[TakopiSettings, Path]:
    try:
        return load_settings(path=config_path)
    except ConfigError as exc:
        _exit_config_error(exc)
    raise AssertionError("unreachable")


def _resolve_projects(
    settings: TakopiSettings,
    *,
    config_path: Path,
) -> ProjectsConfig:
    allowlist = resolve_plugins_allowlist(settings)
    engine_ids = list_backend_ids(allowlist=allowlist)
    return settings.to_projects_config(config_path=config_path, engine_ids=engine_ids)


def _project_aliases(projects: ProjectsConfig) -> dict[str, str]:
    return {key: project.alias for key, project in projects.projects.items()}


def _status_for_output(status: TopicStatus) -> dict[str, object]:
    return status.to_dict()


def _echo_status_lines(status: TopicStatus) -> None:
    ctx = "-"
    if status.project is not None:
        ctx = status.project
        if status.branch:
            ctx = f"{ctx}@{status.branch}"
    sessions = ", ".join(status.sessions) if status.sessions else "none"
    title = status.topic_title or "-"
    default_engine = status.default_engine or "-"
    typer.echo(
        f"{status.chat_id}:{status.thread_id}  ctx={ctx}  "
        f"title={title!r}  default_engine={default_engine}  sessions={sessions}"
    )


def _json_dump(payload: object) -> None:
    typer.echo(json.dumps(payload, sort_keys=True))


def _resolve_target_chat_id(
    *,
    settings: TakopiSettings,
    projects: ProjectsConfig,
    project_key: str | None,
    chat_id: int | None,
) -> int:
    if chat_id is not None:
        return chat_id
    if project_key is not None:
        project_cfg = projects.projects.get(project_key)
        if project_cfg is not None and project_cfg.chat_id is not None:
            return project_cfg.chat_id
    return int(settings.transports.telegram.chat_id)


def _resolve_project(
    project: str,
    projects: ProjectsConfig,
) -> tuple[str, str]:
    key = project.strip().lower()
    cfg = projects.projects.get(key)
    if cfg is None:
        available = ", ".join(sorted(projects.projects)) or "none"
        raise ConfigError(
            f"Unknown project {project!r}. Available project ids: {available}."
        )
    return key, cfg.alias


def _resolve_swarm_ingress_or_raise(
    *,
    settings: TakopiSettings,
    config_path: Path,
):
    try:
        return resolve_swarm_ingress_config_from_plugins(
            settings.plugins.model_extra,
            config_path=config_path,
        )
    except ConfigError as exc:
        _exit_config_error(exc)
    raise AssertionError("unreachable")


def create_swarm_app() -> typer.Typer:
    app = typer.Typer(help="Swarm helpers for topic orchestration and agent triggers.")
    topics_app = typer.Typer(help="Inspect and manage topic bindings.")
    control_app = typer.Typer(help="Send bot-plane control messages to Telegram.")
    trigger_app = typer.Typer(help="Send trigger-plane synthetic prompts to Takopi.")

    @topics_app.command(name="list")
    def topics_list(
        chat_id: int | None = typer.Option(
            None,
            "--chat-id",
            help="Filter tracked topics by chat id.",
        ),
        as_json: bool = typer.Option(False, "--json", help="Output JSON."),
        config_path: Path | None = _CONFIG_PATH_OPTION,
    ) -> None:
        """List tracked topics from topic state."""
        settings, resolved_config_path = _load_settings_for_swarm(config_path)
        try:
            projects = _resolve_projects(settings, config_path=resolved_config_path)
        except ConfigError as exc:
            _exit_config_error(exc)

        store = TopicStateStore(resolve_state_path(resolved_config_path))
        async def _run() -> list[TopicStatus]:
            return await list_topic_statuses(
                store=store,
                project_aliases=_project_aliases(projects),
                chat_id=chat_id,
            )

        statuses = anyio.run(_run)
        if as_json:
            _json_dump([_status_for_output(status) for status in statuses])
            return
        if not statuses:
            typer.echo("no tracked topics")
            return
        for status in statuses:
            _echo_status_lines(status)

    @topics_app.command(name="status")
    def topics_status(
        chat_id: int = typer.Option(..., "--chat-id", help="Chat id."),
        thread_id: int = typer.Option(..., "--thread-id", help="Thread id."),
        as_json: bool = typer.Option(False, "--json", help="Output JSON."),
        config_path: Path | None = _CONFIG_PATH_OPTION,
    ) -> None:
        """Show a single topic thread status."""
        settings, resolved_config_path = _load_settings_for_swarm(config_path)
        try:
            projects = _resolve_projects(settings, config_path=resolved_config_path)
        except ConfigError as exc:
            _exit_config_error(exc)

        store = TopicStateStore(resolve_state_path(resolved_config_path))
        snapshot = anyio.run(store.get_thread, chat_id, thread_id)
        if snapshot is None:
            typer.echo("topic not found", err=True)
            raise typer.Exit(code=1)
        status = snapshot_to_status(snapshot, project_aliases=_project_aliases(projects))
        if as_json:
            _json_dump(_status_for_output(status))
            return
        _echo_status_lines(status)

    @topics_app.command(name="ensure")
    def topics_ensure(
        project: str = typer.Option(..., "--project", help="Project alias/id."),
        branch: str | None = typer.Option(
            None,
            "--branch",
            help="Optional branch name for the topic binding.",
        ),
        chat_id: int | None = typer.Option(
            None,
            "--chat-id",
            help="Target chat id (defaults to project chat_id or main chat).",
        ),
        bind_state: bool = typer.Option(
            True,
            "--bind-state/--no-bind-state",
            help="Persist topic->context binding in Takopi state.",
        ),
        as_json: bool = typer.Option(False, "--json", help="Output JSON."),
        config_path: Path | None = _CONFIG_PATH_OPTION,
    ) -> None:
        """Ensure a project/branch topic exists in Telegram."""
        settings, resolved_config_path = _load_settings_for_swarm(config_path)
        try:
            projects = _resolve_projects(settings, config_path=resolved_config_path)
            project_key, project_alias = _resolve_project(project, projects)
        except ConfigError as exc:
            _exit_config_error(exc)

        target_chat_id = _resolve_target_chat_id(
            settings=settings,
            projects=projects,
            project_key=project_key,
            chat_id=chat_id,
        )
        normalized_branch = normalize_branch(branch)
        state_path = resolve_state_path(resolved_config_path)
        token = settings.transports.telegram.bot_token

        async def _run() -> tuple[TopicStatus, bool]:
            bot = TelegramClient(token)
            store = TopicStateStore(state_path)
            try:
                return await ensure_topic_thread(
                    bot=bot,
                    store=store,
                    chat_id=target_chat_id,
                    project_key=project_key,
                    project_alias=project_alias,
                    branch=normalized_branch,
                    bind_state=bind_state,
                )
            finally:
                await bot.close()

        try:
            status, created = anyio.run(_run)
        except (ConfigError, RuntimeError) as exc:
            _exit_config_error(ConfigError(str(exc)))

        payload = {
            "created": created,
            "status": _status_for_output(status),
            "state_path": str(state_path),
        }
        if as_json:
            _json_dump(payload)
            return
        action = "created" if created else "reused"
        typer.echo(
            f"{action} topic {status.chat_id}:{status.thread_id} "
            f"for {status.project or project_alias}"
            + (f" @{status.branch}" if status.branch else "")
        )

    @control_app.command(name="send")
    def control_send(
        text: str = typer.Argument(..., help="Message text."),
        chat_id: int | None = typer.Option(
            None,
            "--chat-id",
            help="Target chat id (defaults to main chat).",
        ),
        thread_id: int | None = typer.Option(
            None,
            "--thread-id",
            help="Target thread id in forum chats.",
        ),
        notify: bool = typer.Option(
            True,
            "--notify/--silent",
            help="Send with notification on/off.",
        ),
        as_json: bool = typer.Option(False, "--json", help="Output JSON."),
        config_path: Path | None = _CONFIG_PATH_OPTION,
    ) -> None:
        """Send a control-plane Telegram message as the bot."""
        settings, resolved_config_path = _load_settings_for_swarm(config_path)
        try:
            projects = _resolve_projects(settings, config_path=resolved_config_path)
        except ConfigError as exc:
            _exit_config_error(exc)
        target_chat_id = _resolve_target_chat_id(
            settings=settings,
            projects=projects,
            project_key=None,
            chat_id=chat_id,
        )
        token = settings.transports.telegram.bot_token

        async def _run() -> int | None:
            bot = TelegramClient(token)
            try:
                return await send_control_message(
                    bot=bot,
                    chat_id=target_chat_id,
                    thread_id=thread_id,
                    text=text,
                    notify=notify,
                )
            finally:
                await bot.close()

        message_id = anyio.run(_run)
        if as_json:
            _json_dump(
                {
                    "chat_id": target_chat_id,
                    "thread_id": thread_id,
                    "message_id": message_id,
                }
            )
            return
        if message_id is None:
            typer.echo("control message failed", err=True)
            raise typer.Exit(code=1)
        typer.echo(
            f"sent control message to chat {target_chat_id}"
            + (f" thread {thread_id}" if thread_id is not None else "")
            + f" (message_id={message_id})"
        )

    @trigger_app.command(name="send")
    def trigger_send(
        text: str = typer.Argument(..., help="Prompt text injected into Takopi loop."),
        chat_id: int | None = typer.Option(
            None,
            "--chat-id",
            help="Target chat id (defaults to main chat).",
        ),
        thread_id: int | None = typer.Option(
            None,
            "--thread-id",
            help="Target thread id in forum chats.",
        ),
        origin_agent: str | None = typer.Option(
            None,
            "--origin-agent",
            help="Optional source label written into ingress metadata.",
        ),
        as_json: bool = typer.Option(False, "--json", help="Output JSON."),
        config_path: Path | None = _CONFIG_PATH_OPTION,
    ) -> None:
        """Queue a synthetic trigger message for Takopi's local swarm ingress."""
        settings, resolved_config_path = _load_settings_for_swarm(config_path)
        try:
            projects = _resolve_projects(settings, config_path=resolved_config_path)
        except ConfigError as exc:
            _exit_config_error(exc)

        ingress_cfg = _resolve_swarm_ingress_or_raise(
            settings=settings,
            config_path=resolved_config_path,
        )
        if ingress_cfg is None:
            message = (
                "swarm trigger ingress is disabled; set "
                "`[plugins.swarm] enabled = true` in "
                f"{_config_path_display(resolved_config_path)}"
            )
            typer.echo(f"error: {message}", err=True)
            raise typer.Exit(code=2)

        target_chat_id = _resolve_target_chat_id(
            settings=settings,
            projects=projects,
            project_key=None,
            chat_id=chat_id,
        )
        envelope = new_swarm_envelope(
            intent="trigger",
            chat_id=target_chat_id,
            thread_id=thread_id,
            text=text,
            origin_agent=origin_agent,
        )
        append_swarm_envelope(ingress_cfg.inbox_path, envelope)

        payload = {
            "event_id": envelope.event_id,
            "chat_id": target_chat_id,
            "thread_id": thread_id,
            "inbox_path": str(ingress_cfg.inbox_path),
        }
        if as_json:
            _json_dump(payload)
            return
        typer.echo(
            f"queued trigger {envelope.event_id} for chat {target_chat_id}"
            + (f" thread {thread_id}" if thread_id is not None else "")
            + f" via {ingress_cfg.inbox_path}"
        )

    app.add_typer(topics_app, name="topics")
    app.add_typer(control_app, name="control")
    app.add_typer(trigger_app, name="trigger")
    return app
