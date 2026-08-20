from typing import Optional

import typer

from softmaxwt.app import app
from softmaxwt.config import InplaceOpenerConfig
from softmaxwt.isolation.common import IsolationMode
from softmaxwt.opener.inplace import InplaceOpener
from softmaxwt.shells import ShellType
from softmaxwt.worktree import complete_worktree_name, current_worktree_name, git_root


@app.command()
def attach(
    name: Optional[str] = typer.Argument(
        None,
        help="Name of the worktree to attach to (inferred from cwd if omitted)",
        autocompletion=complete_worktree_name,
    ),
    mode: IsolationMode = typer.Option(IsolationMode.raw, "--mode", "-m", help="Isolation mode."),
    shell: ShellType = typer.Option(ShellType.shell, "--shell", "-s", help="Shell mode."),
):
    """Attach to a worktree in the current terminal (always in-place, one shell)."""
    if name is None:
        name = current_worktree_name()
        if name is None:
            typer.echo("Not inside a worktree — please specify a name.")
            raise typer.Exit(1)

    root = git_root()
    worktree_path = root / ".worktrees" / name

    if not worktree_path.exists():
        typer.echo(f"Worktree not found: {worktree_path}")
        raise typer.Exit(1)

    config = InplaceOpenerConfig(shell=shell, mode=mode)
    InplaceOpener().open(root, worktree_path, name, config)
