from __future__ import annotations

from dataclasses import dataclass

from ..context import RunContext
from ..telegram.topic_state import TopicStateStore, TopicThreadSnapshot
from ..telegram.client import TelegramClient


@dataclass(frozen=True, slots=True)
class TopicStatus:
    chat_id: int
    thread_id: int
    project: str | None
    branch: str | None
    topic_title: str | None
    default_engine: str | None
    sessions: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "chat_id": self.chat_id,
            "thread_id": self.thread_id,
            "project": self.project,
            "branch": self.branch,
            "topic_title": self.topic_title,
            "default_engine": self.default_engine,
            "sessions": list(self.sessions),
        }


def normalize_branch(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def build_topic_title(*, project_alias: str, branch: str | None) -> str:
    if branch:
        return f"{project_alias} @{branch}"
    return project_alias


def snapshot_to_status(
    snapshot: TopicThreadSnapshot,
    *,
    project_aliases: dict[str, str],
) -> TopicStatus:
    project_key = snapshot.context.project if snapshot.context is not None else None
    project = (
        project_aliases.get(project_key, project_key) if project_key is not None else None
    )
    branch = snapshot.context.branch if snapshot.context is not None else None
    sessions = tuple(sorted(snapshot.sessions))
    return TopicStatus(
        chat_id=snapshot.chat_id,
        thread_id=snapshot.thread_id,
        project=project,
        branch=branch,
        topic_title=snapshot.topic_title,
        default_engine=snapshot.default_engine,
        sessions=sessions,
    )


async def list_topic_statuses(
    *,
    store: TopicStateStore,
    project_aliases: dict[str, str],
    chat_id: int | None,
) -> list[TopicStatus]:
    snapshots = await store.list_threads(chat_id=chat_id)
    return [
        snapshot_to_status(snapshot, project_aliases=project_aliases)
        for snapshot in snapshots
    ]


async def ensure_topic_thread(
    *,
    bot: TelegramClient,
    store: TopicStateStore,
    chat_id: int,
    project_key: str,
    project_alias: str,
    branch: str | None,
    bind_state: bool,
) -> tuple[TopicStatus, bool]:
    context = RunContext(project=project_key, branch=branch)
    title = build_topic_title(project_alias=project_alias, branch=branch)
    existing_thread_id = await store.find_thread_for_context(chat_id, context)
    created = False

    if existing_thread_id is not None:
        renamed = await bot.edit_forum_topic(
            chat_id=chat_id,
            message_thread_id=existing_thread_id,
            name=title,
        )
        if renamed:
            if bind_state:
                await store.set_context(
                    chat_id,
                    existing_thread_id,
                    context,
                    topic_title=title,
                )
            snapshot = await store.get_thread(chat_id, existing_thread_id)
            if snapshot is None:
                snapshot = TopicThreadSnapshot(
                    chat_id=chat_id,
                    thread_id=existing_thread_id,
                    context=context if bind_state else None,
                    sessions={},
                    topic_title=title,
                    default_engine=None,
                )
            status = snapshot_to_status(
                snapshot,
                project_aliases={project_key: project_alias},
            )
            return status, created

        await store.delete_thread(chat_id, existing_thread_id)

    created_topic = await bot.create_forum_topic(chat_id, title)
    if created_topic is None:
        raise RuntimeError("failed to create telegram forum topic")
    thread_id = created_topic.message_thread_id
    created = True
    if bind_state:
        await store.set_context(
            chat_id,
            thread_id,
            context,
            topic_title=title,
        )

    snapshot = await store.get_thread(chat_id, thread_id)
    if snapshot is None:
        snapshot = TopicThreadSnapshot(
            chat_id=chat_id,
            thread_id=thread_id,
            context=context if bind_state else None,
            sessions={},
            topic_title=title,
            default_engine=None,
        )
    status = snapshot_to_status(snapshot, project_aliases={project_key: project_alias})
    return status, created


async def send_control_message(
    *,
    bot: TelegramClient,
    chat_id: int,
    thread_id: int | None,
    text: str,
    notify: bool,
) -> int | None:
    sent = await bot.send_message(
        chat_id=chat_id,
        text=text,
        message_thread_id=thread_id,
        disable_notification=not notify,
    )
    if sent is None:
        return None
    return sent.message_id
