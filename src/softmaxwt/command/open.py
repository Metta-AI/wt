from typing import Optional

import typer

from softmaxwt.app import app
from softmaxwt.config import resolve_profile
from softmaxwt.opener.common import OpenerName
from softmaxwt.opener.registry import get_opener
from softmaxwt.worktree import complete_worktree_name, current_worktree_name, git_root


@app.command()
def open(
    name: Optional[str] = typer.Argument(
        None,
        help="Worktree to open (inferred from cwd if omitted).",
        autocompletion=complete_worktree_name,
    ),
    profile: Optional[str] = typer.Option(None, "--profile", "-p", help="Named opener profile from config."),
    opener: Optional[OpenerName] = typer.Option(None, "--opener", help="Opener to use directly, with its defaults."),
    opt: list[str] = typer.Option([], "--opt", "-o", help="Override an opener field, e.g. -o focus=true. Repeatable."),
):
    """Open an existing worktree with the resolved opener profile."""
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

    resolved_profile = resolve_profile(profile=profile, opener=opener, opts=opt)
    resolved_opener = get_opener(resolved_profile.opener.type)
    # Surface init runs on every open (it's part of the surface command); the
    # create-only hooks (init, background_init) don't.
    resolved_opener.open(
        root, worktree_path, name, resolved_profile.opener, surface_init=resolved_profile.hooks.surface_init
    )
