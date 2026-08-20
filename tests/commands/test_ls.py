import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

from softmaxwt.claude import ClaudeAgent
from softmaxwt.cli import app
from softmaxwt.command import ls
from softmaxwt.test_support.helpers import invoke
from typer.testing import CliRunner

runner = CliRunner()


def _no_sessions(*_args, **_kwargs):
    return []


@patch("softmaxwt.command.ls.list_claude_agents", _no_sessions)
class TestLs:
    @patch("softmaxwt.isolation.nono.NonoBackend.list_sessions", _no_sessions)
    def test_empty(self, git_repo: Path):
        result = runner.invoke(app, ["ls"])
        assert "No worktrees found" in result.output

    @patch("softmaxwt.isolation.nono.NonoBackend.list_sessions", _no_sessions)
    def test_shows_worktree(self, git_repo: Path):
        invoke("create", "bar", "--opener", "noop", cwd=git_repo)
        result = runner.invoke(app, ["ls"])
        assert "bar" in result.output

    @patch("softmaxwt.isolation.nono.NonoBackend.list_sessions", _no_sessions)
    def test_shows_removed(self, git_repo: Path):
        invoke("create", "bar", "--opener", "noop", cwd=git_repo)

        shutil.rmtree(git_repo / ".worktrees" / "bar")

        result = runner.invoke(app, ["ls"])
        assert "bar" in result.output
        assert "REMOVED" in result.output

    @patch("softmaxwt.isolation.nono.NonoBackend.list_sessions", _no_sessions)
    def test_shows_claude_session(self, git_repo: Path):
        invoke("create", "bar", "--opener", "noop", cwd=git_repo)
        agent = ClaudeAgent(
            pid=1,
            sessionId="abc",
            cwd=git_repo / ".worktrees" / "bar",
            kind="interactive",
            status="busy",
        )
        with patch.object(ls, "list_claude_agents", return_value=[agent]):
            result = runner.invoke(app, ["ls", "--sessions"])
        assert "claude (busy)" in result.output

    @patch("softmaxwt.isolation.nono.NonoBackend.list_sessions", _no_sessions)
    def test_default_skips_session_query(self, git_repo: Path):
        """The default (no --sessions) drops the Sessions column and never queries claude/nono."""
        invoke("create", "bar", "--opener", "noop", cwd=git_repo)
        claude_spy = MagicMock(return_value=[])
        with patch.object(ls, "list_claude_agents", claude_spy):
            result = runner.invoke(app, ["ls"])

        assert "bar" in result.output
        assert "Sessions" not in result.output
        claude_spy.assert_not_called()
