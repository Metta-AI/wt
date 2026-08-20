import typer
from rich.console import Console

from softmaxwt.app import app
from softmaxwt.claude import list_claude_agents
from softmaxwt.command.destroy import destroy_worktree
from softmaxwt.graphite import fetch_all_graphite_info
from softmaxwt.worktree import Worktree, list_worktrees

console = Console()


@app.command()
def gc():
    """Destroy worktrees with nothing of value: pruned directories, and clean
    worktrees whose work is merged (or that never had local-only commits).

    A worktree with an active Claude session — busy, or stopped mid-task
    waiting on the user — is never collected; idle sessions don't block
    collection (their conversations survive via `claude --resume`).
    """
    worktrees = list_worktrees()

    graphite_info = fetch_all_graphite_info()
    for wt in worktrees:
        wt.set_graphite_info(graphite_info.get(wt.branch))

    claude_agents = list_claude_agents()

    victims: list[tuple[Worktree, str]] = []  # (worktree, reason/annotation)
    skipped: list[tuple[Worktree, str]] = []
    for wt in worktrees:
        if not wt.path.exists():
            victims.append((wt, "[red]REMOVED[/]"))
            continue
        if not wt.is_disposable():
            continue
        agents = [a for a in claude_agents if a.is_inside(wt.path)]
        active = [a for a in agents if a.is_active]
        if active:
            skipped.append((wt, f"[green]{active[0].label} ({active[0].activity})[/]"))
            continue
        note = "disposable"
        if agents:
            note += f", will orphan [yellow]{', '.join(f'{a.label} ({a.activity})' for a in agents)}[/]"
        victims.append((wt, note))

    for wt, why in skipped:
        console.print(f"Skipping [bold]{wt.path.name}[/]: {why}")

    if not victims:
        typer.echo("Nothing to clean up.")
        return

    console.print("[yellow]The following worktrees will be destroyed:[/]")
    for wt, why in victims:
        console.print(f"  [bold]{wt.path.name}[/]  (branch: [cyan]{wt.branch}[/]) — {why}")

    if not typer.confirm(typer.style("Proceed?", fg=typer.colors.RED, bold=True)):
        raise typer.Abort()

    for wt, _ in victims:
        destroy_worktree(wt)

    typer.echo("Done.")
