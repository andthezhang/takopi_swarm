# takopi_swarm

Fork of [banteg/takopi](https://github.com/banteg/takopi) with swarm orchestration for cross-topic agent coordination in Telegram.

## why swarm on top of takopi

Takopi gives you a single-agent Telegram bridge — one human sends a message, one agent works on it, and replies back. That model breaks down when you need multiple agents collaborating across repos or branches. For example:

- A **manager agent** plans work, splits it into subtasks, and dispatches each to a worker agent in its own Telegram topic.
- A **worker agent** finishes its task and notifies the manager that it's done, triggering the next step.
- Several agents work **in parallel** on different branches of the same repo, each in its own isolated worktree and topic thread.

Takopi alone has no concept of agent-to-agent communication. It only listens for human messages from the Telegram Bot API. The swarm layer solves this by adding two primitives:

| Primitive | What it does | Sent to AI loop |
|-----------|-------------|--------------|
| **control** | Sends a visible bot message to a topic (coordination, status updates) | No |
| **trigger** | Injects a synthetic prompt into Takopi's event loop via a JSONL inbox file | Yes |

With these two primitives, any agent (or script) can create topics, post coordination notes, and kick off work in other topics — turning a single-agent bridge into a multi-agent swarm.

### why not a takopi plugin?

takopi has a plugin system for adding new engines, transports, and commands. the swarm doesn't fit any of those:

- **plugins react to messages — swarm creates them.** the swarm layer adds a new message source (the JSONL inbox) into the main event loop. plugins can only handle messages that already arrived; they can't inject new ones.
- **plugins run inside takopi — swarm CLI runs outside.** commands like `takopi swarm trigger send` work without a running takopi instance. they just write to a file or call the telegram API. the plugin system doesn't have CLI extension points.
- **plugins get a scoped API — swarm needs core internals.** the swarm service talks directly to `TopicStateStore`, `TelegramClient`, and the config system. plugins only see the public `takopi.api` surface.

in short: plugins extend takopi sideways (new engines, new commands). swarm extends it through the core — it adds a new way for messages to enter the system.

### why bot messages, not user messages?

control messages are sent *as the bot*, not as you. two reasons:

- **telegram bots can only send as themselves.** the bot API doesn't support sending messages as a user. that would require a full telegram user client (MTProto), which is a completely different auth model. takopi only has a bot token.
- **it's better for readability.** bot messages look different in telegram — different name, different avatar. when a topic has both human instructions and swarm coordination notes, you can instantly tell them apart. if everything came from "you," the history would be confusing.

trigger messages don't appear in telegram at all. they write to a local file and get picked up by the running takopi loop internally. no chat noise — the agent just starts working.

## how bot messages work

### message flow (human → agent)

```
Telegram message
  → TelegramClient polls updates
  → TelegramIncomingMessage (types.py)
  → run_main_loop dispatches
    → slash command? → command handler
    → otherwise → ThreadScheduler queues a job
      → runner_bridge spawns the agent CLI (claude/codex/opencode/pi)
      → agent streams JSONL events back
      → TelegramPresenter renders progress → edits the Telegram message live
      → final answer sent, progress message deleted
```

### message flow (swarm trigger → agent)

```
takopi swarm trigger send "do the thing" --chat-id 123 --thread-id 456
  → writes a SwarmEnvelope (intent="trigger") to the JSONL inbox file
  → poll_swarm_inbox() reads the inbox (polling every 0.35s)
  → converts envelope to a synthetic TelegramIncomingMessage
  → feeds it into the same run_main_loop pipeline as a human message
  → agent runs, replies in the topic thread
```

The trigger path reuses 100% of the existing runner/scheduler/presenter pipeline. From the agent's perspective there is no difference between a human prompt and a swarm trigger.

### control messages

Control messages use the Telegram Bot API directly — the bot posts a message to the target topic. They are informational and never start a run:

```
takopi swarm control send "[manager] auth subtask complete" \
  --chat-id 123 --thread-id 456
```

### SwarmEnvelope

Each swarm message (control or trigger) is a structured JSONL record:

```json
{
  "version": 1,
  "event_id": "a1b2c3...",
  "intent": "trigger",
  "chat_id": 123,
  "thread_id": 456,
  "text": "Implement JWT auth middleware",
  "origin_agent": "manager",
  "created_at": "2026-03-01T12:00:00+00:00"
}
```

- `intent`: `"control"` (bot message only) or `"trigger"` (starts agent work)
- `origin_agent`: label identifying which agent sent it (optional, for tracing)
- `thread_id`: the Telegram forum topic thread to target

## features

- projects and worktrees: work on multiple repos/branches simultaneously, branches are git worktrees
- stateless resume: continue in chat or copy the resume line to pick up in terminal
- progress streaming: commands, tools, file changes, elapsed time
- parallel runs across agent sessions, per-agent-session queue
- works with telegram features like voice notes and scheduled messages
- file transfer: send files to the repo or fetch files/dirs back
- group chats and topics: map group topics to repo/branch contexts
- works with existing anthropic and openai subscriptions
- **swarm orchestration**: agent-to-agent coordination via control/trigger primitives

## requirements

`uv` for installation (`curl -LsSf https://astral.sh/uv/install.sh | sh`)

python 3.14+ (`uv python install 3.14`)

at least one engine on PATH: `codex`, `claude`, `opencode`, or `pi`

## install

```sh
uv tool install -U takopi
```

## setup

run `takopi` and follow the setup wizard. it will help you:

1. create a bot token via @BotFather
2. pick a workflow (assistant, workspace, or handoff)
3. connect your chat
4. choose a default engine

workflows configure conversation mode, topics, and resume lines automatically:

- **assistant**: ongoing chat with auto-resume (recommended)
- **workspace**: forum topics bound to repos/branches
- **handoff**: reply-to-continue with terminal resume lines

### enable swarm ingress

add to your `takopi.toml`:

```toml
[plugins.swarm]
enabled = true
# inbox_path = "telegram_swarm_inbox.jsonl"   # optional, defaults to same dir as config
# poll_interval_s = 0.35                       # optional
```

## usage

```sh
cd ~/dev/happy-gadgets
takopi
```

send a message to your bot. prefix with `/codex`, `/claude`, `/opencode`, or `/pi` to pick an engine. reply to continue a thread.

register a project with `takopi init happy-gadgets`, then target it from anywhere with `/happy-gadgets hard reset the timeline`.

mention a branch to run an agent in a dedicated worktree `/happy-gadgets @feat/memory-box freeze artifacts forever`.

inspect or update settings with `takopi config list`, `takopi config get`, and `takopi config set`.

see [takopi.dev](https://takopi.dev/) for configuration, worktrees, topics, file transfer, and more.

## swarm CLI

### topic management

```sh
# list all tracked topics
takopi swarm topics list --json

# create or reuse a topic for a project + branch
takopi swarm topics ensure --project api --branch feat/auth --json

# check a single topic's status
takopi swarm topics status --chat-id 123 --thread-id 456 --json
```

topic titles follow the format `project_alias @branch` (or just `project_alias` if no branch).

### control messages

```sh
# send a coordination message (does NOT start a run)
takopi swarm control send "[manager] implement auth middleware" \
  --chat-id 123 --thread-id 456
```

### trigger messages

```sh
# inject a runnable prompt (STARTS a run)
takopi swarm trigger send "Implement JWT auth middleware + tests" \
  --chat-id 123 --thread-id 456 --origin-agent manager
```

### example workflow

```sh
# 1. ensure a topic exists for the project/branch
takopi swarm topics ensure --project api --branch feat/auth --json
# → returns chat_id, thread_id

# 2. post a coordination note
takopi swarm control send "[manager] implement auth" \
  --chat-id 123 --thread-id 456

# 3. trigger actual work
takopi swarm trigger send "Implement JWT auth middleware" \
  --chat-id 123 --thread-id 456 --origin-agent manager

# 4. check status
takopi swarm topics status --chat-id 123 --thread-id 456 --json
```

### rule of thumb

- use `control` for coordination text (status updates, handoff notes)
- use `trigger` for actionable work prompts (starts agent runs)
- `main` and `master` stay in repo root; other branches use worktrees

## plugins

takopi supports entrypoint-based plugins for engines, transports, and commands.

see [`docs/how-to/write-a-plugin.md`](docs/how-to/write-a-plugin.md) and [`docs/reference/plugin-api.md`](docs/reference/plugin-api.md).

## development

see [`docs/reference/specification.md`](docs/reference/specification.md) and [`docs/developing.md`](docs/developing.md).
