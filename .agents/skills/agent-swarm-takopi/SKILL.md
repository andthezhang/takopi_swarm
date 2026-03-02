---
name: agent-swarm-takopi
description: Agent swarm orchestration for coding agents and subagents: create worker topics, send agent-to-agent coordination messages, and trigger runnable tasks via Takopi CLI.
---

# agent-swarm-takopi

Use this skill when one coding agent needs to coordinate other agents/subagents in Telegram topics.

## Quick model

- `control`: send a visible coordination message to a topic.
- `trigger`: inject a runnable prompt into Takopi loop (starts work).

## Core commands

```bash
# list tracked topics
takopi swarm topics list --json

# create or reuse topic for project + branch
takopi swarm topics ensure --project <project> --branch <branch> --json

# send coordination note (does not start a run by itself)
takopi swarm control send "[manager] pick up task" \
  --chat-id <chat_id> --thread-id <thread_id> --json

# send actual task prompt (starts work)
takopi swarm trigger send "<concrete task prompt>" \
  --chat-id <chat_id> --thread-id <thread_id> --origin-agent manager --json

# inspect one worker topic
takopi swarm topics status --chat-id <chat_id> --thread-id <thread_id> --json
```

## Example

1. Ensure topic: `takopi swarm topics ensure --project api --branch feat/auth --json`
2. Control note: `takopi swarm control send "[manager] implement auth middleware" --chat-id <chat_id> --thread-id <thread_id> --json`
3. Trigger task: `takopi swarm trigger send "Implement JWT auth middleware + tests" --chat-id <chat_id> --thread-id <thread_id> --origin-agent manager --json`
4. Check status: `takopi swarm topics status --chat-id <chat_id> --thread-id <thread_id> --json`

## Rule of thumb

- Use `control` for coordination text.
- Use `trigger` for actionable work prompts.
- `main` and `master` stay in repo root; other branches use worktrees.
