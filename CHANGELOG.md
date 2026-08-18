# Changelog

## 0.5.0

Profiles, dry-run planning, and a deeper doctor.

### Added
- **Config profiles**: named bundles of run defaults (agent, model, cwd, yes,
  max-steps, env). `arccode profile set/list/show/use/clear/delete`, an active
  pointer, and `-p/--profile` on `run`/`chat`. Precedence is explicit CLI flag →
  `-p` → active profile → built-in default; `ARCCODE_PROFILE` overrides per call.
  A profile's `env` (e.g. `ARCCODE_CONFIG`) is applied without clobbering values
  you already set, and the catalog reloads so its models are usable immediately.
- **`--dry-run` planning mode**: preview a run's routing, agent, model (with
  runtime-accurate provider fallback), tool set, and a cost estimate without
  calling any model or writing to disk. Works with `--json` for CI budgeting.
- **Richer `arccode doctor`**: adds catalog size, active profile, agents/skills
  counts, `ARCCODE_CONFIG` validity, credential file permissions, `mcp.json`
  validity, and saved-session count, plus a pass/warn/fail summary.

## 0.4.0

Shell tab-completion.

### Added
- **`arccode completion`**: install shell tab-completion for bash, zsh, and fish.
  `--install` wires a loader into your rc (idempotent; fish drops a file into its
  completions dir); without it the raw script prints to stdout for redirection.
- **Dynamic value completion**: `<Tab>` after `--agent` suggests agent names from
  your active registry, and after `--model`/`-m` suggests catalog model keys,
  both prefix-filtered. Commands, subcommands, and flags complete too.

## 0.3.0

Live streaming + scripting.

### Added
- **Live response streaming**: `chat` and `run` now stream the assistant's reply
  token by token on a terminal. Providers (OpenAI-compatible and Anthropic) grew
  an `on_text` streaming path that still assembles tool calls, threaded through
  the resilient completion layer and the agent loop. The spinner clears on the
  first token.
- **Scripting modes for `run`**: `--quiet/-q` prints only the final result
  (pipe-friendly) and `--json` emits `{result, agent, files_changed, usage,
  session}` for CI and tooling.
- **Richer interactive chat**: session header panel (agent, model, connected
  services), running token/cost totals, and in-chat slash commands (`/agent`,
  `/model`, `/agents`, `/models`, `/cost`, `/clear`, `/help`).

## 0.2.0

Product polish + robustness.

### Added
- **Auto-connect to free AI services**: on startup arccode detects and connects
  to local Ollama plus any hosted provider whose key is set (Groq, Gemini,
  Cerebras, Mistral, OpenRouter, GitHub Models), and builds the model catalog
  from what's available. `arccode providers` shows status.
- **Credential-aware routing**: runs prefer models whose provider is usable
  right now, so zero-config runs work against connected free services.
- **Resilient completion**: transient provider errors (429/5xx/timeouts) are
  retried with backoff (honoring Retry-After), then fail over to the next usable
  model so a run still completes.
- **UX**: friendly welcome screen on bare `arccode`; a live step-feedback
  spinner during runs; a run summary line (files changed + cost); actionable
  error messages instead of tracebacks; and `arccode doctor` self-diagnostics.

### Fixed
- OpenAI `max_tokens` vs `max_completion_tokens` compatibility for newer models.
- Unknown `-m` model now prints a friendly message instead of a traceback.

## 0.1.0
Initial release: multi-provider agent harness CLI with routing, file-based
agents + skills, orchestration, MCP, hooks, sessions, OAuth, and a tool suite.
