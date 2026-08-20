import os

import typer

from softmaxwt.app import app
from softmaxwt.command.destroy import destroy_worktree
from softmaxwt.worktree import current_worktree_name, find_worktree, git_root


@app.command(name="self-destroy")
def self_destroy():
    """
    Destroy the worktree the current directory is inside. No confirmation.
    """
    name = current_worktree_name()
    if name is None:
        typer.echo("Not inside a worktree — nothing to self-destroy.")
        raise typer.Exit(1)

    wt = find_worktree(name)
    if wt is None:
        typer.echo(f"Could not resolve worktree {name!r} from git.")
        raise typer.Exit(1)

    # Step out to the main repo root first, since git refuses to remove the
    # directory a process is running in.
    os.chdir(git_root())

    destroy_worktree(wt)
    typer.echo("Done.")
