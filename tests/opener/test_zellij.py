from pathlib import Path

import pytest
from softmaxwt.config import ZellijOpenerConfig, ZellijSurface
from softmaxwt.opener import zellij
from softmaxwt.opener.zellij import ZellijOpener, build_commands
from softmaxwt.shells import ShellType

ROOT = Path("/root")
WT = Path("/root/.worktrees/foo")


@pytest.fixture(autouse=True)
def _installed_in_session(monkeypatch: pytest.MonkeyPatch):
    """Default: zellij installed and we're inside a session named 'sess'."""
    monkeypatch.setattr(zellij, "zellij_installed", lambda: True)
    monkeypatch.setenv("ZELLIJ_SESSION_NAME", "sess")


class TestBuildCommands:
    def test_one_surface(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("SHELL", "/bin/zsh")
        config = ZellijOpenerConfig(surfaces=[ZellijSurface(shell=ShellType.shell)])
        assert build_commands(ROOT, WT, "foo", config) == [["/bin/zsh"]]

    def test_claude_and_shell(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("SHELL", "/bin/zsh")
        config = ZellijOpenerConfig(
            surfaces=[ZellijSurface(shell=ShellType.claude), ZellijSurface(shell=ShellType.shell)]
        )
        assert build_commands(ROOT, WT, "foo", config) == [["claude"], ["/bin/zsh"]]

    def test_surface_init_wraps_every_surface(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("SHELL", "/bin/zsh")
        config = ZellijOpenerConfig(
            surfaces=[ZellijSurface(shell=ShellType.claude), ZellijSurface(shell=ShellType.shell)]
        )
        commands = build_commands(ROOT, WT, "foo", config, surface_init="direnv allow")
        for command, exec_target in zip(commands, ["claude", "/bin/zsh"], strict=True):
            assert command[:2] == ["sh", "-c"]
            assert "direnv allow" in command[2]
            assert f"exec {exec_target}" in command[2]

    def test_per_surface_init_appends_after_profile_init(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("SHELL", "/bin/zsh")
        config = ZellijOpenerConfig(
            surfaces=[ZellijSurface(shell=ShellType.claude, init="echo claude-extra"), ZellijSurface()]
        )
        claude_cmd, shell_cmd = build_commands(ROOT, WT, "foo", config, surface_init="echo shared")
        assert claude_cmd[2].index("echo shared") < claude_cmd[2].index("echo claude-extra")
        # The second surface has no init of its own: only the shared script.
        assert "claude-extra" not in shell_cmd[2]

    def test_no_init_no_wrapper(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("SHELL", "/bin/zsh")
        config = ZellijOpenerConfig(surfaces=[ZellijSurface(shell=ShellType.claude)])
        assert build_commands(ROOT, WT, "foo", config, surface_init=None) == [["claude"]]


class TestOpen:
    def test_errors_when_not_installed(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(zellij, "zellij_installed", lambda: False)
        with pytest.raises(SystemExit):
            ZellijOpener().open(ROOT, WT, "foo", ZellijOpenerConfig())

    def test_errors_when_no_session(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("ZELLIJ_SESSION_NAME", raising=False)
        with pytest.raises(SystemExit):
            ZellijOpener().open(ROOT, WT, "foo", ZellijOpenerConfig())

    def test_config_session_overrides_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("SHELL", "/bin/zsh")
        monkeypatch.setattr(zellij, "_query_tab_names", lambda session: [])
        new_tabs: list = []
        monkeypatch.setattr(zellij, "_new_tab", lambda s, n, c, cmd: new_tabs.append(s))
        # Different session than the env: focus restore is skipped, no current-tab-info.
        monkeypatch.setattr(zellij, "_current_tab_id", lambda s: pytest.fail("must not query focus"))

        ZellijOpener().open(ROOT, WT, "foo", ZellijOpenerConfig(session="other", surfaces=[ZellijSurface()]))
        assert new_tabs == ["other"]

    def test_idempotent_open_focuses_existing(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(zellij, "_query_tab_names", lambda session: ["other", "foo"])
        went: list = []
        monkeypatch.setattr(zellij, "_go_to_tab_name", lambda s, n: went.append((s, n)))
        # Would raise if a new tab were created — proves we short-circuited.
        monkeypatch.setattr(zellij, "_new_tab", lambda *a: pytest.fail("must not create"))

        ZellijOpener().open(ROOT, WT, "foo", ZellijOpenerConfig(focus=True))
        assert went == [("sess", "foo")]

    def test_idempotent_open_no_focus_does_not_move(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(zellij, "_query_tab_names", lambda session: ["foo"])
        monkeypatch.setattr(zellij, "_go_to_tab_name", lambda *a: pytest.fail("must not move focus"))
        monkeypatch.setattr(zellij, "_new_tab", lambda *a: pytest.fail("must not create"))
        ZellijOpener().open(ROOT, WT, "foo", ZellijOpenerConfig(focus=False))

    def test_creates_tab_and_panes_restoring_focus(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("SHELL", "/bin/zsh")
        monkeypatch.setattr(zellij, "_query_tab_names", lambda session: [])
        monkeypatch.setattr(zellij, "_current_tab_id", lambda session: 3)

        tabs: list = []
        panes: list = []
        restored: list = []
        monkeypatch.setattr(zellij, "_new_tab", lambda s, n, cwd, cmd: tabs.append((n, cwd, cmd)))
        monkeypatch.setattr(zellij, "_new_pane", lambda s, cwd, opts, cmd: panes.append((opts, cmd)))
        monkeypatch.setattr(zellij, "_go_to_tab_id", lambda s, tid: restored.append(tid))

        config = ZellijOpenerConfig(
            surfaces=[ZellijSurface(shell=ShellType.claude), ZellijSurface(shell=ShellType.shell)]
        )
        ZellijOpener().open(ROOT, WT, "foo", config)

        # Tab named after the worktree, first surface as its initial command.
        assert tabs == [("foo", WT, ["claude"])]
        # One extra pane (the second surface); no pane_options set, so empty argv.
        assert panes == [([], ["/bin/zsh"])]
        # focus=False in the current session → previously-focused tab is restored.
        assert restored == [3]

    def test_focus_true_does_not_restore(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("SHELL", "/bin/zsh")
        monkeypatch.setattr(zellij, "_query_tab_names", lambda session: [])
        monkeypatch.setattr(zellij, "_current_tab_id", lambda s: pytest.fail("must not query focus"))
        monkeypatch.setattr(zellij, "_new_tab", lambda *a: None)
        monkeypatch.setattr(zellij, "_go_to_tab_id", lambda *a: pytest.fail("must not restore focus"))

        ZellijOpener().open(ROOT, WT, "foo", ZellijOpenerConfig(focus=True, surfaces=[ZellijSurface()]))

    def test_pane_options_passed_verbatim(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("SHELL", "/bin/zsh")
        monkeypatch.setattr(zellij, "_query_tab_names", lambda session: [])
        monkeypatch.setattr(zellij, "_current_tab_id", lambda session: 0)
        monkeypatch.setattr(zellij, "_new_tab", lambda *a: None)
        monkeypatch.setattr(zellij, "_go_to_tab_id", lambda *a: None)
        panes: list = []
        monkeypatch.setattr(zellij, "_new_pane", lambda s, cwd, opts, cmd: panes.append(opts))

        config = ZellijOpenerConfig(
            surfaces=[
                # First surface's pane_options are ignored (it becomes the tab command).
                ZellijSurface(pane_options="-d right"),
                ZellijSurface(pane_options="-d right"),
                ZellijSurface(pane_options="-d down --name extra"),
            ]
        )
        ZellijOpener().open(ROOT, WT, "foo", config)
        # Each later surface's pane_options reach new-pane as split argv.
        assert panes == [["-d", "right"], ["-d", "down", "--name", "extra"]]

    def test_background_init_rides_as_named_pane(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("SHELL", "/bin/zsh")
        monkeypatch.setattr(zellij, "_query_tab_names", lambda session: [])
        monkeypatch.setattr(zellij, "_current_tab_id", lambda session: 0)
        monkeypatch.setattr(zellij, "_new_tab", lambda *a: None)
        monkeypatch.setattr(zellij, "_go_to_tab_id", lambda *a: None)
        panes: list = []
        monkeypatch.setattr(zellij, "_new_pane", lambda s, cwd, opts, cmd: panes.append((opts, cmd)))

        config = ZellijOpenerConfig(surfaces=[ZellijSurface(shell=ShellType.shell)])
        ZellijOpener().open(ROOT, WT, "foo", config, init="sh -c 'uv sync'")

        # The init command rides as a trailing pane named "init", argv-split (no shell wrapper).
        assert panes == [(["--name", "init"], ["sh", "-c", "uv sync"])]


class TestClose:
    def test_close_noop_when_not_installed(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(zellij, "zellij_installed", lambda: False)
        monkeypatch.setattr(zellij, "_query_tab_names", lambda s: pytest.fail("must not query"))
        ZellijOpener().close(ROOT, WT, "foo")

    def test_close_noop_outside_session(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("ZELLIJ_SESSION_NAME", raising=False)
        monkeypatch.setattr(zellij, "_query_tab_names", lambda s: pytest.fail("must not query"))
        ZellijOpener().close(ROOT, WT, "foo")

    def test_close_noop_when_tab_absent(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(zellij, "_query_tab_names", lambda session: ["other"])
        monkeypatch.setattr(zellij, "_go_to_tab_name", lambda *a: pytest.fail("must not move focus"))
        monkeypatch.setattr(zellij, "_close_tab", lambda *a: pytest.fail("must not close"))
        ZellijOpener().close(ROOT, WT, "foo")

    def test_close_focuses_then_closes(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(zellij, "_query_tab_names", lambda session: ["foo"])
        calls: list = []
        monkeypatch.setattr(zellij, "_go_to_tab_name", lambda s, n: calls.append(("go", s, n)))
        monkeypatch.setattr(zellij, "_close_tab", lambda s: calls.append(("close", s)))
        ZellijOpener().close(ROOT, WT, "foo")
        assert calls == [("go", "sess", "foo"), ("close", "sess")]
