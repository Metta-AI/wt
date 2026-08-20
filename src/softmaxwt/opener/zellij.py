import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from softmaxwt.config import OpenerConfig, ZellijOpenerConfig
from softmaxwt.isolation.registry import get_isolation_backend
from softmaxwt.opener.common import Opener
from softmaxwt.shells import combine_scripts

# --- thin zellij CLI wrappers (monkeypatched in tests) -------------------------
#
# Every `zellij action` is routed at an explicit --session so open/close never
# depend on which session the calling client happens to be attached to. Tabs are
# discovered by name (the tab is named after the worktree); pane placement rides
# zellij's focus model rather than the ambiguous `--tab-id` flag — `new-tab`
# focuses the tab it creates, and `new-pane` lands in the focused tab.


def zellij_installed() -> bool:
    return bool(shutil.which("zellij"))


def _run(session: str, *args: str) -> str:
    """Run a zellij subcommand against `session`, returning stripped stdout.

    On failure, surface zellij's own stderr and exit — a raw CalledProcessError
    traceback hides the actual complaint (e.g. a bad `pane_options` argument)."""
    result = subprocess.run(["zellij", "--session", session, *args], capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"zellij {shlex.join(args)} failed (exit {result.returncode}):\n{result.stderr.strip()}")
    return result.stdout.strip()


def _query_tab_names(session: str) -> list[str]:
    return _run(session, "action", "query-tab-names").splitlines()


def _current_tab_id(session: str) -> int:
    """Stable id of the session's focused tab (for restoring focus afterwards)."""
    out = _run(session, "action", "current-tab-info")
    for line in out.splitlines():
        if line.startswith("id:"):
            return int(line.split(":", 1)[1])
    raise RuntimeError(f"zellij current-tab-info reported no id:\n{out}")


def _new_tab(session: str, name: str, cwd: Path, command: list[str]) -> None:
    _run(session, "action", "new-tab", "--name", name, "--cwd", str(cwd), "--", *command)


def _new_pane(session: str, cwd: Path, options: list[str], command: list[str]) -> None:
    # `options` is the surface's verbatim `pane_options` (e.g. "-d horizontal"),
    # already split into argv; --cwd is forced so the pane opens in the worktree.
    _run(session, "action", "new-pane", "--cwd", str(cwd), *options, "--", *command)


def _go_to_tab_name(session: str, name: str) -> None:
    _run(session, "action", "go-to-tab-name", name)


def _go_to_tab_id(session: str, tab_id: int) -> None:
    _run(session, "action", "go-to-tab-by-id", str(tab_id))


def _close_tab(session: str) -> None:
    _run(session, "action", "close-tab")


# --- opener --------------------------------------------------------------------


def build_commands(
    root: Path, worktree_path: Path, name: str, config: ZellijOpenerConfig, surface_init: str | None = None
) -> list[list[str]]:
    """Argv per surface, via each surface's isolation mode. zellij takes argv after
    `--`, so (unlike cmux) these are never joined into shell strings. Each surface's
    init is the profile-wide `surface_init` followed by its own `init`."""
    return [
        get_isolation_backend(s.mode).enter_command(
            root, worktree_path, name, s.shell, init=combine_scripts(surface_init, s.init)
        )
        for s in config.surfaces
    ]


def _resolve_session(config: ZellijOpenerConfig) -> str:
    session = config.session or os.environ.get("ZELLIJ_SESSION_NAME")
    if session is None:
        sys.exit("No zellij session — run wt from inside zellij, or set `session` in the opener config.")
    return session


class ZellijOpener(Opener):
    """Opener for the https://zellij.dev terminal multiplexer.

    Opens a new tab named after the worktree in an existing zellij session and
    fills it with one pane per configured surface. The session is the current
    one (`$ZELLIJ_SESSION_NAME`) unless `session` is set in the opener config; if
    neither resolves, `open` errors rather than starting a detached session.

    Pane placement rides zellij's focus model instead of the ambiguous
    `--tab-id` flag: `new-tab` focuses the tab it creates, so subsequent
    `new-pane` calls land there. With `focus=False` (the default) the previously
    focused tab is restored after the panes are spawned, so the worktree boots in
    the background without yanking you out of your current tab.

    - **idempotent**: `open` matches an existing tab by name and selects it (when
      focusing) instead of creating a duplicate.
    - **destroy**: `close` finds the tab by name in the current session and closes
      it; it no-ops outside zellij, so `destroy` stays safe everywhere.
    """

    # The tab returns after opening and panes are first-class, so a background
    # init just rides along as one more pane running the command.
    hosts_background_init = True

    def open(
        self,
        root: Path,
        worktree_path: Path,
        name: str,
        config: OpenerConfig,
        init: str | None = None,
        surface_init: str | None = None,
    ) -> None:
        assert isinstance(config, ZellijOpenerConfig)
        if not zellij_installed():
            sys.exit("zellij is not installed — install it or pick another opener.")
        session = _resolve_session(config)

        if name in _query_tab_names(session):
            if config.focus:
                _go_to_tab_name(session, name)
            print(f"zellij tab for {name} already open.")
            return

        commands = build_commands(root, worktree_path, name, config, surface_init)
        # Each extra pane is (pane_options, command). The first surface becomes the
        # tab's initial command (via new-tab), so its pane_options don't apply; the
        # rest carry their verbatim `pane_options` (e.g. "-d horizontal"). A
        # background init rides as one more pane, named so it's clear what it runs.
        extra_panes: list[tuple[list[str], list[str]]] = [
            (shlex.split(s.pane_options), c) for s, c in zip(config.surfaces[1:], commands[1:], strict=True)
        ]
        if init is not None:
            extra_panes.append((["--name", "init"], shlex.split(init)))

        # Capture focus to restore only when staying put in the session we're in;
        # focusing elsewhere (or a different session) makes restoring meaningless.
        restore_to = None
        if not config.focus and session == os.environ.get("ZELLIJ_SESSION_NAME"):
            restore_to = _current_tab_id(session)

        _new_tab(session, name, worktree_path, commands[0])  # focuses the new tab
        for options, command in extra_panes:
            _new_pane(session, worktree_path, options, command)

        if restore_to is not None:
            _go_to_tab_id(session, restore_to)
        print(f"Opened zellij tab {name}.")

    def close(self, root: Path, worktree_path: Path, name: str) -> None:
        if not zellij_installed():
            return
        session = os.environ.get("ZELLIJ_SESSION_NAME")
        if session is None:
            return
        # Existence-gated so we never close the wrong (focused) tab: go-to-tab-name
        # only moves focus to a tab we've confirmed exists, then close-tab closes it.
        if name not in _query_tab_names(session):
            return
        _go_to_tab_name(session, name)
        _close_tab(session)
