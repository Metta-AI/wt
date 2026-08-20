import os
import shlex
import subprocess
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from softmaxwt.app import app
from softmaxwt.config import resolve_profile
from softmaxwt.opener.common import OpenerName
from softmaxwt.opener.registry import get_opener
from softmaxwt.worktree import git_root, trunk_branch

console = Console()


def _stage(message: str) -> None:
    """Announce a top-level step of `create` so it stands out from command output."""
    console.print(f"\n[bold cyan]▸ {message}[/]")


def _init_command(init_background: str, root: Path, worktree_path: Path) -> str:
    """A self-contained `sh -c` string for the init_background snippet: exports the
    create-time env, cds into the worktree, and prints a completion marker so the
    surface it runs in shows when it finished (and its exit status) without
    auto-closing."""
    # The snippet runs in a subshell so an `exit` inside it sets $? instead of
    # killing the marker line that reports completion.
    script = (
        f"export ROOT_REPO={shlex.quote(str(root))}\n"
        f"export PARENT_BRANCH={shlex.quote(trunk_branch())}\n"
        f"cd {shlex.quote(str(worktree_path))}\n"
        f"(\n{init_background}\n)\n"
        'status=$?; [ "$status" -eq 0 ] '
        '&& echo "✅ init finished (exit 0)" '
        '|| echo "❌ init failed (exit $status)"'
    )
    return shlex.join(["sh", "-c", script])


@app.command()
def create(
    name: str = typer.Argument(help="Name for the worktree"),
    profile_name: Optional[str] = typer.Option(None, "--profile", "-p", help="Named opener profile from config."),
    opener_name: Optional[OpenerName] = typer.Option(
        None, "--opener", help="Opener to use directly, with its defaults."
    ),
    opt: list[str] = typer.Option(
        [],
        "--opt",
        "-o",
        help="Override an opener field, e.g. -o focus=true. Repeatable.",
    ),
):
    """Create a new git worktree and open it with the resolved profile.

    Use --opener noop to create the worktree without opening it.
    """
    root = git_root()
    worktree_path = root / ".worktrees" / name
    branch = f"wt/{name}"

    if worktree_path.exists():
        typer.echo(f"Worktree already exists: {worktree_path}")
        raise typer.Exit(1)

    profile = resolve_profile(profile=profile_name, opener=opener_name, opts=opt)

    _stage(f"Creating worktree at {worktree_path} (branch: {branch})")
    subprocess.run(
        [
            "git",
            "worktree",
            "add",
            "-b",
            branch,
            str(worktree_path),
            trunk_branch(),
        ],
        check=True,
    )

    # `hooks.init` is the synchronous half: surfaces (claude in particular) must
    # only start once it has succeeded, so it always runs before opening.
    # `hooks.background_init` is the slow, non-blocking half; it rides in its own
    # surface on openers that can host it, and degrades to a second synchronous
    # step (with a warning) on those that can't.
    sync_scripts: list[tuple[str, str]] = []
    if profile.hooks.init is not None:
        sync_scripts.append(("init", profile.hooks.init))
    background = profile.hooks.background_init
    if background is not None and not get_opener(profile.opener.type).hosts_background_init:
        console.print(
            f"[yellow]⚠ {profile.opener.type.value} opener can't run background_init in the background; "
            f"running it synchronously.[/]"
        )
        sync_scripts.append(("background_init", background))
        background = None

    for label, script in sync_scripts:
        _stage(f"Running {label}")
        result = subprocess.run(
            script,
            shell=True,
            cwd=worktree_path,
            env={**os.environ, "ROOT_REPO": str(root), "PARENT_BRANCH": trunk_branch()},
        )
        if result.returncode != 0:
            console.print(
                f"[bold red]✗ {label} failed[/] (exit {result.returncode}). "
                f"The worktree was created at {worktree_path} but not opened."
            )
            raise typer.Exit(result.returncode)

    _stage(f"Opening worktree ({profile.opener.type.value})")
    init_command: Optional[str] = None
    if background is not None:
        init_command = _init_command(background, root, worktree_path)

    opener = get_opener(profile.opener.type)
    opener.open(
        root,
        worktree_path,
        name,
        config=profile.opener,
        init=init_command,
        surface_init=profile.hooks.surface_init,
    )
