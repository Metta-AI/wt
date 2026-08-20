import os
from pathlib import Path

from softmaxwt.config import InplaceOpenerConfig, OpenerConfig
from softmaxwt.isolation.registry import get_isolation_backend
from softmaxwt.opener.common import Opener
from softmaxwt.shells import combine_scripts


class InplaceOpener(Opener):
    """Replace the current process with the worktree session — exactly one
    surface, in the caller's terminal. The universal default."""

    def open(
        self,
        root: Path,
        worktree_path: Path,
        name: str,
        config: OpenerConfig,
        init: str | None = None,
        surface_init: str | None = None,
    ) -> None:
        assert isinstance(config, InplaceOpenerConfig)
        assert init is None  # inplace execs away; it never hosts background init.
        backend = get_isolation_backend(config.mode)
        command = backend.enter_command(
            root, worktree_path, name, config.shell, init=combine_scripts(surface_init, config.init)
        )
        os.chdir(worktree_path)
        os.execvp(command[0], command)
