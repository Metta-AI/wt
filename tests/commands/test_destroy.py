import shutil
import subprocess
from pathlib import Path

from softmaxwt.test_support.helpers import invoke, wt_run


class TestDestroy:
    def test_removes_worktree_and_branch(self, git_repo: Path):
        invoke("create", "foo", "--opener", "noop", cwd=git_repo)
        invoke("destroy", "foo", "-y", cwd=git_repo)

        assert not (git_repo / ".worktrees" / "foo").exists()

        branches = subprocess.run(
            ["git", "branch", "--list", "wt/foo"],
            capture_output=True,
            text=True,
            cwd=git_repo,
        )
        assert "wt/foo" not in branches.stdout

    def test_create_after_destroy_reuses_name(self, git_repo: Path):
        invoke("create", "foo", "--opener", "noop", cwd=git_repo)
        invoke("destroy", "foo", "-y", cwd=git_repo)
        invoke("create", "foo", "--opener", "noop", cwd=git_repo)

        assert (git_repo / ".worktrees" / "foo").exists()

    def test_destroy_after_manual_rm(self, git_repo: Path):
        invoke("create", "foo", "--opener", "noop", cwd=git_repo)

        shutil.rmtree(git_repo / ".worktrees" / "foo")

        result = invoke("destroy", "foo", "-y", cwd=git_repo)
        assert "pruning" in result.stdout

    def test_destroy_unknown_name_fails_cleanly(self, git_repo: Path):
        # Neither a worktree nor a branch: a typo. Must report it, exit non-zero,
        # and not dump a traceback (the old behavior crashed in is_disposable()).
        result = wt_run("destroy", "nope", "-y", cwd=git_repo)
        assert result.returncode != 0
        assert "No worktree or branch found" in result.stdout
        assert "Traceback" not in result.stderr

    def test_destroy_branch_without_worktree_dir(self, git_repo: Path):
        # Branch lingers with local-only work but its directory is gone: destroy
        # must still assess disposability (no FileNotFoundError) and prompt.
        invoke("create", "foo", "--opener", "noop", cwd=git_repo)
        wt_path = git_repo / ".worktrees" / "foo"
        (wt_path / "newfile.txt").write_text("hello")
        subprocess.run(["git", "add", "newfile.txt"], cwd=wt_path, check=True)
        subprocess.run(["git", "commit", "-m", "local work"], cwd=wt_path, check=True)
        shutil.rmtree(wt_path)

        result = wt_run("destroy", "foo", cwd=git_repo, stdin="no\n")
        assert result.returncode != 0  # we answered "no"
        assert "Traceback" not in result.stderr
        assert "not merged" in result.stdout

    def test_destroy_with_unwritable_files(self, git_repo: Path):
        """Simulate bazel leaving read-only files that cause git worktree remove to fail."""
        invoke("create", "foo", "--opener", "noop", cwd=git_repo)

        wt_path = git_repo / ".worktrees" / "foo"
        bazel_dir = wt_path / "bazel-out" / "some-target"
        bazel_dir.mkdir(parents=True)
        locked_file = bazel_dir / "locked.o"
        locked_file.write_text("data")
        locked_file.chmod(0o000)
        bazel_dir.chmod(0o500)

        invoke("destroy", "foo", "-y", cwd=git_repo)

        assert not wt_path.exists()

    def test_squash_merged_branch_shows_no_unmerged_warning(self, git_repo: Path):
        """A branch whose content is squash-merged into main should not warn about unmerged commits."""
        invoke("create", "foo", "--opener", "noop", cwd=git_repo)

        wt_path = git_repo / ".worktrees" / "foo"
        # Make a commit on the worktree branch
        (wt_path / "newfile.txt").write_text("hello")
        subprocess.run(["git", "add", "newfile.txt"], cwd=wt_path, check=True)
        subprocess.run(["git", "commit", "-m", "add newfile"], cwd=wt_path, check=True)

        # Simulate squash-merge onto main: apply the same content as a new commit
        subprocess.run(["git", "checkout", "main"], cwd=git_repo, check=True)
        (git_repo / "newfile.txt").write_text("hello")
        subprocess.run(["git", "add", "newfile.txt"], cwd=git_repo, check=True)
        subprocess.run(["git", "commit", "-m", "squash: add newfile"], cwd=git_repo, check=True)
        subprocess.run(["git", "update-ref", "refs/remotes/origin/main", "main"], cwd=git_repo, check=True)

        # Destroy without -y to see the warnings, then confirm
        result = wt_run("destroy", "foo", cwd=git_repo, stdin="yes\n")
        assert result.returncode == 0
        assert "not merged" not in result.stdout

    def test_destroy_without_yes_aborts_on_no(self, git_repo: Path):
        invoke("create", "foo", "--opener", "noop", cwd=git_repo)
        # Dirty the tree so the worktree isn't disposable and destroy prompts.
        (git_repo / ".worktrees" / "foo" / "junk.txt").write_text("wip")

        result = wt_run("destroy", "foo", cwd=git_repo, stdin="no\n")
        assert result.returncode != 0

        assert (git_repo / ".worktrees" / "foo").exists()

    def test_destroy_disposable_skips_prompt(self, git_repo: Path):
        # Fresh worktree: clean, no local-only commits. No stdin provided — the
        # command must not prompt.
        invoke("create", "foo", "--opener", "noop", cwd=git_repo)

        result = invoke("destroy", "foo", cwd=git_repo)
        assert "confirm" not in result.stdout
        assert not (git_repo / ".worktrees" / "foo").exists()

    def test_destroy_with_local_commit_prompts(self, git_repo: Path):
        invoke("create", "foo", "--opener", "noop", cwd=git_repo)
        wt_path = git_repo / ".worktrees" / "foo"
        (wt_path / "newfile.txt").write_text("hello")
        subprocess.run(["git", "add", "newfile.txt"], cwd=wt_path, check=True)
        subprocess.run(["git", "commit", "-m", "local work"], cwd=wt_path, check=True)

        result = wt_run("destroy", "foo", cwd=git_repo, stdin="no\n")
        assert result.returncode != 0
        assert "not merged" in result.stdout
        assert wt_path.exists()
