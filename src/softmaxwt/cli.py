# ruff: noqa: F401 - imports here have side effects

# register commands
import softmaxwt.command.attach
import softmaxwt.command.config
import softmaxwt.command.create
import softmaxwt.command.destroy
import softmaxwt.command.gc
import softmaxwt.command.ls
import softmaxwt.command.open
import softmaxwt.command.self_destroy

# typer app re-exported as entry point
from softmaxwt.app import app

if __name__ == "__main__":
    app()
