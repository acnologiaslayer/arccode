"""arccode CLI."""
from __future__ import annotations

import sys

import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from .app import App
from .config import MODELS
from .router import route

app = typer.Typer(add_completion=False, help="arccode - multi-provider agent harness CLI")
console = Console()


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
):
    """Run a single task with an agent (auto-routed model unless -m given)."""
    a = _app(cwd, yes, verbose, no_mcp)
    sess = None
    if session_id:
        from .session import Session
        if session_id == "new":
            sess = Session.create(agent)
            console.print(f"[dim]session {sess.id}[/dim]")
        else:
            try:
                sess = Session.load(session_id)
            except FileNotFoundError:
                sess = Session.create(agent)
                sess.id = session_id
    result = a.run(task, agent=agent, model=model, max_steps=max_steps, session=sess)
    console.print(result)
    if sess:
        console.print(f"[dim]session saved: {sess.id} ({len(sess.messages)} turns)[/dim]")
    u = a.usage()
    console.print(f"[dim]tokens in={u['in']} out={u['out']} cost=${u['usd']:.4f}[/dim]",
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
    """Interactive REPL. Type /exit to quit."""
    a = _app(cwd, yes, verbose, no_mcp)
    console.print(f"[bold]arccode[/bold] chat :: agent={agent}. /exit to quit.")
    while True:
        try:
            line = console.input("[bold cyan]you>[/bold cyan] ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if line in ("/exit", "/quit"):
            break
        if not line:
            continue
        result = a.run(line, agent=agent, model=model)
        console.print(f"[bold green]{agent}>[/bold green] {result}")


@app.command()
def agents(cwd: str = typer.Option(".", "--cwd")):
    """List available agents."""
    a = App(cwd=cwd, enable_mcp=False)
    table = Table(title="agents")
    table.add_column("name", style="cyan")
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
    table = Table(title="model catalog")
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
    console.print(f"[bold]{d.model.key}[/bold] ({d.model.id})")
    console.print(f"[dim]{d.reason}[/dim]")


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
def sessions():
    """List saved sessions."""
    from .session import list_sessions
    rows = list_sessions()
    if not rows:
        console.print("(no sessions)")
        return
    table = Table(title="sessions")
    for col in ("id", "agent", "turns", "cost"):
        table.add_column(col)
    for s in rows:
        table.add_row(s["id"], s["agent"], str(s["turns"]), f"${s['usd']:.4f}")
    console.print(table)


@app.command()
def version():
    """Print version."""
    console.print(f"arccode {__version__}")


if __name__ == "__main__":
    app()
