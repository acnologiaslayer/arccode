# Changelog

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
