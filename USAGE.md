# arccode Usage Guide

A practical, task-oriented guide to using arccode. For install and a high-level
overview see the [README](README.md); this document goes command by command and
covers real workflows.

- [Install & first run](#install--first-run)
- [Authentication](#authentication)
- [Choosing a model (the router)](#choosing-a-model-the-router)
- [Running tasks](#running-tasks)
- [Interactive chat](#interactive-chat)
- [Agents](#agents)
- [Skills](#skills)
- [Sessions](#sessions)
- [Spawning & orchestration](#spawning--orchestration)
- [MCP servers](#mcp-servers)
- [Hooks](#hooks)
- [Slash commands](#slash-commands)
- [Configuration reference](#configuration-reference)
- [Recipes](#recipes)
- [Troubleshooting](#troubleshooting)

---

## Install & first run

```bash
pipx install arccode          # isolated global CLI (recommended)
# or: pip install arccode

arccode version               # confirm it works
arccode --help                # list all commands
```

Point it at a provider (any one is enough):

```bash
export ANTHROPIC_API_KEY=...   # or OPENAI_API_KEY / OPENROUTER_API_KEY
# or run fully local with Ollama at http://localhost:11434 (no key)
# or log in with OAuth: arccode auth login openai
```

First task:

```bash
arccode run "List the Python files in this repo and summarize what each does"
```

arccode classifies the task, picks a model, runs a tool loop (reading files,
running commands), and prints the result plus token/cost accounting.

---

## Authentication

arccode resolves credentials **per provider**, in this order:

1. **API key** from the environment (always wins):
   `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY`. Ollama needs none.
2. **OAuth login** (subscription-style):

```bash
arccode auth login openai          # PKCE browser flow + local callback
arccode auth login anthropic
arccode auth login github --device # headless / SSH: device-code flow
arccode auth status                # who am I logged in as
arccode auth logout openai
```

Tokens live in `~/.arccode/credentials.json` (mode 0600) and refresh
automatically. OAuth clients are issued by each provider, so set your
`client_id` and any endpoint overrides in `~/.arccode/oauth.json`:

```json
{
  "providers": {
    "openai": {
      "auth_url": "https://auth.openai.com/authorize",
      "token_url": "https://auth.openai.com/oauth/token",
      "client_id": "YOUR_CLIENT_ID",
      "scopes": ["openid", "profile", "offline_access"]
    }
  }
}
```

---

## Choosing a model (the router)

By default arccode picks the model for you from the task's **intent** and
**complexity**, balanced against **capability, cost, and latency**.

See the decision without running anything:

```bash
arccode whichmodel "summarize every file in src/"
# -> bulk-read (cheap/fast): intent=bulk_read ...

arccode whichmodel "design a fault-tolerant migration for the cache layer"
# -> frontier: intent=design complexity=high ...
```

Inspect and price the catalog:

```bash
arccode models
```

Routing policy (tunable in `config.py`):

| Intent | Model tier | Why |
|---|---|---|
| bulk read / summarize | small / cheap | high volume, low stakes |
| implement | mid workhorse | good tools + code, moderate cost |
| design / debug / review | frontier | needs strong reasoning |
| chat | small | latency matters |

Override the router for any run with `-m`:

```bash
arccode run "fix the failing test" -m workhorse      # a catalog key
arccode run "quick question" -m openai:gpt-5-mini    # or a full provider id
```

Add or change models with a YAML override:

```yaml
# my-models.yaml
models:
  fast:
    id: "openai:gpt-5-mini"
    provider: openai
    tier: small
    in_cost: 0.15
    out_cost: 0.6
    ctx: 128000
    strengths: [speed, cheap, tools]
```

```bash
ARCCODE_CONFIG=my-models.yaml arccode run "..." -m fast
```

---

## Running tasks

```bash
arccode run "<task>" [options]
```

| Flag | Meaning |
|---|---|
| `-a, --agent <name>` | Agent to use (default `coordinator`). |
| `-m, --model <key/id>` | Force a model, bypassing the router. |
| `-y, --yes` | Auto-approve "danger" tools (writes, bash). Use in CI/non-interactive. |
| `-v, --verbose` | Show the routing decision and each tool call. |
| `-s, --session <id>` | Persist/resume a session (`new` starts one). |
| `--cwd <dir>` | Working directory for file/shell tools. |
| `--no-mcp` | Skip connecting MCP servers this run. |
| `--max-steps <n>` | Cap the tool loop (default 40). |
| `-q, --quiet` | Print only the final result (no summary/spinner). Good for pipes. |
| `--json` | Emit a JSON object: `result`, `agent`, `files_changed`, `usage`, `session`. |

Examples:

```bash
# implement + verify, auto-approving tool use
arccode run "Add a --json flag to the export command and add a test" -a implementer -y

# see exactly what it is doing
arccode run "Why does the build fail?" -a debugger -v

# keep it read-only and cheap
arccode run "Summarize the architecture" -a researcher

# scripting: capture just the answer, or parse structured output
answer=$(arccode run "Return the current version string" -q)
arccode run "List the top 3 risks" --json | jq -r '.result'
```

Each run prints token counts and estimated USD at the end.

---

## Interactive chat

A REPL that keeps context across turns:

```bash
arccode chat                     # coordinator by default
arccode chat -a architect -v
```

Type `/exit` (or `/quit`) to leave. Every message routes and runs like `run`.
Replies **stream in live** (token by token) when your terminal supports it, and
each turn shows running token/cost totals. In-chat commands: `/agent`, `/model`,
`/agents`, `/models`, `/cost`, `/clear`, `/help`.

---

## Agents

Agents are Markdown files with frontmatter. List what ships:

```bash
arccode agents
```

Built-ins: `coordinator` (default entry), `implementer`, `architect`,
`debugger`, `researcher`, `reviewer`, each pinned to a sensible model tier.

Create your own by dropping a file in the agents registry (or set
`ARCCODE_AGENTS_DIR` to your own folder):

```markdown
---
name: sql-tuner
description: Use for slow queries, indexes, and query plans.
model: frontier-reason      # a catalog key, a full id, or "auto"
effort: high
tools: [read_file, bash, grep, web_search]
skills: [git-commit]
---
You are a Postgres performance expert. Reproduce the slow query, read the plan,
propose an index or rewrite, and verify the improvement with EXPLAIN ANALYZE.
```

Then:

```bash
arccode run "The orders report takes 8s" -a sql-tuner -v
```

An agent can also build another agent at runtime via the `build_agent` tool.

---

## Skills

Skills are reusable instruction packs with **progressive disclosure**: their
one-line descriptions are always in context; the full body loads only when the
agent calls `load_skill`.

```bash
arccode skills                   # list available skills
```

Add one at `skills/registry/<name>/SKILL.md` (or `ARCCODE_SKILLS_DIR`):

```markdown
---
name: api-review
description: Use when reviewing REST API changes. Triggers on endpoint, route, OpenAPI.
---
# API Review
Check: versioning, auth on every route, pagination, error shapes, idempotency,
and that the OpenAPI spec matches the handlers.
```

Import an external skill folder with the `import_skill` tool, or have an agent
author one with `build_skill`.

---

## Sessions

Sessions persist an agent's full message history so you can resume later.

```bash
arccode run "Start reviewing the auth module" -s new
# prints: session 20260809-...    (note the id)

arccode run "Now check the token refresh path" -s 20260809-...
arccode sessions                 # list saved sessions with turn counts + cost
```

History is stored at `~/.arccode/sessions/<id>.json`. Resuming feeds the prior
turns back to the model, so it remembers the earlier context.

---

## Spawning & orchestration

The coordinator can decompose work and delegate to specialists, each routed to
its own model. You can also invoke a specialist directly:

```bash
arccode spawn debugger "pytest fails in test_auth with a KeyError" -v
arccode spawn researcher "Summarize how sessions are stored"
```

Inside a run, the coordinator uses the `spawn_agent` tool to fan out subtasks
(e.g. researcher to gather context, implementer to change code, reviewer to
check it). Spawns are depth-limited to avoid runaway trees.

---

## MCP servers

arccode is an MCP client. Declare servers in `~/.arccode/mcp.json`:

```json
{
  "servers": {
    "fs": {
      "command": ["npx", "-y", "@modelcontextprotocol/server-filesystem", "."]
    }
  }
}
```

```bash
arccode mcp                      # list connected servers and their tools
```

Each MCP tool is exposed to agents as `mcp__<server>__<tool>`. Disable for a run
with `--no-mcp`.

---

## Hooks

Shell commands that fire on tool lifecycle events. Config in
`~/.arccode/hooks.json` or `./.arccode/hooks.json`:

```json
{
  "PreToolUse": [
    { "match": "bash", "command": "case \"$0\" in *'rm -rf'*) exit 2;; esac" }
  ],
  "PostToolUse": [
    { "match": "write_file", "command": "echo 'file written' >> ~/.arccode/audit.log" }
  ]
}
```

A non-zero exit on `PreToolUse` **blocks** the tool. Use it for guardrails,
auditing, or formatting after writes.

---

## Slash commands

Reusable prompt templates. Create `./.arccode/commands/<name>.md`:

```markdown
Review $ARGUMENTS for security issues, then list blocking findings only.
```

Then in a run or chat, `/review the login flow` expands to the template with
`$ARGUMENTS` replaced.

---

## Configuration reference

| Path / var | Purpose |
|---|---|
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY` | Provider API keys. |
| `ARCCODE_CONFIG` | YAML file adding/overriding models. |
| `ARCCODE_AGENTS_DIR` | Extra agents directory. |
| `ARCCODE_SKILLS_DIR` | Extra skills directory. |
| `ARCCODE_HOME` | Base dir (default `~/.arccode`). |
| `~/.arccode/credentials.json` | OAuth tokens (0600). |
| `~/.arccode/oauth.json` | OAuth client config per provider. |
| `~/.arccode/mcp.json` | MCP servers. |
| `~/.arccode/hooks.json` | Global hooks. |
| `./.arccode/hooks.json` | Project hooks. |
| `./.arccode/commands/*.md` | Slash commands. |
| `~/.arccode/sessions/*.json` | Saved sessions. |

---

## Recipes

**Fully local, private, no keys:**
```bash
ollama pull qwen2.5-coder
ARCCODE_CONFIG=examples/ollama-local.yaml arccode run "refactor utils.py" -m qwen-small -y
```

**CI check (non-interactive, auto-approve, fail loudly):**
```bash
arccode run "Run the test suite and report failures" -a debugger -y --no-mcp
```

**Cheap bulk digest of a big repo:**
```bash
arccode run "Summarize each module under src/ in one line" -a researcher
```

**Design then implement in one session:**
```bash
arccode run "Design a rate limiter for 10k rps" -a architect -s new
arccode run "Now implement the design you proposed" -a implementer -s <id> -y
```

---

## Troubleshooting

**"No credentials for <provider>"** — set the API key env var or
`arccode auth login <provider>`. For local use, start Ollama.

**"provider call failed (... 4xx/410)"** — the model id is wrong or retired.
Check `arccode models` and your `ARCCODE_CONFIG`; override with `-m`.

**A tool is blocked** — a hook or the built-in destructive-command guard
stopped it. Check `~/.arccode/hooks.json`. Danger tools also need `-y` (or an
interactive `y`) to run.

**Nothing happens / loops to max steps** — raise `--max-steps`, or use `-v` to
see where the loop stalls. A weak local model may not emit tool calls reliably;
try a stronger model with `-m`.

**Cost surprise** — every run prints tokens and USD. Route bulk work to cheap
models (`-a researcher` or `-m <small>`), and check `arccode whichmodel`.
