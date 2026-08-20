import subprocess

import typer
from rich.console import Console

from softmaxwt.app import app
from softmaxwt.claude import ClaudeAgent, list_claude_agents
from softmaxwt.graphite import GraphiteStatus
from softmaxwt.isolation.common import IsolatedSession
from softmaxwt.isolation.registry import all_isolation_backends
from softmaxwt.opener.registry import all_openers
from softmaxwt.worktree import Worktree, branch_exists, complete_worktree_name, find_worktree, git_root, trunk_branch

console = Console()


def _find_sessions(wt: Worktree) -> list[IsolatedSession]:
    sessions: list[IsolatedSession] = []
    for backend in all_isolation_backends():
        sessions.extend(backend.list_sessions(wt.path))
    return sessions


def _print_warnings(wt: Worktree, sessions: list[IsolatedSession], agents: list[ClaudeAgent]) -> None:
    if sessions:
        console.print("  [yellow]Active sessions:[/]")
        for s in sessions:
            console.print(f"    - {s.description()}")

    for agent in agents:
        style = "red" if agent.is_active else "yellow"
        console.print(f"  [{style}]Claude session {agent.label} ({agent.activity}) is running here[/]")

    if wt.path.exists():
        if wt.uncommitted_diff_stats() is not None:
            console.print("  [red]Uncommitted changes in working copy[/]")

    info = wt.graphite_info
    if info is not None and info.status == GraphiteStatus.merged:
        # Graphite says the PR is merged — local upstream/merge state is irrelevant.
        return

    no_upstream = wt.has_no_upstream()
    if no_upstream:
        console.print("  [red]Branch has no remote tracking branch (never pushed)[/]")

    unmerged = wt.unmerged_commits()
    if unmerged:
        console.print(f"  [red]{len(unmerged)} commit(s) not merged to {trunk_branch()}:[/]")
        for c in unmerged[:5]:
            console.print(f"    - {c}")
        if len(unmerged) > 5:
            console.print(f"    ... and {len(unmerged) - 5} more")

    if not no_upstream:
        unpushed = wt.unpushed_commits()
        if unpushed:
            console.print(f"  [red]{len(unpushed)} commit(s) not pushed to remote:[/]")
            for c in unpushed[:5]:
                console.print(f"    - {c}")
            if len(unpushed) > 5:
                console.print(f"    ... and {len(unpushed) - 5} more")


def _force_remove_dir(path) -> None:
    """Remove a directory that may contain root-owned files (e.g. from bazel builds)."""
    subprocess.run(["chmod", "-R", "u+w", str(path)], check=False)
    subprocess.run(["rm", "-rf", str(path)], check=False)
    if path.exists():
        raise RuntimeError(
            f"Failed to remove {path} — directory may contain root-owned files. Try: sudo rm -rf " + str(path)
        )


def destroy_worktree(wt: Worktree) -> None:
    """
    Stop all sessions, remove the worktree, delete its branch, then close any
    UI surface (cmux workspace / zellij tab) opened for it.
    """
    name = wt.path.name
    branch = wt.branch
    root = git_root()

    if wt.path.exists():
        for backend in all_isolation_backends():
            for session in backend.list_sessions(wt.path):
                typer.echo(f"Stopping {session.description()}...")
                session.destroy()

        typer.echo(f"Removing worktree {name}...")
        result = subprocess.run(
            ["git", "worktree", "remove", "--force", str(wt.path)],
            capture_output=True,
        )
        if result.returncode != 0 or wt.path.exists():
            typer.echo("git worktree remove failed, force-cleaning directory...")
            _force_remove_dir(wt.path)
            subprocess.run(["git", "worktree", "prune"], check=True)
    else:
        typer.echo(f"Worktree {name} already removed, pruning...")
        subprocess.run(["git", "worktree", "prune"], check=True)

    result = subprocess.run(["git", "branch", "-D", branch], capture_output=True)
    if result.returncode == 0:
        typer.echo(f"Deleted branch {branch}")

    # Closing the surface is the LAST step on purpose: `self-destroy` runs from
    # inside that surface, and closing it kills this very process.
    for opener in all_openers():
        opener.close(root, wt.path, name)


@app.command()
def destroy(
    name: str = typer.Argument(help="Name of the worktree to destroy", autocompletion=complete_worktree_name),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Stop all sessions and remove the worktree.

    Skips the confirmation prompt when nothing of value would be lost: clean
    tree, no local-only commits (or PR merged), and no active Claude session.
    """
    root = git_root()
    wt = find_worktree(name)
    if wt is None:
        # The directory may already be gone (git worktree pruned) while the branch
        # lingers; still destroyable. But a name matching neither a worktree nor a
        # branch is a typo — fail loudly instead of pretending we cleaned something.
        branch = f"wt/{name}"
        if not (root / ".worktrees" / name).exists() and not branch_exists(branch):
            typer.echo(f"No worktree or branch found for {name!r}.")
            raise typer.Exit(1)
        wt = Worktree(path=root / ".worktrees" / name, branch=branch, head="")

    if not yes:
        agents = [a for a in list_claude_agents() if wt.path.exists() and a.is_inside(wt.path)]
        active = any(a.is_active for a in agents)

        if active or not wt.is_disposable():
            sessions = _find_sessions(wt) if wt.path.exists() else []

            console.print(f"About to destroy worktree [bold]{name}[/]:")
            _print_warnings(wt, sessions, agents)
            console.print()

            confirmation = typer.prompt("Type 'yes' to confirm")
            if confirmation != "yes":
                typer.echo("Aborted.")
                raise typer.Exit(1)

    destroy_worktree(wt)
    typer.echo("Done.")
