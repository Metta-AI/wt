import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from softmaxwt.isolation.common import IsolatedSession, IsolationBackend
from softmaxwt.shells import ShellType, wrap_with_init

# Names the nono profile to sandbox with; nono mode refuses to run without it.
NONO_PROFILE_ENV = "WT_NONO_PROFILE"


@dataclass
class NonoSession(IsolatedSession):
    session_id: str
    name: str
    command: list[str]

    def description(self) -> str:
        cmd = " ".join(self.command)
        return f"nono: {cmd} ({self.status})"

    def destroy(self) -> None:
        if self.status == "running":
            subprocess.run(["nono", "stop", self.session_id], check=True)


@lru_cache(maxsize=1)
def check_nono() -> str | None:
    """Return an error message if nono isn't usable, or None if ok."""
    if not shutil.which("nono"):
        return "'nono' is not installed. Tip: install nono."
    profile = os.environ.get(NONO_PROFILE_ENV)
    if not profile:
        return f"{NONO_PROFILE_ENV} is not set — set it to the nono profile to sandbox with."
    profile_path = Path.home() / ".config" / "nono" / "profiles" / f"{profile}.json"
    if not profile_path.exists():
        return f"nono profile not found: {profile_path}"
    return None


def enforce_nono() -> None:
    err = check_nono()
    if err:
        sys.exit(err)


def _nono_base_args(root: Path, name: str) -> list[str]:
    """Common nono flags for worktree sandboxing."""
    return [
        "-p",
        os.environ[NONO_PROFILE_ENV],
        "--allow-cwd",
        "--allow",
        str(root / ".git"),
        "--name",
        name,
    ]


@lru_cache(maxsize=1)
def _list_nono_sessions() -> list[dict]:
    """Run `nono ps --json` and return parsed JSON, or [] on failure.

    Cached for the process: `wt ls`/`gc` ask once per worktree, but the session
    list is global, so a single `nono ps` covers them all.
    """
    if not shutil.which("nono"):
        return []
    result = subprocess.run(
        ["nono", "ps", "--json"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    return json.loads(result.stdout)


class NonoBackend(IsolationBackend):
    def enter_command(
        self, root: Path, worktree_path: Path, name: str, shell: ShellType, init: str | None = None
    ) -> list[str]:
        """Argv that runs `nono shell` or `nono run …`. Assumes cwd is the worktree.

        A surface init wraps the command *inside* the sandbox (via `nono run`), so
        its exports land in the sandboxed process — including for plain-shell
        surfaces, which otherwise use the more ergonomic `nono shell`.
        """
        enforce_nono()
        if init is None and shell == ShellType.shell:
            return ["nono", "shell", *_nono_base_args(root, name)]
        command = shell.get_command()
        if init is not None:
            command = wrap_with_init(command, init, root)
        return ["nono", "run", *_nono_base_args(root, name), "--", *command]

    def list_sessions(self, worktree_path: Path) -> list[NonoSession]:
        workdir = str(worktree_path)
        return [
            NonoSession(
                status=entry["status"],
                session_id=entry["session_id"],
                name=entry.get("name", ""),
                command=entry.get("command", []),
            )
            for entry in _list_nono_sessions()
            if entry.get("workdir") == workdir
        ]
