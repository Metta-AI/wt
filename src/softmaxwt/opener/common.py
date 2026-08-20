from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from softmaxwt.config import OpenerConfig


class OpenerName(str, Enum):
    """How a worktree is presented once created."""

    inplace = "inplace"
    cmux = "cmux"
    zellij = "zellij"
    noop = "noop"


class Opener(ABC):
    """Controls how a worktree is presented to the user once created.

    When the opener can tell a worktree is already open, `open` may behave
    idempotently — reattach instead of duplicating. See the cmux opener.
    """

    # True if this opener can run a profile's `background_init` snippet
    # concurrently with opening (e.g. in its own cmux surface). Openers that exec
    # away (inplace) or surface nothing (noop) can't, so `create` runs it
    # synchronously for them.
    hosts_background_init: bool = False

    @abstractmethod
    def open(
        self,
        root: Path,
        worktree_path: Path,
        name: str,
        config: OpenerConfig,
        init: str | None = None,
        surface_init: str | None = None,
    ) -> None:
        """Open the worktree.

        `init` is a background init command this opener has agreed to host (only
        ever passed on create, when `hosts_background_init` is set). `surface_init`
        is the profile's `hooks.surface_init` script, run inside every surface
        before its command — on create and open alike."""

    def close(self, root: Path, worktree_path: Path, name: str) -> None:
        return None
