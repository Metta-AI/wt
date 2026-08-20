import os
import shlex
import subprocess

import typer
from rich.console import Console
from rich.table import Table

from softmaxwt.app import app
from softmaxwt.config import CmuxOpenerConfig, Config, InplaceOpenerConfig, ZellijOpenerConfig, config_path

config_app = typer.Typer(help="View and edit wt configuration.", invoke_without_command=True)
app.add_typer(config_app, name="config")


@config_app.callback()
def config_main(ctx: typer.Context):
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())


@config_app.command("list")
def list_config(
    raw: bool = typer.Option(False, "--raw", help="Show the stored config file as-is."),
):
    """Show the default profile and the profiles defined in config."""
    config = Config.load()
    if raw:
        Console().print(config.model_dump(mode="json", exclude_none=True))
        return

    console = Console()
    console.print(f"default profile: [bold]{config.default_profile or '(builtin inplace)'}[/]")

    if not config.profiles:
        console.print("[dim]No profiles defined. Add them under `profiles:` in the config file.[/]")
        return

    table = Table(box=None, pad_edge=False)
    table.add_column("Profile", style="bold")
    table.add_column("Opener", style="cyan")
    table.add_column("Detail")
    for profile_name, profile in config.profiles.items():
        opener = profile.opener
        if isinstance(opener, (CmuxOpenerConfig, ZellijOpenerConfig)):
            detail = f"{len(opener.surfaces)} surfaces"
        elif isinstance(opener, InplaceOpenerConfig):
            detail = opener.shell.value
        else:
            detail = ""
        table.add_row(profile_name, opener.type.value, detail)
    console.print(table)


@config_app.command("edit")
def edit_config():
    """Open the config file in $EDITOR (or $VISUAL)."""
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR")
    if not editor:
        typer.echo("No editor set. Set $EDITOR (or $VISUAL) to your preferred editor.")
        raise typer.Exit(1)

    path = config_path()
    if not path.exists():
        # Seed a valid file so the editor opens onto a parseable starting point
        # rather than an empty buffer the user has to construct from scratch.
        Config().save()

    subprocess.run([*shlex.split(editor), str(path)], check=True)


@config_app.command("set-default")
def set_default(
    profile: str = typer.Argument(help="Profile to use as the default for create/open."),
):
    """Set the default profile."""
    config = Config.load()
    if profile not in config.profiles:
        known = ", ".join(sorted(config.profiles)) or "(none)"
        typer.echo(f"Unknown profile: {profile}. Known profiles: {known}")
        raise typer.Exit(1)

    config.default_profile = profile
    config.save()
    typer.echo(f"Default profile set to {profile}")
