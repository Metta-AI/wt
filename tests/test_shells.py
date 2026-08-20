import subprocess
from pathlib import Path

from softmaxwt.shells import combine_scripts, wrap_with_init

ROOT = Path("/root")


def _run(command: list[str], **env: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, env={"PATH": "/usr/bin:/bin", **env})


class TestCombineScripts:
    def test_all_none_is_none(self):
        assert combine_scripts(None, None) is None

    def test_order_preserved(self):
        assert combine_scripts("a", None, "b") == "a\nb"


class TestWrapWithInit:
    def test_init_env_reaches_command(self):
        # Exports from the init script must land in the exec'd command itself —
        # that's the whole point (direnv env into claude).
        result = _run(wrap_with_init(["sh", "-c", "echo $WT_TEST_VAR"], "export WT_TEST_VAR=hello", ROOT))
        assert result.returncode == 0
        assert result.stdout.strip() == "hello"

    def test_root_repo_exported(self):
        result = _run(wrap_with_init(["sh", "-c", "echo $ROOT_REPO"], ":", ROOT))
        assert result.stdout.strip() == str(ROOT)

    def test_failure_falls_back_to_shell(self):
        # On init failure the surface must drop into $SHELL (visible error, pane
        # stays alive) instead of running the command. /usr/bin/false as $SHELL
        # makes the fallback observable via the exit code.
        result = _run(wrap_with_init(["sh", "-c", "echo ran"], "exit 3", ROOT), SHELL="/usr/bin/false")
        assert "ran" not in result.stdout
        assert "surface init failed (exit 3)" in result.stderr

    def test_failure_mid_script_falls_back(self):
        # An `exit` (or set -e death) mid-script skips the trailing status check;
        # the EXIT trap must still catch it and not run the command.
        result = _run(
            wrap_with_init(["sh", "-c", "echo ran"], "set -e\nfalse\necho unreachable", ROOT),
            SHELL="/usr/bin/false",
        )
        assert "ran" not in result.stdout
        assert "unreachable" not in result.stdout
        assert "surface init failed" in result.stderr
