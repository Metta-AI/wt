from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Literal, Optional, Union

import click
import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    ValidationInfo,
    model_validator,
)
from rich.console import Console

from softmaxwt.isolation.common import IsolationMode
from softmaxwt.opener.common import OpenerName
from softmaxwt.shells import ShellType

# Context key holding the mutable list a tolerant load passes into validation;
# the after-validator appends "ignored unknown field" notes to it. Absent on the
# strict path (`-o` overrides), where unknown fields must hard-fail instead.
_TOLERANT_SINK = "unknown_field_notes"

_KNOWN_OPENER_TYPES = ", ".join(sorted(o.value for o in OpenerName))


class ConfigError(click.ClickException, ValueError):
    """A user-facing config problem.

    `ClickException` so the CLI prints a clean one-liner instead of a pydantic
    traceback; `ValueError` so the callers (and tests) that already expect a
    `ValueError` from `resolve_profile` keep catching it.
    """


def config_path() -> Path:
    """Location of the wt config file."""
    base = os.environ.get("XDG_CONFIG_HOME")
    config_home = Path(base) if base else Path.home() / ".config"
    return config_home / "wt" / "config.yml"


class _ConfigModel(BaseModel):
    """Base for every wt config model.

    Tolerant of unknown fields *when a load explicitly opts in* (see
    `Config.load`): extras are collected, reported as a warning, and dropped so
    a config written by a newer wt still loads on an older one. Without that
    opt-in — direct construction and `-o` overrides — unknown fields hard-fail,
    so typos in explicit input don't pass silently.
    """

    model_config = ConfigDict(extra="allow")

    @model_validator(mode="after")
    def _handle_unknown_fields(self, info: ValidationInfo) -> _ConfigModel:
        extra = self.__pydantic_extra__
        if not extra:
            return self
        keys = ", ".join(sorted(extra))
        sink = info.context.get(_TOLERANT_SINK) if info.context else None
        if sink is None:
            raise ValueError(f"unknown field(s): {keys}")
        sink.append(f"ignoring unknown field(s) in {type(self).__name__}: {keys}")
        extra.clear()
        return self


class InplaceOpenerConfig(_ConfigModel):
    """Replace the current process with a single shell/agent in the worktree."""

    type: Literal[OpenerName.inplace] = OpenerName.inplace
    shell: ShellType = ShellType.shell
    mode: IsolationMode = IsolationMode.raw
    # Shell snippet run before the command starts, after the profile-wide
    # `hooks.surface_init` (inplace is a single surface). See `Hooks.surface_init`.
    init: Optional[str] = None


class CmuxSurface(_ConfigModel):
    """One terminal inside a cmux workspace."""

    shell: ShellType = ShellType.shell
    mode: IsolationMode = IsolationMode.raw
    # Shell snippet run inside this surface before its command starts, after the
    # profile-wide `hooks.surface_init`. See `Hooks.surface_init` for the contract.
    init: Optional[str] = None


class CmuxOpenerConfig(_ConfigModel):
    """Spawn a cmux workspace with one or more surfaces."""

    type: Literal[OpenerName.cmux] = OpenerName.cmux
    focus: bool = False
    # "tabs" stacks surfaces in one pane; "horizontal"/"vertical" split into panes.
    layout: Literal["tabs", "horizontal", "vertical"] = "tabs"
    surfaces: list[CmuxSurface] = Field(
        # The dream out of the box: a claude tab and a plain shell tab.
        default_factory=lambda: [CmuxSurface(shell=ShellType.claude), CmuxSurface(shell=ShellType.shell)]
    )


class ZellijSurface(_ConfigModel):
    """One pane inside the worktree's zellij tab."""

    shell: ShellType = ShellType.shell
    mode: IsolationMode = IsolationMode.raw
    # Shell snippet run inside this pane before its command starts, after the
    # profile-wide `hooks.surface_init`. See `Hooks.surface_init` for the contract.
    init: Optional[str] = None
    # Extra args passed verbatim to `zellij action new-pane` for this pane, e.g.
    # "-d right" / "-d down" to control the split, or "-f" to float. Ignored for
    # the first surface — it becomes the tab's initial command (via new-tab), not
    # a new-pane.
    pane_options: str = ""


class ZellijOpenerConfig(_ConfigModel):
    """Open a new tab (named after the worktree) with one pane per surface."""

    type: Literal[OpenerName.zellij] = OpenerName.zellij
    focus: bool = False
    # Target session; defaults to the current $ZELLIJ_SESSION_NAME. Set it to open
    # into a specific session from a terminal that isn't itself inside zellij.
    session: Optional[str] = None
    surfaces: list[ZellijSurface] = Field(
        # The dream out of the box: a claude pane and a plain shell pane.
        default_factory=lambda: [ZellijSurface(shell=ShellType.claude), ZellijSurface(shell=ShellType.shell)]
    )


class NoopOpenerConfig(_ConfigModel):
    """Create the worktree but open nothing."""

    type: Literal[OpenerName.noop] = OpenerName.noop


# Discriminated on `type`, so YAML profiles and `-o` overrides route to the right
# model. An unknown `type` is reported by `_format_validation_error`; unknown
# keys are tolerated only on a tolerant load (see `_ConfigModel`).
OpenerConfig = Annotated[
    Union[InplaceOpenerConfig, CmuxOpenerConfig, ZellijOpenerConfig, NoopOpenerConfig], Field(discriminator="type")
]
_OPENER_ADAPTER: TypeAdapter[OpenerConfig] = TypeAdapter(OpenerConfig)

_OPENER_DEFAULTS: dict[
    OpenerName, type[InplaceOpenerConfig] | type[CmuxOpenerConfig] | type[ZellijOpenerConfig] | type[NoopOpenerConfig]
] = {
    OpenerName.inplace: InplaceOpenerConfig,
    OpenerName.cmux: CmuxOpenerConfig,
    OpenerName.zellij: ZellijOpenerConfig,
    OpenerName.noop: NoopOpenerConfig,
}


class Hooks(_ConfigModel):
    """Shell snippets run at defined points of a worktree session's lifecycle.

    All hooks run with cwd = the worktree and $ROOT_REPO = the originating repo;
    the create-time hooks (`init`, `background_init`) also get $PARENT_BRANCH.
    May be multi-line.
    """

    # Run synchronously when the worktree is created, before it is opened —
    # surfaces (e.g. claude) only start once it has succeeded.
    init: Optional[str] = None

    # Run inside every surface, before its command starts — on `create` and every
    # `open`. This is the place to load per-worktree environment (direnv, venv)
    # into the surface process itself. Runs once per surface, so keep it fast;
    # slow setup belongs in `init` or `background_init`. On failure the surface
    # drops into $SHELL instead of running its command, so the error stays visible.
    surface_init: Optional[str] = None

    # Slow, non-blocking setup (pnpm install, cache warming, ...). Runs
    # concurrently with the surfaces, in its own pane/surface, on openers that can
    # host it (cmux, zellij); others warn and run it synchronously after `init`.
    background_init: Optional[str] = None


class Profile(_ConfigModel):
    """A named bundle of how-to-open-a-worktree settings. Holds one opener and
    optional lifecycle hooks."""

    opener: OpenerConfig = Field(default_factory=InplaceOpenerConfig)
    hooks: Hooks = Field(default_factory=Hooks)


def _format_validation_error(exc: ValidationError, path: Path) -> ConfigError:
    """Turn a pydantic `ValidationError` from loading the config into a clean,
    user-facing `ConfigError` — no traceback, with an actionable line per problem
    (an unknown opener `type` is the common one and gets the list of valid types)."""
    lines: list[str] = []
    for err in exc.errors():
        where = ".".join(str(p) for p in err["loc"]) or "(root)"
        if err["type"] in ("union_tag_invalid", "union_tag_not_found"):
            tag = err.get("ctx", {}).get("tag")
            named = f"unknown opener type {tag!r}" if tag else "missing opener type"
            lines.append(f"  {where}: {named}. Known types: {_KNOWN_OPENER_TYPES}")
        else:
            lines.append(f"  {where}: {err['msg']}")
    return ConfigError(f"Invalid wt config ({path}):\n" + "\n".join(lines))


# 1.1: profile-level `init` + bool `init_background` became the `hooks` block
# (init / surface_init / background_init scripts).
_LATEST_CONFIG_VERSION = 1.1


def _upgrade_config(data: dict, notes: list[str]) -> None:
    """Upgrade a pre-1.1 config dict in place, so old files keep loading.

    1 -> 1.1: a profile's `init` script moves to `hooks.init` — or to
    `hooks.background_init` when the old bool `init_background` flag was true
    ("run `init` in the background"), preserving v1 behavior.
    """
    version = data.get("version", 1)
    if not isinstance(version, (int, float)) or version >= _LATEST_CONFIG_VERSION:
        return
    for profile in (data.get("profiles") or {}).values():
        if not isinstance(profile, dict):
            continue
        init = profile.pop("init", None)
        background = profile.pop("init_background", False)
        if init is not None:
            profile["hooks"] = {"background_init" if background else "init": init}
    data["version"] = _LATEST_CONFIG_VERSION
    notes.append(
        f"version {version} config upgraded in memory to {_LATEST_CONFIG_VERSION} "
        "(init scripts live under `hooks:` now — see the README). "
        "Update the file to silence this warning."
    )


class Config(_ConfigModel):
    """The wt config file, persisted as YAML at config_path()."""

    version: float = _LATEST_CONFIG_VERSION
    default_profile: str | None = None
    profiles: dict[str, Profile] = {}

    @classmethod
    def load(cls) -> Config:
        path = config_path()
        if not path.exists():
            return cls()
        # Tolerant load: unknown fields are warned-about and dropped (sink below)
        # instead of failing the parse, so a config touched by a newer wt still
        # loads. A genuinely broken config (bad opener type, wrong scalar type)
        # still raises, but as a clean ConfigError rather than a raw traceback.
        notes: list[str] = []
        data = yaml.safe_load(path.read_text()) or {}
        if isinstance(data, dict):
            _upgrade_config(data, notes)
        try:
            config = cls.model_validate(
                data,
                context={_TOLERANT_SINK: notes},
            )
        except ValidationError as exc:
            raise _format_validation_error(exc, path) from exc
        if notes:
            warning = Console(stderr=True)
            for note in notes:
                warning.print(f"[yellow]⚠ wt config: {note}[/]")
        return config

    def save(self) -> None:
        path = config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(self.model_dump(mode="json", exclude_none=True), sort_keys=True))


def _apply_opts(opener: OpenerConfig, opts: list[str]) -> OpenerConfig:
    # Values stay as strings and lean on pydantic coercion ("true"->bool,
    # "claude"->ShellType). No tolerant context here, so an unknown key fails
    # loudly — a typo in an explicit `-o` flag is a mistake, not a forward-compat
    # config. Reaches the opener's top-level scalar fields only — not nested
    # `surfaces`.
    data = opener.model_dump(mode="json")
    for opt in opts:
        if "=" not in opt:
            raise ConfigError(f"Invalid override {opt!r}: expected key=value")
        key, value = opt.split("=", 1)
        data[key] = value
    try:
        return _OPENER_ADAPTER.validate_python(data)
    except ValidationError as exc:
        fields = ", ".join(sorted(f for f in opener.__class__.model_fields if f != "type"))
        # loc[0] is the discriminated-union tag (the opener type); the field, if
        # any, follows. Field-level errors get a "field: msg" prefix; model-level
        # ones (unknown key) carry the field in their message already.
        details = "; ".join(f"{e['loc'][1]}: {e['msg']}" if len(e["loc"]) > 1 else e["msg"] for e in exc.errors())
        raise ConfigError(f"Invalid -o override ({details}). Valid fields for {opener.type.value}: {fields}") from exc


def resolve_profile(
    profile: str | None = None,
    opener: OpenerName | None = None,
    opts: list[str] | None = None,
) -> Profile:
    """Pick the profile for a command, then apply `-o` overrides to its opener.

    Base precedence: explicit `--opener` (a profile with that opener's defaults)
    or `--profile` (from config) — mutually exclusive — else the configured
    `default_profile`, else a builtin one-surface `inplace`.
    """
    if profile is not None and opener is not None:
        raise ValueError("Pass either --profile or --opener, not both.")

    config = Config.load()
    if opener is not None:
        base = Profile(opener=_OPENER_DEFAULTS[opener]())
    else:
        name = profile if profile is not None else config.default_profile
        if name is None:
            base = Profile()
        elif name in config.profiles:
            base = config.profiles[name]
        else:
            known = ", ".join(sorted(config.profiles)) or "(none)"
            raise ValueError(f"Unknown profile {name!r}. Known profiles: {known}")

    return base.model_copy(update={"opener": _apply_opts(base.opener, opts or [])})
