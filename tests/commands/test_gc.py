import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

from softmaxwt.claude import ClaudeAgent
from softmaxwt.cli import app
from softmaxwt.command import gc
from softmaxwt.test_support.helpers import invoke
from typer.testing import CliRunner

runner = CliRunner()


def _agent(cwd: Path, status: str) -> ClaudeAgent:
    return ClaudeAgent(pid=1, sessionId="abc", cwd=cwd, kind="interactive", status=status)


@patch("softmaxwt.command.gc.list_claude_agents", lambda: [])
class TestGc:
    def test_nothing_to_clean(self, git_repo: Path):
        result = runner.invoke(app, ["gc"])
        assert "Nothing to clean up" in result.output

    def test_collects_removed_directory(self, git_repo: Path):
        invoke("create", "foo", "--opener", "noop", cwd=git_repo)
        shutil.rmtree(git_repo / ".worktrees" / "foo")

        result = runner.invoke(app, ["gc"], input="y\n")
        assert result.exit_code == 0
        assert "REMOVED" in result.output

    def test_collects_disposable_worktree(self, git_repo: Path):
        # Fresh worktree: clean, no local-only commits => disposable.
        invoke("create", "foo", "--opener", "noop", cwd=git_repo)

        result = runner.invoke(app, ["gc"], input="y\n")
        assert result.exit_code == 0
        assert "foo" in result.output
        assert not (git_repo / ".worktrees" / "foo").exists()

    def test_spares_worktree_with_local_commit(self, git_repo: Path):
        invoke("create", "foo", "--opener", "noop", cwd=git_repo)
        wt_path = git_repo / ".worktrees" / "foo"
        (wt_path / "newfile.txt").write_text("hello")
        subprocess.run(["git", "add", "newfile.txt"], cwd=wt_path, check=True)
        subprocess.run(["git", "commit", "-m", "local work"], cwd=wt_path, check=True)

        result = runner.invoke(app, ["gc"])
        assert "Nothing to clean up" in result.output
        assert wt_path.exists()

    def test_spares_dirty_worktree(self, git_repo: Path):
        invoke("create", "foo", "--opener", "noop", cwd=git_repo)
        (git_repo / ".worktrees" / "foo" / "junk.txt").write_text("wip")

        result = runner.invoke(app, ["gc"])
        assert "Nothing to clean up" in result.output

    def test_aborts_on_no(self, git_repo: Path):
        invoke("create", "foo", "--opener", "noop", cwd=git_repo)

        result = runner.invoke(app, ["gc"], input="n\n")
        assert result.exit_code != 0
        assert (git_repo / ".worktrees" / "foo").exists()


class TestGcClaudeSessions:
    def test_busy_claude_blocks_collection(self, git_repo: Path):
        invoke("create", "foo", "--opener", "noop", cwd=git_repo)
        agent = _agent(git_repo / ".worktrees" / "foo", "busy")

        with patch.object(gc, "list_claude_agents", return_value=[agent]):
            result = runner.invoke(app, ["gc"])

        assert "Skipping" in result.output
        assert "Nothing to clean up" in result.output
        assert (git_repo / ".worktrees" / "foo").exists()

    def test_idle_claude_is_orphaned_with_note(self, git_repo: Path):
        invoke("create", "foo", "--opener", "noop", cwd=git_repo)
        agent = _agent(git_repo / ".worktrees" / "foo", "idle")

        with patch.object(gc, "list_claude_agents", return_value=[agent]):
            result = runner.invoke(app, ["gc"], input="y\n")

        assert result.exit_code == 0
        assert "will orphan" in result.output
        assert not (git_repo / ".worktrees" / "foo").exists()
