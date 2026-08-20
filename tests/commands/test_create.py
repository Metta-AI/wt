import subprocess
from pathlib import Path

from softmaxwt.config import Config, Hooks, NoopOpenerConfig, Profile
from softmaxwt.test_support.helpers import invoke, wt_run


def _write_init_profile(name: str, init: str | None, background_init: str | None = None) -> None:
    # git_repo fixture points XDG_CONFIG_HOME at the test dir, so Config.save()
    # lands where the subprocess `wt` will read it. noop opener: just run init.
    config = Config()
    config.profiles[name] = Profile(opener=NoopOpenerConfig(), hooks=Hooks(init=init, background_init=background_init))
    config.save()


class TestInit:
    def test_runs_in_worktree(self, git_repo: Path):
        _write_init_profile("setup", "echo test > init-file")
        invoke("create", "foo", "--profile", "setup", cwd=git_repo)
        assert (git_repo / ".worktrees" / "foo" / "init-file").read_text().strip() == "test"

    def test_root_repo_env_set(self, git_repo: Path):
        _write_init_profile("setup", 'echo "$ROOT_REPO" > root-file')
        invoke("create", "foo", "--profile", "setup", cwd=git_repo)
        content = (git_repo / ".worktrees" / "foo" / "root-file").read_text().strip()
        assert Path(content).resolve() == git_repo.resolve()

    def test_multiline(self, git_repo: Path):
        _write_init_profile("setup", "echo one > a\necho two > b")
        invoke("create", "foo", "--profile", "setup", cwd=git_repo)
        wt = git_repo / ".worktrees" / "foo"
        assert wt.joinpath("a").read_text().strip() == "one"
        assert wt.joinpath("b").read_text().strip() == "two"

    def test_failure_aborts_create(self, git_repo: Path):
        _write_init_profile("setup", "exit 1")
        result = wt_run("create", "foo", "--profile", "setup", cwd=git_repo)
        assert result.returncode != 0

    def test_failure_summarized_not_traceback(self, git_repo: Path):
        _write_init_profile("setup", "exit 3")
        result = wt_run("create", "foo", "--profile", "setup", cwd=git_repo)
        assert result.returncode == 3
        assert "init failed" in result.stdout
        # No Python stacktrace leaks to the user.
        assert "Traceback" not in result.stdout
        assert "Traceback" not in result.stderr

    def test_background_unsupported_warns_and_runs_sync(self, git_repo: Path):
        # noop opener can't host background_init: it must warn and fall back to
        # synchronous, so the file still lands before create returns.
        _write_init_profile("setup", None, background_init="echo test > init-file")
        result = invoke("create", "foo", "--profile", "setup", cwd=git_repo)
        assert "can't run background_init in the background" in result.stdout
        assert (git_repo / ".worktrees" / "foo" / "init-file").read_text().strip() == "test"

    def test_sync_init_runs_before_background_fallback(self, git_repo: Path):
        # Both scripts on an opener without background hosting: init first,
        # then background_init, each seeing the other's ordering.
        _write_init_profile("setup", "echo sync > order", background_init="echo background >> order")
        invoke("create", "foo", "--profile", "setup", cwd=git_repo)
        assert (git_repo / ".worktrees" / "foo" / "order").read_text().splitlines() == ["sync", "background"]

    def test_background_failure_aborts_create_when_sync(self, git_repo: Path):
        _write_init_profile("setup", None, background_init="exit 5")
        result = wt_run("create", "foo", "--profile", "setup", cwd=git_repo)
        assert result.returncode == 5
        assert "background_init failed" in result.stdout

    def test_v1_config_upgraded_with_warning(self, git_repo: Path):
        # A version-1 config (init + init_background: true) still works: the init
        # script moves to hooks.background_init (preserving v1 behavior), and a
        # stale-version warning points at the file.
        config_file = git_repo / "xdg_config" / "wt" / "config.yml"
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(
            "version: 1\nprofiles:\n  setup:\n    init: echo test > init-file\n    init_background: true\n"
            "    opener:\n      type: noop\n"
        )
        result = wt_run("create", "foo", "--profile", "setup", cwd=git_repo)
        assert result.returncode == 0, result.stderr
        assert "upgraded in memory" in result.stderr
        # noop can't host background init, so the migrated script still ran (sync).
        assert (git_repo / ".worktrees" / "foo" / "init-file").read_text().strip() == "test"

    def test_old_fields_rejected_on_current_version(self, git_repo: Path):
        # A config that claims the current version but still has the pre-1.1
        # profile-level init is not silently dropped: the tolerant load warns.
        config_file = git_repo / "xdg_config" / "wt" / "config.yml"
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(
            "version: 1.1\nprofiles:\n  setup:\n    init: echo test > init-file\n    opener:\n      type: noop\n"
        )
        result = wt_run("create", "foo", "--profile", "setup", cwd=git_repo)
        assert result.returncode == 0
        assert "ignoring unknown field(s) in Profile: init" in result.stderr
        # The ignored script must NOT have run.
        assert not (git_repo / ".worktrees" / "foo" / "init-file").exists()


class TestCreate:
    def test_creates_worktree(self, git_repo: Path):
        invoke("create", "foo", "--opener", "noop", cwd=git_repo)

        wt_path = git_repo / ".worktrees" / "foo"
        assert wt_path.exists()

    def test_creates_branch(self, git_repo: Path):
        invoke("create", "foo", "--opener", "noop", cwd=git_repo)

        result = subprocess.run(
            ["git", "branch", "--list", "wt/foo"],
            capture_output=True,
            text=True,
            cwd=git_repo,
        )
        assert "wt/foo" in result.stdout

    def test_prints_path(self, git_repo: Path):
        result = invoke("create", "foo", "--opener", "noop", cwd=git_repo)
        assert "Creating worktree at" in result.stdout
        assert ".worktrees/foo" in result.stdout

    def test_duplicate_name_fails(self, git_repo: Path):
        invoke("create", "foo", "--opener", "noop", cwd=git_repo)
        result = wt_run("create", "foo", "--opener", "noop", cwd=git_repo)
        assert result.returncode != 0
        assert "already exists" in result.stdout

    def test_default_opener_is_inplace_exec(self, git_repo: Path):
        # No opener override: the default inplace opener execs the shell.
        # SHELL=/usr/bin/true (set in wt_run) makes that exec return 0 harmlessly.
        invoke("create", "foo", cwd=git_repo)
        assert (git_repo / ".worktrees" / "foo").exists()
