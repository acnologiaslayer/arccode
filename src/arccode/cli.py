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
# Separate stderr console so hints don't pollute redirected stdout (e.g. when a
# user does `arccode completion bash > file`).
console_err = Console(theme=ARC_THEME, stderr=True)

# We keep Typer's auto-added `--install-completion/--show-completion` options off
# (add_completion=False) for a clean help screen, but still register the shell
# completion classes so runtime <Tab> completion works once the user installs a
# script via `arccode completion`.
try:
    from typer._completion_classes import completion_init as _completion_init
    _completion_init()
except Exception:  # noqa: BLE001, S110
    pass


# --- Shell tab-completion helpers -------------------------------------------
# These power `--agent`/`--model` value completion. They must be cheap and never
# raise: the shell calls them synchronously on every <Tab>.

def _complete_agents(incomplete: str):
    """Complete agent names from the active registry (env-overridable)."""
    try:
        import pathlib

        from .agents import load_registry
        default = pathlib.Path(__file__).resolve().parent / "agents" / "registry"
        agents_dir = os.environ.get("ARCCODE_AGENTS_DIR") or str(default)
        reg = load_registry(pathlib.Path(agents_dir).expanduser())
        for name, spec in sorted(reg.items()):
            if name.startswith(incomplete):
                yield (name, (spec.description or "")[:50])
    except Exception:  # noqa: BLE001, S110
        pass


def _complete_models(incomplete: str):
    """Complete model catalog keys (and provider/id forms)."""
    try:
        for key, spec in sorted(MODELS.items()):
            if key.startswith(incomplete):
                yield (key, getattr(spec, "id", ""))
    except Exception:  # noqa: BLE001, S110
        pass


def _complete_profiles(incomplete: str):
    """Complete saved profile names."""
    try:
        from .profiles import ProfileStore
        store = ProfileStore.load()
        for name, p in sorted(store.profiles.items()):
            if name.startswith(incomplete):
                bits = []
                if p.agent:
                    bits.append(p.agent)
                if p.model:
                    bits.append(p.model)
                yield (name, " ".join(bits))
    except Exception:  # noqa: BLE001, S110
        pass


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


def _activate_profile(name: str | None):
    """Resolve a profile (explicit name overrides the active one), apply its env,
    and refresh the model catalog. Returns the Profile or None.

    Errors are surfaced (unknown explicit profile aborts); a missing active
    profile is simply ignored so normal runs are unaffected.
    """
    from . import config as _config
    from .profiles import ProfileStore, apply_env, resolve_active

    prof = None
    if name:
        prof = ProfileStore.load().get(name)
        if prof is None:
            console.print(f"[arc.err]Unknown profile '{name}'.[/arc.err] "
                          "See [arc.accent2]arccode profile list[/arc.accent2].")
            raise typer.Exit(1)
    else:
        prof = resolve_active()
    if prof:
        apply_env(prof)
        _config.reload()  # ARCCODE_CONFIG / keys from the profile take effect
    return prof


def _merge(profile, *, agent, model, cwd, yes, max_steps):
    """Layer a profile under explicit CLI values (the command line always wins).

    Sentinels: agent/model/cwd/max_steps == None means "not given on CLI"; yes
    is a bool where True means the user passed -y (profile can still enable it).
    """
    p = profile
    agent = agent or (p.agent if p and p.agent else None) or "coordinator"
    model = model or (p.model if p and p.model else None)
    cwd = cwd or (p.cwd if p and p.cwd else None) or "."
    yes = yes or bool(p.yes) if p else yes
    if max_steps is None:
        max_steps = (p.max_steps if p and p.max_steps else None) or 40
    return agent, model, cwd, yes, max_steps


@app.command()
def run(
    task: str = typer.Argument(..., help="The task/prompt to run."),
    agent: str = typer.Option(None, "--agent", "-a", help="Agent to use (default coordinator).",
        autocompletion=_complete_agents),
    model: str = typer.Option(None, "--model", "-m", help="Force a model (catalog key or id).",
        autocompletion=_complete_models),
    profile: str = typer.Option(None, "--profile", "-p",
        help="Use a named profile's defaults (overrides the active one).",
        autocompletion=_complete_profiles),
    yes: bool = typer.Option(False, "--yes", "-y", help="Auto-approve danger tools."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show routing + tool calls."),
    cwd: str = typer.Option(None, "--cwd", help="Working directory."),
    no_mcp: bool = typer.Option(False, "--no-mcp", help="Disable MCP servers."),
    session_id: str = typer.Option(None, "--session", "-s",
        help="Persist to / resume this session id ('new' to start one)."),
    max_steps: int = typer.Option(None, "--max-steps"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Print only the result (no summary/spinner)."),
    as_json: bool = typer.Option(False, "--json", help="Emit a JSON object with result, files, and usage."),
    dry_run: bool = typer.Option(False, "--dry-run",
        help="Plan only: show routing, agent, model, tools, and cost. No LLM call, no writes."),
):
    """Run a single task with an agent (auto-routed model unless -m given)."""
    prof = _activate_profile(profile)
    agent, model, cwd, yes, max_steps = _merge(
        prof, agent=agent, model=model, cwd=cwd, yes=yes, max_steps=max_steps)
    if model:
        from .config import resolve as _resolve_model
        try:
            _resolve_model(model)
        except KeyError:
            console.print(f"[arc.err]Unknown model '{model}'.[/arc.err] "
                          "See available models with [arc.accent2]arccode models[/arc.accent2].")
            raise typer.Exit(1)
    if dry_run:
        _dry_run(task, agent=agent, model=model, cwd=cwd, no_mcp=no_mcp,
                 profile=prof, as_json=as_json)
        return
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
    streamed = {"any": False}
    if use_spinner:
        def _emit(delta, _s=streamed):
            _s["any"] = True
            console.print(delta, end="", markup=False, highlight=False)
        with console.status("[arc.muted]starting...[/arc.muted]", spinner="dots") as status:
            a.ctx.on_status = lambda text: status.update(f"[arc.muted]{text}[/arc.muted]") \
                if text else status.stop()
            a.ctx.on_text = _emit
            result = a.run(task, agent=agent, model=model, max_steps=max_steps, session=sess)
        a.ctx.on_text = None
        if streamed["any"]:
            console.print()  # newline after streamed text
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

    # Plain result. If we already streamed it live, don't print it again.
    if not streamed["any"]:
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


def _estimate_cost(spec, in_tokens: int, out_tokens: int) -> float:
    return (in_tokens / 1_000_000) * spec.in_cost + (out_tokens / 1_000_000) * spec.out_cost


def _dry_run(task, *, agent, model, cwd, no_mcp, profile, as_json):
    """Show the execution plan without calling any model or touching the disk.

    Resolves the same routing decision the real run would, plus the agent's tool
    set and a rough cost estimate, so users can preview and price a task safely.
    """
    from .router import _usable_provider, route
    from .tools import DEFAULT_TOOLS

    app_obj = App(cwd=cwd or ".", enable_mcp=False)
    spec = app_obj.orchestrator.get(agent)
    if not spec:
        console.print(f"[arc.err]Unknown agent '{agent}'.[/arc.err] "
                      "See [arc.accent2]arccode agents[/arc.accent2].")
        raise typer.Exit(1)

    pinned = model or spec.model
    decision = route(task, force=pinned)
    # Mirror the runtime's fallback: if a pinned model's provider is unusable,
    # auto-routing would pick an alternative.
    fell_back = False
    if pinned and not _usable_provider(decision.model.provider):
        alt = route(task, force=None)
        if _usable_provider(alt.model.provider):
            decision, fell_back = alt, True

    m = decision.model
    usable = _usable_provider(m.provider)
    tool_names = list(spec.tools or DEFAULT_TOOLS)
    # Rough estimate: prompt+system+task in, a modest reply out.
    est_in = max(200, len(task) // 3 + 400)
    est_out = 500
    est = _estimate_cost(m, est_in, est_out)

    if as_json:
        import json as _json
        print(_json.dumps({
            "dry_run": True,
            "task": task,
            "profile": profile.name if profile else None,
            "agent": agent,
            "model": {"key": m.key, "id": m.id, "provider": m.provider,
                      "tier": m.tier, "usable_now": usable},
            "routing": {"intent": decision.intent, "complexity": decision.complexity,
                        "forced": bool(pinned), "fell_back": fell_back,
                        "reason": decision.reason},
            "tools": tool_names,
            "cwd": cwd or ".",
            "mcp": (not no_mcp),
            "cost_estimate_usd": round(est, 6),
            "cost_basis": {"in_tokens": est_in, "out_tokens": est_out,
                           "in_per_m": m.in_cost, "out_per_m": m.out_cost},
        }, indent=2))
        return

    table = _table("dry run - execution plan")
    table.add_column("field", style="arc.accent")
    table.add_column("value")
    if profile:
        table.add_row("profile", profile.name)
    table.add_row("task", (task[:70] + "...") if len(task) > 70 else task)
    table.add_row("agent", agent)
    model_line = f"{m.key}  [arc.muted]({m.id}, {m.tier})[/arc.muted]"
    if not usable:
        model_line += "  [arc.warn]provider not usable now[/arc.warn]"
    table.add_row("model", model_line)
    route_line = f"intent={decision.intent} complexity={decision.complexity}"
    if pinned:
        route_line = "forced" + ("  [arc.warn](pinned unusable -> fell back)[/arc.warn]"
                                 if fell_back else "")
    table.add_row("routing", route_line)
    table.add_row("tools", ", ".join(tool_names) or "(none)")
    table.add_row("cwd", cwd or ".")
    table.add_row("mcp", "on" if not no_mcp else "off")
    cost_txt = "free" if est == 0 else f"~${est:.4f}"
    table.add_row("est. cost", f"{cost_txt}  [arc.muted]({est_in} in + {est_out} out tok)[/arc.muted]")
    console.print(table)
    console.print("[arc.muted]dry run: no model was called and nothing was written. "
                  "Drop --dry-run to execute.[/arc.muted]")


@app.command()
def chat(
    agent: str = typer.Option(None, "--agent", "-a",
        autocompletion=_complete_agents),
    model: str = typer.Option(None, "--model", "-m",
        autocompletion=_complete_models),
    profile: str = typer.Option(None, "--profile", "-p",
        help="Use a named profile's defaults (overrides the active one).",
        autocompletion=_complete_profiles),
    yes: bool = typer.Option(False, "--yes", "-y"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
    cwd: str = typer.Option(None, "--cwd"),
    no_mcp: bool = typer.Option(False, "--no-mcp"),
):
    """Interactive session. Type a task, or /help for in-chat commands."""
    from rich.panel import Panel
    prof = _activate_profile(profile)
    agent, model, cwd, yes, _ms = _merge(
        prof, agent=agent, model=model, cwd=cwd, yes=yes, max_steps=None)
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

        # A real task. Stream the reply live when attached to a terminal.
        if not verbose and console.is_terminal:
            console.print(f"[arc.ok]{agent} ›[/arc.ok] ", end="")
            streamed = {"any": False}

            def _emit(delta, _s=streamed):
                _s["any"] = True
                console.print(delta, end="", markup=False, highlight=False)

            with console.status("[arc.muted]thinking...[/arc.muted]", spinner="dots") as st:
                a.ctx.on_status = lambda t: st.update(f"[arc.muted]{t}[/arc.muted]") if t \
                    else st.stop()
                a.ctx.on_text = _emit
                result = a.run(line, agent=agent, model=model)
            a.ctx.on_text = None
            if streamed["any"]:
                console.print()  # newline after streamed text
            else:
                console.print(result)
        else:
            result = a.run(line, agent=agent, model=model)
            console.print(f"[arc.ok]{agent} ›[/arc.ok] {result}")
        turns += 1
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
    agent: str = typer.Argument(..., autocompletion=_complete_agents),
    task: str = typer.Argument(...),
    model: str = typer.Option(None, "--model", "-m",
        autocompletion=_complete_models),
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
    """Diagnose your setup: Python, services, catalog, agents, config, and more."""
    import pathlib
    import shutil
    import sys as _sys

    from .services import detect

    ok, warn, bad = "[arc.ok]✓[/arc.ok]", "[arc.warn]![/arc.warn]", "[arc.err]✗[/arc.err]"
    lines = []
    n_warn = n_bad = 0

    def add(mark, text):
        nonlocal n_warn, n_bad
        if mark == warn:
            n_warn += 1
        elif mark == bad:
            n_bad += 1
        lines.append((mark, text))

    home = pathlib.Path(os.environ.get("ARCCODE_HOME", pathlib.Path.home() / ".arccode"))

    # --- environment -------------------------------------------------------
    v = _sys.version_info
    pyok = v >= (3, 10)
    add(ok if pyok else bad,
        f"Python {v.major}.{v.minor}.{v.micro}" + ("" if pyok else " (need 3.10+)"))

    on_path = shutil.which("arccode")
    add(ok if on_path else warn,
        f"arccode on PATH: {on_path}" if on_path else
        "arccode not on PATH (add ~/.local/bin to PATH)")
    add(ok, f"version {__version__}")

    # provider SDKs importable
    for mod, label in (("openai", "openai SDK"), ("anthropic", "anthropic SDK")):
        try:
            __import__(mod)
            add(ok, f"{label} installed")
        except ImportError:
            add(warn, f"{label} missing (pip install {mod})")

    # --- services + catalog ------------------------------------------------
    try:
        det = detect()
        conn = [n for n, d in det.items() if d.connected]
    except Exception as e:  # noqa: BLE001
        conn, det = [], {}
        add(bad, f"service detection failed: {e}")
    if conn:
        add(ok, f"{len(conn)} AI service(s) connected: {', '.join(conn)}")
    else:
        add(bad, "no AI services connected")
        add(warn, "  fix: run `ollama serve`, or set a key "
                  "(e.g. export GROQ_API_KEY=... / OPENAI_API_KEY=...)")

    try:
        from .config import MODELS
        n_models = len(MODELS)
        add(ok if n_models else warn,
            f"model catalog: {n_models} model(s)" +
            ("" if n_models else " (empty)"))
    except Exception as e:  # noqa: BLE001
        add(bad, f"catalog load failed: {e}")

    # ARCCODE_CONFIG override, if set, must exist and parse
    cfg = os.environ.get("ARCCODE_CONFIG")
    if cfg:
        cpath = pathlib.Path(cfg).expanduser()
        if not cpath.exists():
            add(bad, f"ARCCODE_CONFIG points to missing file: {cfg}")
        else:
            try:
                import yaml
                yaml.safe_load(cpath.read_text())
                add(ok, f"ARCCODE_CONFIG valid: {cfg}")
            except Exception as e:  # noqa: BLE001
                add(bad, f"ARCCODE_CONFIG invalid YAML: {e}")

    # --- profiles ----------------------------------------------------------
    try:
        from .profiles import ProfileStore
        store = ProfileStore.load()
        if store.profiles:
            active = store.active or "(none)"
            add(ok, f"profiles: {len(store.profiles)} saved, active: {active}")
        else:
            add(ok, "profiles: none (optional)")
    except Exception as e:  # noqa: BLE001
        add(warn, f"profiles unreadable: {e}")

    # --- agents & skills ---------------------------------------------------
    try:
        from .app import App
        a = App(cwd=".", enable_mcp=False)
        n_agents = len(a.orchestrator.registry)
        add(ok if n_agents else warn, f"agents: {n_agents} available")
        n_skills = 0
        try:
            skills_map = getattr(a.skills, "skills", {})
            n_skills = len(skills_map)
        except Exception:  # noqa: BLE001
            n_skills = 0
        add(ok, f"skills: {n_skills} available")
    except Exception as e:  # noqa: BLE001
        add(bad, f"agent registry failed to load: {e}")

    # --- config dir, credentials, MCP, sessions ----------------------------
    add(ok if home.exists() else warn, f"config dir: {home}")

    cred = home / "credentials.json"
    if cred.exists():
        try:
            mode = oct(cred.stat().st_mode & 0o777)
            secure = (cred.stat().st_mode & 0o077) == 0
            add(ok if secure else warn,
                f"credentials.json present (mode {mode})" +
                ("" if secure else " - should be 0600 (chmod 600)"))
        except OSError as e:
            add(warn, f"credentials.json unreadable: {e}")
    else:
        add(ok, "credentials.json: none (using env keys/OAuth as needed)")

    mcp_cfg = home / "mcp.json"
    if mcp_cfg.exists():
        try:
            import json as _json
            data = _json.loads(mcp_cfg.read_text())
            n_srv = len((data or {}).get("mcpServers", data) or {})
            add(ok, f"mcp.json: {n_srv} server(s) configured")
        except Exception as e:  # noqa: BLE001
            add(bad, f"mcp.json invalid JSON: {e}")
    else:
        add(ok, "mcp.json: none (optional)")

    try:
        from .session import list_sessions
        add(ok, f"sessions: {len(list_sessions())} saved")
    except Exception:  # noqa: BLE001
        add(ok, "sessions: 0 saved")

    # --- render ------------------------------------------------------------
    table = _table("arccode doctor")
    table.add_column("")
    table.add_column("check")
    for mark, text in lines:
        table.add_row(mark, text)
    console.print(table)

    if n_bad:
        console.print(f"[arc.err]{n_bad} problem(s), {n_warn} warning(s).[/arc.err] "
                      "Fix the ✗ items above, then re-run `arccode doctor`.")
    elif n_warn:
        console.print(f"[arc.warn]{n_warn} warning(s), nothing blocking.[/arc.warn] "
                      "arccode should work; address ! items for the best experience.")
    else:
        console.print("[arc.ok]All checks passed. Ready to go.[/arc.ok] "
                      "Try: arccode run \"summarize this project\"")


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


profile_app = typer.Typer(help="Manage config profiles (named run defaults).",
                          no_args_is_help=True)
app.add_typer(profile_app, name="profile")


@profile_app.command("list")
def profile_list():
    """List saved profiles (the active one is marked)."""
    from .profiles import ProfileStore
    store = ProfileStore.load()
    if not store.profiles:
        console.print("(no profiles) create one with "
                      "[arc.accent2]arccode profile set <name> ...[/arc.accent2]")
        return
    table = _table("profiles")
    for col in ("", "name", "agent", "model", "yes", "env"):
        table.add_column(col)
    for name, p in sorted(store.profiles.items()):
        mark = "[arc.accent2]●[/arc.accent2]" if name == store.active else ""
        env = ", ".join(sorted(p.env)) if p.env else ""
        table.add_row(mark, name, p.agent or "-", p.model or "-",
                      "yes" if p.yes else "-", env or "-")
    console.print(table)


@profile_app.command("show")
def profile_show(name: str = typer.Argument(None, autocompletion=_complete_profiles)):
    """Show one profile (or the active one if no name is given)."""
    import json as _json

    from .profiles import ProfileStore
    store = ProfileStore.load()
    p = store.get(name) if name else store.active_profile()
    if not p:
        console.print("[arc.err]no such profile[/arc.err]" if name
                      else "[arc.warn]no active profile[/arc.warn]")
        raise typer.Exit(1)
    console.print(f"[arc.accent2]{p.name}[/arc.accent2]"
                  + (" [arc.muted](active)[/arc.muted]" if p.name == store.active else ""))
    console.print(_json.dumps(p.to_dict(), indent=2))


@profile_app.command("set")
def profile_set(
    name: str = typer.Argument(..., help="Profile name to create or update."),
    agent: str = typer.Option(None, "--agent", "-a", autocompletion=_complete_agents),
    model: str = typer.Option(None, "--model", "-m", autocompletion=_complete_models),
    cwd: str = typer.Option(None, "--cwd"),
    yes: bool = typer.Option(None, "--yes/--no-yes",
        help="Auto-approve danger tools for this profile."),
    max_steps: int = typer.Option(None, "--max-steps"),
    env: list[str] = typer.Option(None, "--env", "-e",  # noqa: B008
        help="Env var as KEY=VALUE (repeatable). E.g. -e ARCCODE_CONFIG=~/work.yaml"),
    activate: bool = typer.Option(False, "--activate",
        help="Also make this the active profile."),
):
    """Create or update a profile. Only the flags you pass are changed."""
    from .profiles import Profile, ProfileStore
    store = ProfileStore.load()
    p = store.get(name) or Profile(name=name)
    if agent is not None:
        p.agent = agent
    if model is not None:
        p.model = model
    if cwd is not None:
        p.cwd = cwd
    if yes is not None:
        p.yes = yes
    if max_steps is not None:
        p.max_steps = max_steps
    for pair in (env or []):
        if "=" not in pair:
            console.print(f"[arc.err]bad --env '{pair}'[/arc.err] (expected KEY=VALUE)")
            raise typer.Exit(1)
        k, v = pair.split("=", 1)
        p.env[k.strip()] = v.strip()
    store.set(p)
    if activate:
        store.use(name)
    store.save()
    console.print(f"[arc.ok]✓ saved profile[/arc.ok] [arc.accent2]{name}[/arc.accent2]"
                  + ("  [arc.muted](active)[/arc.muted]" if store.active == name else ""))


@profile_app.command("use")
def profile_use(name: str = typer.Argument(..., autocompletion=_complete_profiles)):
    """Make a profile the active default for run/chat."""
    from .profiles import ProfileStore
    store = ProfileStore.load()
    if not store.use(name):
        console.print(f"[arc.err]Unknown profile '{name}'.[/arc.err]")
        raise typer.Exit(1)
    store.save()
    console.print(f"[arc.ok]✓ active profile:[/arc.ok] [arc.accent2]{name}[/arc.accent2]")


@profile_app.command("clear")
def profile_clear():
    """Clear the active profile (run/chat use built-in defaults)."""
    from .profiles import ProfileStore
    store = ProfileStore.load()
    store.active = None
    store.save()
    console.print("[arc.ok]✓ no active profile[/arc.ok]")


@profile_app.command("delete")
def profile_delete(name: str = typer.Argument(..., autocompletion=_complete_profiles)):
    """Delete a profile."""
    from .profiles import ProfileStore
    store = ProfileStore.load()
    if not store.delete(name):
        console.print(f"[arc.err]Unknown profile '{name}'.[/arc.err]")
        raise typer.Exit(1)
    store.save()
    console.print(f"[arc.ok]✓ deleted[/arc.ok] {name}")


@app.command()
def completion(
    shell: str = typer.Argument(None,
        help="Shell to target: bash, zsh, or fish. Auto-detected from $SHELL if omitted."),
    install: bool = typer.Option(False, "--install",
        help="Append the loader line to your shell rc file."),
):
    """Set up shell tab-completion for arccode (agents, models, commands, flags).

    Without --install this prints the completion script; pipe it to a file. With
    --install it wires the loader into your shell rc so completion just works.
    """
    import pathlib

    sh = (shell or os.environ.get("SHELL", "")).rsplit("/", 1)[-1].strip().lower()
    if sh not in ("bash", "zsh", "fish"):
        console.print(f"[arc.err]unsupported shell '{sh or shell}'[/arc.err] "
                      "(supported: bash, zsh, fish)")
        raise typer.Exit(1)

    # Typer generates the completion script for us (no subprocess needed).
    try:
        from typer._completion_shared import get_completion_script
        script = get_completion_script(
            prog_name="arccode", complete_var="_ARCCODE_COMPLETE", shell=sh)
    except Exception:  # noqa: BLE001
        script = ""

    if not script.strip():
        console.print("[arc.warn]Could not generate the script.[/arc.warn] "
                      "Run this once to enable completion:")
        _print_completion_hint(sh)
        raise typer.Exit(0)

    if not install:
        # Print raw script for redirection: `arccode completion bash > file`.
        print(script)
        console_err.print("\n[arc.muted]Save it and source it, e.g.:[/arc.muted]")
        _print_completion_hint(sh)
        return

    # --install: write the script where the shell will load it.
    if sh == "fish":
        dest = pathlib.Path.home() / ".config" / "fish" / "completions" / "arccode.fish"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(script)
        console.print(f"[arc.ok]✓ installed[/arc.ok] completion into {dest}")
        console.print("[arc.muted]Restart fish (it auto-loads this file).[/arc.muted]")
        return

    cfg = pathlib.Path.home() / ".arccode"
    cfg.mkdir(parents=True, exist_ok=True)
    script_path = cfg / f"completion.{sh}"
    script_path.write_text(script)
    rc = pathlib.Path.home() / (".bashrc" if sh == "bash" else ".zshrc")
    loader = f"source {script_path}"
    rc.parent.mkdir(parents=True, exist_ok=True)
    existing = rc.read_text() if rc.exists() else ""
    if loader in existing:
        console.print(f"[arc.ok]already installed[/arc.ok] in {rc}")
    else:
        with rc.open("a") as f:
            f.write(f"\n# arccode shell completion\n{loader}\n")
        console.print(f"[arc.ok]✓ installed[/arc.ok] completion into {rc}")
    console.print(f"[arc.muted]Restart your shell or run: source {rc}[/arc.muted]")


def _print_completion_hint(sh: str):
    if sh == "fish":
        console_err.print("[arc.accent2]  arccode completion fish "
                          "> ~/.config/fish/completions/arccode.fish[/arc.accent2]")
    else:
        rc = "~/.bashrc" if sh == "bash" else "~/.zshrc"
        console_err.print(f"[arc.accent2]  arccode completion {sh} --install[/arc.accent2]"
                          f"[arc.muted]  (or: arccode completion {sh} > ~/.arccode/completion.{sh} "
                          f"&& echo 'source ~/.arccode/completion.{sh}' >> {rc})[/arc.muted]")


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
