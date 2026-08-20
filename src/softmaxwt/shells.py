import os
import shlex
from enum import Enum
from pathlib import Path


class ShellType(str, Enum):
    claude = "claude"
    shell = "shell"

    def get_command(self) -> list[str]:
        match self:
            case ShellType.claude:
                return ["claude"]
            case ShellType.shell:
                return [os.environ.get("SHELL", "/bin/bash")]


def combine_scripts(*scripts: str | None) -> str | None:
    """Concatenate optional shell snippets in order; None when all are absent."""
    parts = [s for s in scripts if s]
    return "\n".join(parts) if parts else None


def wrap_with_init(command: list[str], init: str, root: Path) -> list[str]:
    """Argv that runs `init` in-process before exec'ing `command`, so anything the
    script exports (direnv env, venv) is inherited by the command itself.

    On failure — a nonzero trailing status, or an early exit from the script
    (`set -e`, explicit `exit`) caught by the EXIT trap — it reports the status
    and execs $SHELL instead, so the surface stays open with the error visible
    rather than dying with the pane.
    """
    script = (
        f"export ROOT_REPO={shlex.quote(str(root))}\n"
        "wt_surface_fail() {\n"
        '  if [ "$1" -ne 0 ]; then\n'
        '    echo "⚠ wt: surface init failed (exit $1). Starting a plain shell instead." >&2\n'
        "    trap - EXIT\n"
        '    exec "${SHELL:-/bin/sh}"\n'
        "  fi\n"
        "}\n"
        "trap 'wt_surface_fail $?' EXIT\n"
        f"{init}\n"
        "wt_status=$?\n"
        '[ "$wt_status" -eq 0 ] || wt_surface_fail "$wt_status"\n'
        "trap - EXIT\n"
        f"exec {shlex.join(command)}"
    )
    return ["sh", "-c", script]
