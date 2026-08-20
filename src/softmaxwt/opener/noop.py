from pathlib import Path

from softmaxwt.config import NoopOpenerConfig, OpenerConfig
from softmaxwt.opener.common import Opener


class NoopOpener(Opener):
    """Create the worktree and stop — open nothing."""

    def open(
        self,
        root: Path,
        worktree_path: Path,
        name: str,
        config: OpenerConfig,
        init: str | None = None,
        surface_init: str | None = None,
    ) -> None:
        assert isinstance(config, NoopOpenerConfig)
        assert init is None  # noop opens nothing; nowhere to host background init.
