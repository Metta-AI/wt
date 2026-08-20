from pathlib import Path

from softmaxwt.isolation.common import IsolatedSession, IsolationBackend
from softmaxwt.shells import ShellType, wrap_with_init


class RawBackend(IsolationBackend):
    def enter_command(
        self, root: Path, worktree_path: Path, name: str, shell: ShellType, init: str | None = None
    ) -> list[str]:
        command = shell.get_command()
        if init is None:
            return command
        return wrap_with_init(command, init, root)

    def list_sessions(self, worktree_path: Path) -> list[IsolatedSession]:
        return []
