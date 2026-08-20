import subprocess
from pathlib import Path

from softmaxwt.test_support.helpers import invoke, wt_run


class TestSelfDestroy:
    def test_destroys_current_worktree(self, git_repo: Path):
        invoke("create", "foo", "--opener", "noop", cwd=git_repo)
        wt_path = git_repo / ".worktrees" / "foo"

        invoke("self-destroy", cwd=wt_path)

        assert not wt_path.exists()
        branches = subprocess.run(
            ["git", "branch", "--list", "wt/foo"],
            capture_output=True,
            text=True,
            cwd=git_repo,
        )
        assert "wt/foo" not in branches.stdout

    def test_no_confirmation_even_with_local_commits(self, git_repo: Path):
        # The whole point: self-destroy never prompts. A worktree with unmerged
        # local commits (which `destroy` would prompt about) is torn down anyway.
        invoke("create", "foo", "--opener", "noop", cwd=git_repo)
        wt_path = git_repo / ".worktrees" / "foo"
        (wt_path / "newfile.txt").write_text("hello")
        subprocess.run(["git", "add", "newfile.txt"], cwd=wt_path, check=True)
        subprocess.run(["git", "commit", "-m", "local work"], cwd=wt_path, check=True)

        result = invoke("self-destroy", cwd=wt_path)

        assert "confirm" not in result.stdout
        assert not wt_path.exists()

    def test_outside_worktree_errors(self, git_repo: Path):
        result = wt_run("self-destroy", cwd=git_repo)

        assert result.returncode != 0
        assert "Not inside a worktree" in result.stdout
