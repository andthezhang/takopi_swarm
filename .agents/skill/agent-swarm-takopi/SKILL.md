---
name: agent-swarm-takopi
description: Agent swarm orchestration for coding agents and subagents: create worker topics, send agent-to-agent coordination messages, and trigger runnable tasks via Takopi CLI.
---

# agent-swarm-takopi

Use this skill when one coding agent needs to coordinate other agents/subagents in Telegram topics.

## Quick model

- `control`: send a visible coordination message to a topic.
- `trigger`: inject a runnable prompt into Takopi loop (starts work).

## CLI

```bash
BIN="takopiswarm"
command -v "$BIN" >/dev/null 2>&1 || BIN="takopi"
```

## Core commands

```bash
# list tracked topics
"$BIN" swarm topics list --json

# create or reuse topic for project + branch
"$BIN" swarm topics ensure --project <project> --branch <branch> --json

# send coordination note (does not start a run by itself)
"$BIN" swarm control send "[manager] pick up task" \
  --chat-id <chat_id> --thread-id <thread_id> --json

# send actual task prompt (starts work)
"$BIN" swarm trigger send "<concrete task prompt>" \
  --chat-id <chat_id> --thread-id <thread_id> --origin-agent manager --json

# inspect one worker topic
"$BIN" swarm topics status --chat-id <chat_id> --thread-id <thread_id> --json
```

## Example

1. Ensure topic: `"$BIN" swarm topics ensure --project api --branch feat/auth --json`
2. Control note: `"$BIN" swarm control send "[manager] implement auth middleware" --chat-id <chat_id> --thread-id <thread_id> --json`
3. Trigger task: `"$BIN" swarm trigger send "Implement JWT auth middleware + tests" --chat-id <chat_id> --thread-id <thread_id> --origin-agent manager --json`
4. Check status: `"$BIN" swarm topics status --chat-id <chat_id> --thread-id <thread_id> --json`

## Rule of thumb

- Use `control` for coordination text.
- Use `trigger` for actionable work prompts.
- `main` and `master` stay in repo root; other branches use worktrees.
