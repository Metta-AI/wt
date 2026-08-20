import typer

app = typer.Typer(help="CLI wrapper for sandboxed git worktrees.", invoke_without_command=True)


@app.callback()
def main(ctx: typer.Context):
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
