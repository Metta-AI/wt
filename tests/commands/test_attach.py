from pathlib import Path
from unittest.mock import patch

import pytest
from softmaxwt.cli import app
from softmaxwt.test_support.helpers import invoke
from typer.testing import CliRunner

runner = CliRunner()


class TestAttach:
    def test_attach_by_name(self, git_repo: Path):
        invoke("create", "foo", "--opener", "noop", cwd=git_repo)

        with patch("os.execvp") as mock_execvp:
            result = runner.invoke(app, ["attach", "foo", "-m", "raw"])

        assert result.exit_code == 0
        mock_execvp.assert_called_once()

    def test_attach_infers_name_from_cwd(self, git_repo: Path, monkeypatch: pytest.MonkeyPatch):
        invoke("create", "foo", "--opener", "noop", cwd=git_repo)
        monkeypatch.chdir(git_repo / ".worktrees" / "foo")

        with patch("os.execvp") as mock_execvp:
            result = runner.invoke(app, ["attach", "-m", "raw"])

        assert result.exit_code == 0
        mock_execvp.assert_called_once()

    def test_attach_infers_from_subdirectory(self, git_repo: Path, monkeypatch: pytest.MonkeyPatch):
        invoke("create", "foo", "--opener", "noop", cwd=git_repo)
        subdir = git_repo / ".worktrees" / "foo" / "deep" / "nested"
        subdir.mkdir(parents=True)
        monkeypatch.chdir(subdir)

        with patch("os.execvp") as mock_execvp:
            result = runner.invoke(app, ["attach", "-m", "raw"])

        assert result.exit_code == 0
        mock_execvp.assert_called_once()

    def test_attach_no_name_outside_worktree(self, git_repo: Path):
        result = runner.invoke(app, ["attach", "-m", "raw"])

        assert result.exit_code != 0
        assert "Not inside a worktree" in result.output

    def test_attach_nonexistent_worktree(self, git_repo: Path):
        with patch("os.execvp"):
            result = runner.invoke(app, ["attach", "nonexistent", "-m", "raw"])

        assert result.exit_code != 0
        assert "Worktree not found" in result.output
