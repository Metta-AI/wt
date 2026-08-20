import os
import subprocess
from pathlib import Path

import pytest


@pytest.fixture()
def git_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a bare-bones git repo and cd into it."""
    # Isolate config from the developer's real ~/.config/wt so subprocess `wt`
    # invocations resolve the builtin default, not whatever they have on disk.
    # The directory must exist: XDG tools treat a nonexistent XDG_CONFIG_HOME
    # as invalid (nono, for one, warns about it — on stdout).
    xdg_config = tmp_path / "xdg_config"
    xdg_config.mkdir()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_config))
    # Shadow claude and nono with no-session stubs so subprocess `wt` calls
    # never see the developer's live sessions — or their output quirks (a real
    # `nono ps --json` logs warnings to stdout, breaking the JSON parse; a real
    # `claude agents --json` returns whatever is running on this machine).
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    for tool in ("claude", "nono"):
        stub = fake_bin / tool
        stub.write_text("#!/bin/sh\necho '[]'\n")
        stub.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ['PATH']}")
    subprocess.run(["git", "init", "-b", "main", str(tmp_path)], check=True, capture_output=True)
    # Per-repo identity so the fixture works inside hermetic test sandboxes
    # (e.g. bazel) where no global git user.name / user.email is configured.
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test"], check=True)
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    # Create a fake origin/main ref so unmerged_commits() works without a real remote.
    subprocess.run(
        ["git", "update-ref", "refs/remotes/origin/main", "main"],
        cwd=tmp_path,
        check=True,
    )
    monkeypatch.chdir(tmp_path)
    return tmp_path
