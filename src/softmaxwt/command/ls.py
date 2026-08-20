from concurrent.futures import ThreadPoolExecutor

import typer
from rich.console import Console
from rich.table import Table

from softmaxwt.app import app
from softmaxwt.claude import ClaudeAgent, list_claude_agents
from softmaxwt.graphite import GraphiteStatus, fetch_all_graphite_info
from softmaxwt.isolation.common import IsolatedSession
from softmaxwt.isolation.registry import all_isolation_backends
from softmaxwt.worktree import Worktree, list_worktrees


def _dirty_col(wt: Worktree) -> str:
    stats = wt.uncommitted_diff_stats()
    if stats is None:
        return "[dim]-[/]"
    return f"[bold]{stats.files} files[/] [green]+{stats.insertions}[/]/[red]-{stats.deletions}[/]"


def _unpushed_col(wt: Worktree) -> str:
    # Commits that exist only on this machine: ahead-of-upstream when the branch
    # has one, ahead-of-trunk (squash-merge aware) when it was never pushed.
    local = wt.unmerged_commits() if wt.has_no_upstream() else wt.unpushed_commits()
    if not local:
        return "[dim]-[/]"
    return f"[yellow]{len(local)} commit{'s' if len(local) > 1 else ''}[/]"


def _sync_col(wt: Worktree) -> str:
    info = wt.graphite_info
    if info is None:
        return "[dim]untracked[/]"
    match info.status:
        case GraphiteStatus.merged:
            return "[green]merged[/]"
        case GraphiteStatus.merging:
            return "[cyan]merging[/]"
        case GraphiteStatus.open:
            return f"[link={info.pr_url}][blue underline]PR open[/][/link]"
        case GraphiteStatus.no_pr:
            return "[yellow]no PR[/]"


def _agent_str(agent: ClaudeAgent) -> str:
    if agent.is_active:
        return f"[green]{agent.label} ({agent.activity})[/]"
    return f"{agent.label} ({agent.activity})"


@app.command()
def ls(
    sessions: bool = typer.Option(
        False,
        "--sessions/--no-sessions",
        help="Show the live sessions column.",
    ),
):
    """List current worktrees and their status."""
    worktrees = list_worktrees()

    if not worktrees:
        typer.echo("No worktrees found.")
        return

    # Graphite status comes from the on-disk cache (one read), not a subprocess.
    graphite_info = fetch_all_graphite_info()
    for wt in worktrees:
        wt.set_graphite_info(graphite_info.get(wt.branch))

    # The dirty/unpushed columns each shell out to git per worktree; those queries
    # are independent and I/O-bound, so run them across worktrees concurrently.
    # Removed worktrees get blank columns (the row renders as REMOVED below).
    def _git_cols(wt: Worktree) -> tuple[str, str]:
        if not wt.path.exists():
            return "", ""
        return _dirty_col(wt), _unpushed_col(wt)

    with ThreadPoolExecutor(max_workers=len(worktrees)) as pool:
        git_cols = list(pool.map(_git_cols, worktrees))

    # The Sessions column costs a `claude agents` + per-backend session query, so
    # it's opt-in: by default we skip that work and drop the column entirely.
    session_cols: list[str] = []
    if sessions:
        sessions_by_path: dict[str, list[IsolatedSession]] = {}
        for backend in all_isolation_backends():
            for wt in worktrees:
                if wt.path.exists():
                    for s in backend.list_sessions(wt.path):
                        if s.status == "running":
                            sessions_by_path.setdefault(str(wt.path), []).append(s)

        claude_agents = list_claude_agents()
        agents_by_path = {
            str(wt.path): [a for a in claude_agents if a.is_inside(wt.path)] for wt in worktrees if wt.path.exists()
        }

        for wt in worktrees:
            cells = [s.description() for s in sessions_by_path.get(str(wt.path), [])]
            cells += [_agent_str(a) for a in agents_by_path.get(str(wt.path), [])]
            session_cols.append(", ".join(cells) if cells else "[dim]-[/]")

    table = Table(box=None, pad_edge=False)
    table.add_column("Name", style="bold")
    table.add_column("Branch", style="cyan")
    table.add_column("Dirty")
    table.add_column("Unpushed")
    table.add_column("Sync")
    if sessions:
        table.add_column("Sessions")

    for i, (wt, (dirty, unpushed)) in enumerate(zip(worktrees, git_cols, strict=True)):
        if not wt.path.exists():
            row = [wt.path.name, wt.branch, "[red]REMOVED[/]", "", ""]
        else:
            row = [wt.path.name, wt.branch, dirty, unpushed, _sync_col(wt)]
        if sessions:
            row.append(session_cols[i] if wt.path.exists() else "")
        table.add_row(*row)

    Console().print(table)
