"""Running Claude Code sessions, via `claude agents --json`."""

import json
import shutil
import subprocess
from pathlib import Path

from pydantic import BaseModel, Field


class ClaudeAgent(BaseModel):
    """One running Claude Code process. Extra JSON fields are ignored.

    The schema drifts across claude releases, so only the fields wt acts on
    are required. Interactive sessions carry `status` ("busy" | "waiting" |
    "idle"); background agents carry `state` ("working" | "blocked" | ...)
    and may have no pid.
    """

    session_id: str = Field(alias="sessionId")
    cwd: Path
    kind: str  # "interactive" | "background"
    pid: int | None = None
    status: str | None = None
    state: str | None = None
    name: str | None = None  # background agents carry a task name

    def is_inside(self, path: Path) -> bool:
        return self.cwd.resolve().is_relative_to(path.resolve())

    @property
    def label(self) -> str:
        return f"claude:{self.name}" if self.name else "claude"

    @property
    def activity(self) -> str:
        """The session's own activity word: `status` (interactive) or `state`
        (background), whichever is present."""
        return self.status or self.state or "unknown"

    @property
    def is_active(self) -> bool:
        """True when the session may have meaningful work in progress: running
        ("busy"/"working") or stopped mid-task waiting on the user
        ("waiting"/"blocked"). Only a session idling at rest doesn't count, so
        unrecognized activity values err on the active side."""
        return self.activity != "idle"


def list_claude_agents() -> list[ClaudeAgent]:
    """All running Claude Code sessions, or [] when claude isn't installed."""
    if not shutil.which("claude"):
        return []
    result = subprocess.run(["claude", "agents", "--json"], capture_output=True, text=True)
    if result.returncode != 0:
        return []
    return [ClaudeAgent.model_validate(entry) for entry in json.loads(result.stdout)]
