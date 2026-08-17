"""arccode CLI."""
from __future__ import annotations

import os

import typer
from rich.console import Console
from rich.table import Table
from rich.theme import Theme

from . import __version__
from .app import App
from .config import MODELS
from .router import route

# arccode red & black brand theme for the CLI.
ARC_THEME = Theme({
    "arc.accent": "bold red",
    "arc.accent2": "bright_red",
    "arc.muted": "grey42",
    "arc.ok": "bold red",
    "arc.warn": "bright_yellow",
    "arc.err": "bold bright_red",
    "arc.tier.cheap": "bright_red",
    "arc.tier.mid": "red",
    "arc.tier.frontier": "bold bright_red",
    # Rich built-ins remapped so stray defaults stay on-brand.
    "repr.str": "red",
    "table.header": "bold red",
})

app = typer.Typer(add_completion=False, help="arccode - multi-provider agent harness CLI",
                  invoke_without_command=True)
console = Console(theme=ARC_THEME)


@app.callback()
def _root(ctx: typer.Context):
    """Show a friendly welcome + status when run with no command."""
    if ctx.invoked_subcommand is not None:
        return
    from rich.panel import Panel

    from .services import detect
    try:
        det = detect()
        conn = [n for n, d in det.items() if d.connected]
    except Exception:  # noqa: BLE001
        conn = []
    status = (f"[arc.ok]{len(conn)} service(s) connected[/arc.ok]: {', '.join(conn)}"
              if conn else "[arc.warn]no services connected[/arc.warn] - start Ollama or set a key")
    body = (
        f"[arc.accent2]arccode[/arc.accent2] [arc.muted]v{__version__}[/arc.muted] "
        f"- route each task to the right model\n\n"
        f"{status}\n\n"
        "[bold]Try:[/bold]\n"
        "  arccode run [arc.accent2]\"summarize this project\"[/arc.accent2]   run a task\n"
        "  arccode chat                            interactive session\n"
        "  arccode providers                       see connected AI services\n"
        "  arccode agents                          list your specialist agents\n"
        "  arccode --help                          all commands"
    )
    console.print(Panel(body, border_style="red", title="[bold red]welcome[/bold red]",
                        title_align="left", padding=(1, 2)))


def _table(title: str) -> Table:
    return Table(title=title, border_style="red", header_style="bold red",
                 title_style="bold bright_red")


def _app(cwd: str, yes: bool, verbose: bool, no_mcp: bool) -> App:
    return App(cwd=cwd, yes=yes, verbose=verbose, enable_mcp=not no_mcp)


@app.command()
def run(
    task: str = typer.Argument(..., help="The task/prompt to run."),
    agent: str = typer.Option("coordinator", "--agent", "-a", help="Agent to use."),
    model: str = typer.Option(None, "--model", "-m", help="Force a model (catalog key or id)."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Auto-approve danger tools."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show routing + tool calls."),
    cwd: str = typer.Option(".", "--cwd", help="Working directory."),
    no_mcp: bool = typer.Option(False, "--no-mcp", help="Disable MCP servers."),
    session_id: str = typer.Option(None, "--session", "-s",
        help="Persist to / resume this session id ('new' to start one)."),
    max_steps: int = typer.Option(40, "--max-steps"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Print only the result (no summary/spinner)."),
    as_json: bool = typer.Option(False, "--json", help="Emit a JSON object with result, files, and usage."),
):
    """Run a single task with an agent (auto-routed model unless -m given)."""
    if model:
        from .config import resolve as _resolve_model
        try:
            _resolve_model(model)
        except KeyError:
            console.print(f"[arc.err]Unknown model '{model}'.[/arc.err] "
                          "See available models with [arc.accent2]arccode models[/arc.accent2].")
            raise typer.Exit(1)
    a = _app(cwd, yes, verbose, no_mcp)
    sess = None
    if session_id:
        from .session import Session
        if session_id == "new":
            sess = Session.create(agent)
        else:
            try:
                sess = Session.load(session_id)
            except FileNotFoundError:
                sess = Session.create(agent)
                sess.id = session_id
    # Live step feedback: a spinner that updates as the agent works (unless
    # verbose/quiet/json, or output is piped).
    use_spinner = not verbose and not quiet and not as_json and console.is_terminal
    if session_id == "new" and not (quiet or as_json):
        console.print(f"[dim]session {sess.id}[/dim]")
    if use_spinner:
        with console.status("[arc.muted]starting...[/arc.muted]", spinner="dots") as status:
            a.ctx.on_status = lambda text: status.update(f"[arc.muted]{text}[/arc.muted]")
            result = a.run(task, agent=agent, model=model, max_steps=max_steps, session=sess)
    else:
        result = a.run(task, agent=agent, model=model, max_steps=max_steps, session=sess)

    u = a.usage()
    touched = sorted(a.ctx.touched)

    if as_json:
        import json as _json
        out = {
            "result": result,
            "agent": agent,
            "files_changed": touched,
            "usage": {"in": u["in"], "out": u["out"], "usd": round(u["usd"], 6)},
        }
        if sess:
            out["session"] = sess.id
        print(_json.dumps(out, indent=2))
        return

    # Plain result (quiet: only this).
    print(result)
    if quiet:
        return

    if sess:
        console.print(f"[dim]session saved: {sess.id} ({len(sess.messages)} turns)[/dim]")
    # Friendly run summary: what changed + cost.
    parts = []
    if touched:
        names = ", ".join(t.split("/")[-1] for t in touched[:4])
        more = f" +{len(touched) - 4} more" if len(touched) > 4 else ""
        parts.append(f"changed {len(touched)} file(s): {names}{more}")
    cost = f"${u['usd']:.4f}" if u["usd"] else "free"
    parts.append(f"{u['in'] + u['out']} tokens · {cost}")
    console.print(f"[arc.ok]✓ done[/arc.ok] [arc.muted]· {' · '.join(parts)}[/arc.muted]",
                  highlight=False)


@app.command()
def chat(
    agent: str = typer.Option("coordinator", "--agent", "-a"),
    model: str = typer.Option(None, "--model", "-m"),
    yes: bool = typer.Option(False, "--yes", "-y"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
    cwd: str = typer.Option(".", "--cwd"),
    no_mcp: bool = typer.Option(False, "--no-mcp"),
):
    """Interactive session. Type a task, or /help for in-chat commands."""
    from rich.panel import Panel
    a = _app(cwd, yes, verbose, no_mcp)

    # Session-scoped running cost.
    turns = 0

    def _header():
        conn = []
        try:
            from .services import detect
            conn = [n for n, d in detect().items() if d.connected]
        except Exception:  # noqa: BLE001
            pass
        mtxt = model or "auto"
        console.print(Panel(
            f"[arc.accent2]arccode chat[/arc.accent2] [arc.muted]v{__version__}[/arc.muted]\n"
            f"agent [arc.accent2]{agent}[/arc.accent2] · model [arc.accent2]{mtxt}[/arc.accent2]"
            f" · services: {', '.join(conn) or 'none'}\n"
            "[arc.muted]/help for commands · /exit to quit[/arc.muted]",
            border_style="red", padding=(0, 2)))

    def _help():
        console.print(
            "[bold]commands:[/bold]\n"
            "  /agent <name>   switch agent\n"
            "  /model <key>    force a model ('auto' to clear)\n"
            "  /agents         list agents\n"
            "  /models         list models\n"
            "  /cost           show session cost so far\n"
            "  /clear          reset the screen\n"
            "  /exit           quit")

    _header()
    while True:
        try:
            line = console.input("[arc.accent]you ›[/arc.accent] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[arc.muted]bye[/arc.muted]")
            break
        if not line:
            continue
        if line in ("/exit", "/quit"):
            console.print("[arc.muted]bye[/arc.muted]")
            break
        if line == "/help":
            _help(); continue
        if line == "/clear":
            console.clear(); _header(); continue
        if line == "/cost":
            u = a.usage()
            c = f"${u['usd']:.4f}" if u["usd"] else "free"
            console.print(f"[arc.muted]session: {turns} turn(s) · "
                          f"{u['in'] + u['out']} tokens · {c}[/arc.muted]")
            continue
        if line == "/agents":
            for name in sorted(a.orchestrator.registry):
                console.print(f"  {name}")
            continue
        if line == "/models":
            from .config import MODELS
            for k in list(MODELS)[:20]:
                console.print(f"  {k}")
            continue
        if line.startswith("/agent "):
            new = line.split(maxsplit=1)[1].strip()
            if new in a.orchestrator.registry:
                agent = new
                console.print(f"[arc.ok]switched to agent {agent}[/arc.ok]")
            else:
                console.print(f"[arc.err]no such agent '{new}'[/arc.err] (try /agents)")
            continue
        if line.startswith("/model "):
            new = line.split(maxsplit=1)[1].strip()
            if new in ("auto", "none", ""):
                model = None
                console.print("[arc.ok]model set to auto[/arc.ok]")
            else:
                from .config import resolve as _rm
                try:
                    _rm(new); model = new
                    console.print(f"[arc.ok]model set to {model}[/arc.ok]")
                except KeyError:
                    console.print(f"[arc.err]unknown model '{new}'[/arc.err] (try /models)")
            continue
        if line.startswith("/"):
            console.print(f"[arc.err]unknown command '{line}'[/arc.err] (try /help)")
            continue

        # A real task.
        if not verbose and console.is_terminal:
            with console.status("[arc.muted]thinking...[/arc.muted]", spinner="dots") as st:
                a.ctx.on_status = lambda t: st.update(f"[arc.muted]{t}[/arc.muted]")
                result = a.run(line, agent=agent, model=model)
        else:
            result = a.run(line, agent=agent, model=model)
        turns += 1
        console.print(f"[arc.ok]{agent} ›[/arc.ok] {result}")
        u = a.usage()
        c = f"${u['usd']:.4f}" if u["usd"] else "free"
        console.print(f"[arc.muted]· {u['in'] + u['out']} tokens · {c} total[/arc.muted]",
                      highlight=False)


@app.command()
def agents(cwd: str = typer.Option(".", "--cwd")):
    """List available agents."""
    a = App(cwd=cwd, enable_mcp=False)
    table = _table("agents")
    table.add_column("name", style="arc.accent")
    table.add_column("model")
    table.add_column("description")
    for name, spec in sorted(a.orchestrator.registry.items()):
        table.add_row(name, spec.model or "auto", (spec.description or "")[:80])
    console.print(table)


@app.command()
def skills(cwd: str = typer.Option(".", "--cwd")):
    """List available skills."""
    a = App(cwd=cwd, enable_mcp=False)
    console.print(a.skills.index() or "(no skills)")


@app.command()
def models():
    """List the model catalog with pricing."""
    table = _table("model catalog")
    for col in ("key", "id", "tier", "$in/1M", "$out/1M", "strengths"):
        table.add_column(col)
    for key, m in MODELS.items():
        table.add_row(key, m.id, m.tier, str(m.in_cost), str(m.out_cost),
                      ",".join(sorted(m.strengths)))
    console.print(table)


@app.command()
def whichmodel(task: str):
    """Show which model the router would pick for a task, and why."""
    d = route(task)
    tier_style = {"frontier": "arc.tier.frontier", "mid": "arc.tier.mid",
                  "small": "arc.tier.cheap", "local": "arc.tier.cheap"}.get(d.model.tier, "arc.accent")
    console.print(f"[{tier_style}]{d.model.key}[/{tier_style}] ({d.model.id})")
    console.print(f"[arc.muted]{d.reason}[/arc.muted]")


@app.command()
def spawn(
    agent: str = typer.Argument(...),
    task: str = typer.Argument(...),
    model: str = typer.Option(None, "--model", "-m"),
    yes: bool = typer.Option(False, "--yes", "-y"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
    cwd: str = typer.Option(".", "--cwd"),
):
    """Spawn a specific agent on a task (bypasses coordinator)."""
    a = _app(cwd, yes, verbose, True)
    console.print(a.orchestrator.spawn(agent, task, model, a.ctx))


@app.command()
def mcp(cwd: str = typer.Option(".", "--cwd")):
    """List connected MCP servers and their tools."""
    a = App(cwd=cwd, enable_mcp=True)
    clients = getattr(a, "mcp_clients", {})
    if not clients:
        console.print("(no MCP servers connected; configure ~/.arccode/mcp.json)")
        return
    for name, client in clients.items():
        console.print(f"[bold]{name}[/bold]: {[t['name'] for t in client.tools]}")


@app.command()
def doctor():
    """Diagnose your setup: Python, connected services, PATH, and config."""
    import shutil
    import sys as _sys

    from .services import detect

    ok, warn, bad = "[arc.ok]✓[/arc.ok]", "[arc.warn]![/arc.warn]", "[arc.err]✗[/arc.err]"
    lines = []

    # Python version
    v = _sys.version_info
    pyok = v >= (3, 10)
    lines.append((ok if pyok else bad,
                  f"Python {v.major}.{v.minor}.{v.micro}" +
                  ("" if pyok else " (need 3.10+)")))

    # arccode on PATH
    on_path = shutil.which("arccode")
    lines.append((ok if on_path else warn,
                  f"arccode on PATH: {on_path}" if on_path else
                  "arccode not on PATH (add ~/.local/bin to PATH)"))

    # Connected services
    try:
        det = detect()
        conn = [n for n, d in det.items() if d.connected]
    except Exception as e:  # noqa: BLE001
        conn, det = [], {}
        lines.append((bad, f"service detection failed: {e}"))
    if conn:
        lines.append((ok, f"{len(conn)} AI service(s) connected: {', '.join(conn)}"))
    else:
        lines.append((bad, "no AI services connected"))
        _fix = ("  fix: run `ollama serve`, or set a key "
                "(e.g. export GROQ_API_KEY=... / OPENAI_API_KEY=...)")
        lines.append((warn, _fix))

    # provider SDKs importable
    for mod, label in (("openai", "openai SDK"), ("anthropic", "anthropic SDK")):
        try:
            __import__(mod)
            lines.append((ok, f"{label} installed"))
        except ImportError:
            lines.append((warn, f"{label} missing (pip install {mod})"))

    # config locations
    import pathlib
    home = pathlib.Path(os.environ.get("ARCCODE_HOME", pathlib.Path.home() / ".arccode"))
    lines.append((ok if home.exists() else warn, f"config dir: {home}"))

    table = _table("arccode doctor")
    table.add_column("")
    table.add_column("check")
    for mark, text in lines:
        table.add_row(mark, text)
    console.print(table)
    if conn:
        console.print("[arc.ok]Ready to go.[/arc.ok] Try: arccode run \"summarize this project\"")
    else:
        console.print("[arc.warn]Not ready:[/arc.warn] connect a service (see fixes above), "
                      "then run `arccode providers`.")


@app.command()
def sessions():
    """List saved sessions."""
    from .session import list_sessions
    rows = list_sessions()
    if not rows:
        console.print("(no sessions)")
        return
    table = _table("sessions")
    for col in ("id", "agent", "turns", "cost"):
        table.add_column(col)
    for s in rows:
        table.add_row(s["id"], s["agent"], str(s["turns"]), f"${s['usd']:.4f}")
    console.print(table)


@app.command()
def providers():
    """Show AI services: which are connected now and how to enable the rest."""
    from .services import detect
    det = detect()
    table = _table("services")
    for col in ("service", "status", "tier", "detail"):
        table.add_column(col)
    for name, d in det.items():
        status = "[arc.ok]connected[/arc.ok]" if d.connected else "[arc.muted]off[/arc.muted]"
        tier = "free" if d.service.free else "paid"
        detail = d.reason if not d.connected else (
            f"{len(d.live_models)} model(s)" if d.live_models else "ready")
        table.add_row(name, status, tier, detail)
    console.print(table)
    n_on = sum(1 for d in det.values() if d.connected)
    if n_on == 0:
        console.print("[arc.warn]No services connected.[/arc.warn] Start Ollama "
                      "(`ollama serve`) or set any provider key (e.g. GROQ_API_KEY).")
    else:
        console.print(f"[arc.muted]{n_on} connected. Add more by setting their key env var.[/arc.muted]")


@app.command()
def version():
    """Print version."""
    banner = r"""
  __ _ _ __ ___ ___ ___   __| | ___
 / _` | '__/ __/ __/ _ \ / _` |/ _ \
| (_| | | | (_| (_| (_) | (_| |  __/
 \__,_|_|  \___\___\___/ \__,_|\___|"""
    console.print(f"[arc.accent]{banner}[/arc.accent]")
    console.print(f"  [arc.accent2]arccode[/arc.accent2] [arc.muted]v{__version__} - "
                  f"multi-provider agent harness[/arc.muted]\n")


auth_app = typer.Typer(help="Authenticate with providers via OAuth.")
app.add_typer(auth_app, name="auth")


@auth_app.command("login")
def auth_login(
    provider: str = typer.Argument(..., help="Provider name (e.g. openai, anthropic, github)."),
    device: bool = typer.Option(False, "--device", help="Use the device-code flow (headless)."),
    port: int = typer.Option(8765, "--port", help="Local callback port for the code flow."),
):
    """Log in to a provider with OAuth and store the token."""
    from . import auth
    try:
        tok = auth.login(provider, device=device)
    except Exception as e:  # noqa: BLE001
        console.print(f"[arc.err]login failed:[/arc.err] {e}")
        raise typer.Exit(1)
    scopes = tok.get("scope", "")
    console.print(f"[arc.ok]logged in[/arc.ok] to {provider}"
                  + (f" (scopes: {scopes})" if scopes else ""))


@auth_app.command("logout")
def auth_logout(provider: str = typer.Argument(...)):
    """Remove stored credentials for a provider."""
    from . import auth
    ok = auth.logout(provider)
    console.print("logged out" if ok else f"no stored credentials for {provider}")


@auth_app.command("status")
def auth_status():
    """Show OAuth login status per provider."""
    from . import auth
    rows = auth.status()
    if not rows:
        console.print("(not logged in to any provider via OAuth)")
        return
    table = _table("oauth status")
    for col in ("provider", "access", "refresh", "expired"):
        table.add_column(col)
    for r in rows:
        table.add_row(r["provider"], "yes" if r["has_access"] else "no",
                      "yes" if r["has_refresh"] else "no",
                      "yes" if r["expired"] else "no")
    console.print(table)


if __name__ == "__main__":
    app()
