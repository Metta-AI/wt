import os
import subprocess
from pathlib import Path


def wt_run(*args: str, cwd: Path, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    """Run the wt CLI in a subprocess. Uses SHELL=/usr/bin/true so that
    os.execvp in raw-mode attach harmlessly replaces the child."""
    # COLUMNS keeps rich from wrapping long tmp_path lines, so output assertions
    # can match paths as contiguous substrings.
    env = {**os.environ, "SHELL": "/usr/bin/true", "COLUMNS": "200"}
    return subprocess.run(
        ["wt", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
        input=stdin,
    )


def invoke(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run a wt CLI command, assert success, return result."""
    result = wt_run(*args, cwd=cwd)
    if result.returncode != 0:
        raise AssertionError(f"exit code {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}")
    return result
