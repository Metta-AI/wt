from pathlib import Path

import pytest
from softmaxwt.config import CmuxOpenerConfig, CmuxSurface
from softmaxwt.opener import cmux
from softmaxwt.opener.cmux import CmuxOpener, build_commands
from softmaxwt.shells import ShellType

ROOT = Path("/root")
WT = Path("/root/.worktrees/foo")


class TestBuildCommands:
    def test_one_surface(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("SHELL", "/bin/zsh")
        config = CmuxOpenerConfig(surfaces=[CmuxSurface(shell=ShellType.shell)])
        assert build_commands(ROOT, WT, "foo", config) == ["/bin/zsh"]

    def test_claude_and_shell(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("SHELL", "/bin/zsh")
        config = CmuxOpenerConfig(surfaces=[CmuxSurface(shell=ShellType.claude), CmuxSurface(shell=ShellType.shell)])
        assert build_commands(ROOT, WT, "foo", config) == ["claude", "/bin/zsh"]


class TestOpen:
    def test_errors_when_cmux_unavailable(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(cmux, "cmux_available", lambda: False)
        with pytest.raises(SystemExit):
            CmuxOpener().open(ROOT, WT, "foo", CmuxOpenerConfig())

    def test_idempotent_open_selects_existing(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(cmux, "cmux_available", lambda: True)
        monkeypatch.setattr(cmux, "_list_workspaces", lambda: [{"ref": "workspace:9", "current_directory": str(WT)}])
        selected: list[str] = []
        monkeypatch.setattr(cmux, "_select_workspace", lambda ws: selected.append(ws))
        # Would raise if a new workspace were created — proves we short-circuited.
        monkeypatch.setattr(cmux, "_new_workspace", lambda *a, **k: pytest.fail("must not create"))

        CmuxOpener().open(ROOT, WT, "foo", CmuxOpenerConfig(focus=True))
        assert selected == ["workspace:9"]

    def test_creates_workspace_and_tab_surface(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("SHELL", "/bin/zsh")
        monkeypatch.setattr(cmux, "cmux_available", lambda: True)

        # The workspace shows up only after _new_workspace; one initial surface,
        # a second after _new_surface.
        state = {"workspaces": [], "surface_refs": ["surface:1"]}
        monkeypatch.setattr(cmux, "_list_workspaces", lambda: state["workspaces"])
        monkeypatch.setattr(
            cmux,
            "_list_panes",
            lambda ws: [{"ref": "pane:1", "surface_refs": list(state["surface_refs"])}],
        )

        created: list = []
        added_surfaces: list = []
        ran: list = []

        def fake_new_workspace(cwd, name, command, focus):
            created.append((cwd, name, command, focus))
            state["workspaces"] = [{"ref": "workspace:5", "current_directory": str(WT)}]

        def fake_new_surface(workspace, pane):
            added_surfaces.append((workspace, pane))
            state["surface_refs"].append("surface:2")

        monkeypatch.setattr(cmux, "_new_workspace", fake_new_workspace)
        monkeypatch.setattr(cmux, "_new_surface", fake_new_surface)
        monkeypatch.setattr(cmux, "_new_split", lambda *a: pytest.fail("tabs must not split"))
        monkeypatch.setattr(cmux, "_run_in_surface", lambda workspace, surface, command: ran.append((surface, command)))

        config = CmuxOpenerConfig(surfaces=[CmuxSurface(shell=ShellType.claude), CmuxSurface(shell=ShellType.shell)])
        CmuxOpener().open(ROOT, WT, "foo", config)

        assert created == [(WT, "foo", "claude", False)]
        assert added_surfaces == [("workspace:5", "pane:1")]
        # The newly-appeared surface ref (surface:2) gets the second command typed in.
        assert ran == [("surface:2", "/bin/zsh")]

    def test_background_init_rides_as_extra_surface(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("SHELL", "/bin/zsh")
        monkeypatch.setattr(cmux, "cmux_available", lambda: True)

        state = {"workspaces": [], "surface_refs": ["surface:1"], "next": 2}
        monkeypatch.setattr(cmux, "_list_workspaces", lambda: state["workspaces"])
        monkeypatch.setattr(
            cmux,
            "_list_panes",
            lambda ws: [{"ref": "pane:1", "surface_refs": list(state["surface_refs"])}],
        )

        def fake_new_workspace(cwd, name, command, focus):
            state["workspaces"] = [{"ref": "workspace:5", "current_directory": str(WT)}]

        def fake_new_surface(workspace, pane):
            state["surface_refs"].append(f"surface:{state['next']}")
            state["next"] += 1

        ran: list = []
        renamed: list = []
        monkeypatch.setattr(cmux, "_new_workspace", fake_new_workspace)
        monkeypatch.setattr(cmux, "_new_surface", fake_new_surface)
        monkeypatch.setattr(cmux, "_run_in_surface", lambda workspace, surface, command: ran.append((surface, command)))
        monkeypatch.setattr(cmux, "_rename_tab", lambda workspace, surface, title: renamed.append((surface, title)))

        config = CmuxOpenerConfig(surfaces=[CmuxSurface(shell=ShellType.shell)])
        CmuxOpener().open(ROOT, WT, "foo", config, init="sh -c 'uv sync'")

        # One real surface (the workspace's initial one ran /bin/zsh as --command),
        # plus a trailing surface dedicated to the init command, tagged "init".
        assert ran == [("surface:2", "sh -c 'uv sync'")]
        assert renamed == [("surface:2", "init")]

    def test_close_noop_when_unavailable(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(cmux, "cmux_available", lambda: False)
        # Must not even list workspaces.
        monkeypatch.setattr(cmux, "_list_workspaces", lambda: pytest.fail("must not list"))
        CmuxOpener().close(ROOT, WT, "foo")
