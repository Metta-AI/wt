from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from softmaxwt.shells import ShellType


class IsolationMode(str, Enum):
    raw = "raw"
    nono = "nono"


@dataclass
class IsolatedSession(ABC):
    status: str

    @abstractmethod
    def description(self) -> str: ...

    @abstractmethod
    def destroy(self) -> None: ...


class IsolationBackend(ABC):
    @abstractmethod
    def enter_command(
        self, root: Path, worktree_path: Path, name: str, shell: ShellType, init: str | None = None
    ) -> list[str]:
        """Argv that enters the worktree session under this isolation mode.

        Returns the command WITHOUT running it: an opener can decide whether to
        os.execvp it (inplace) or hand it to a window manager (cmux), or do
        something else.

        The command will be invoked from the worktree's path. `init` is an
        optional surface-init script to run in-process before the shell command
        starts (inside the sandbox, for isolating backends), so exports land in
        the command's environment; on init failure the surface falls back to a
        plain $SHELL instead of running the command.
        """

    @abstractmethod
    def list_sessions(self, worktree_path: Path) -> list[IsolatedSession]: ...
