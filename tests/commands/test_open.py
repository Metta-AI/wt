from pathlib import Path
from unittest.mock import patch

from softmaxwt.cli import app
from softmaxwt.config import Config, Hooks, InplaceOpenerConfig, Profile
from softmaxwt.test_support.helpers import invoke
from typer.testing import CliRunner

runner = CliRunner()


class TestOpen:
    def test_open_inplace_execs(self, git_repo: Path):
        invoke("create", "foo", "--opener", "noop", cwd=git_repo)

        with patch("os.execvp") as mock_execvp:
            result = runner.invoke(app, ["open", "foo", "--opener", "inplace"])

        assert result.exit_code == 0
        mock_execvp.assert_called_once()

    def test_open_runs_surface_init(self, git_repo: Path):
        # Unlike the create-only hooks, surface_init is part of the surface
        # command itself, so `wt open` runs it too.
        invoke("create", "foo", "--opener", "noop", cwd=git_repo)
        config = Config()
        config.profiles["dev"] = Profile(
            opener=InplaceOpenerConfig(), hooks=Hooks(surface_init="echo surface-init-ran")
        )
        config.save()

        with patch("os.execvp") as mock_execvp:
            result = runner.invoke(app, ["open", "foo", "--profile", "dev"])

        assert result.exit_code == 0
        command = mock_execvp.call_args.args[1]
        assert command[:2] == ["sh", "-c"]
        assert "echo surface-init-ran" in command[2]

    def test_open_nonexistent_worktree(self, git_repo: Path):
        result = runner.invoke(app, ["open", "nope"])
        assert result.exit_code != 0
        assert "Worktree not found" in result.output

    def test_open_cmux_unavailable_errors(self, git_repo: Path):
        invoke("create", "foo", "--opener", "noop", cwd=git_repo)

        with patch("softmaxwt.opener.cmux.cmux_available", return_value=False):
            result = runner.invoke(app, ["open", "foo", "--opener", "cmux"])

        assert result.exit_code != 0
        assert "cmux is not available" in result.output

    def test_open_profile_and_opener_conflict(self, git_repo: Path):
        invoke("create", "foo", "--opener", "noop", cwd=git_repo)
        result = runner.invoke(app, ["open", "foo", "--profile", "x", "--opener", "inplace"])
        assert result.exit_code != 0
