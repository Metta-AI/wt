from pathlib import Path
from unittest.mock import patch

import pytest
from softmaxwt.cli import app
from softmaxwt.config import (
    CmuxOpenerConfig,
    CmuxSurface,
    Config,
    ConfigError,
    InplaceOpenerConfig,
    OpenerConfig,
    Profile,
    ZellijOpenerConfig,
    config_path,
    resolve_profile,
)
from softmaxwt.isolation.common import IsolationMode
from softmaxwt.opener.common import OpenerName
from softmaxwt.shells import ShellType
from typer.testing import CliRunner

runner = CliRunner()


@pytest.fixture()
def config_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return tmp_path


def _write_profile(name: str, opener: OpenerConfig, default: bool = False) -> None:
    config = Config.load()
    config.profiles[name] = Profile(opener=opener)
    if default:
        config.default_profile = name
    config.save()


class TestResolveProfile:
    def test_builtin_is_inplace(self, config_home: Path):
        opener = resolve_profile().opener
        assert isinstance(opener, InplaceOpenerConfig)
        assert opener.shell == ShellType.shell
        assert opener.mode == IsolationMode.raw

    def test_opener_flag_uses_defaults(self, config_home: Path):
        opener = resolve_profile(opener=OpenerName.cmux).opener
        assert isinstance(opener, CmuxOpenerConfig)
        assert [s.shell for s in opener.surfaces] == [ShellType.claude, ShellType.shell]
        assert opener.focus is False

    def test_zellij_flag_uses_defaults(self, config_home: Path):
        opener = resolve_profile(opener=OpenerName.zellij).opener
        assert isinstance(opener, ZellijOpenerConfig)
        assert [s.shell for s in opener.surfaces] == [ShellType.claude, ShellType.shell]
        assert opener.focus is False

    def test_zellij_opt_sets_session(self, config_home: Path):
        opener = resolve_profile(opener=OpenerName.zellij, opts=["session=work"]).opener
        assert isinstance(opener, ZellijOpenerConfig)
        assert opener.session == "work"

    def test_profile_resolves(self, config_home: Path):
        _write_profile("dev", CmuxOpenerConfig(focus=True, surfaces=[CmuxSurface(shell=ShellType.claude)]))
        opener = resolve_profile(profile="dev").opener
        assert isinstance(opener, CmuxOpenerConfig)
        assert opener.focus is True

    def test_default_profile_used_when_unset(self, config_home: Path):
        _write_profile("dev", CmuxOpenerConfig(), default=True)
        assert isinstance(resolve_profile().opener, CmuxOpenerConfig)

    def test_opt_coerces_scalars(self, config_home: Path):
        opener = resolve_profile(opener=OpenerName.cmux, opts=["focus=true"]).opener
        assert isinstance(opener, CmuxOpenerConfig)
        assert opener.focus is True
        opener = resolve_profile(opener=OpenerName.inplace, opts=["shell=claude"]).opener
        assert isinstance(opener, InplaceOpenerConfig)
        assert opener.shell == ShellType.claude

    def test_opt_unknown_key_rejected(self, config_home: Path):
        # A typo in an explicit -o flag is a mistake, not forward-compat config:
        # it fails loudly, but with a clean ConfigError listing the valid fields.
        with pytest.raises(ConfigError, match="Valid fields for inplace"):
            resolve_profile(opener=OpenerName.inplace, opts=["bogus=1"])

    def test_opt_without_equals_rejected(self, config_home: Path):
        with pytest.raises(ValueError, match="key=value"):
            resolve_profile(opener=OpenerName.inplace, opts=["noequals"])

    def test_profile_and_opener_mutually_exclusive(self, config_home: Path):
        with pytest.raises(ValueError, match="not both"):
            resolve_profile(profile="x", opener=OpenerName.cmux)

    def test_unknown_profile_errors(self, config_home: Path):
        with pytest.raises(ValueError, match="Unknown profile"):
            resolve_profile(profile="nope")


class TestTolerantLoad:
    """A config written by a newer wt should still load on an older one: unknown
    fields warn-and-drop, but a genuinely broken config raises a clean error."""

    def _write_raw(self, text: str) -> None:
        path = config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def test_unknown_fields_dropped_with_warning(self, config_home: Path, capsys: pytest.CaptureFixture[str]):
        self._write_raw(
            "newish_top_key: 1\n"
            "profiles:\n"
            "  dev:\n"
            "    future_profile_key: x\n"
            "    opener:\n"
            "      type: cmux\n"
            "      focus: true\n"
            "      experimental: true\n"
        )
        config = Config.load()
        assert isinstance(config.profiles["dev"].opener, CmuxOpenerConfig)
        assert config.profiles["dev"].opener.focus is True
        warned = capsys.readouterr().err
        assert "newish_top_key" in warned
        assert "future_profile_key" in warned
        assert "experimental" in warned

    def test_unknown_opener_type_is_clean_error(self, config_home: Path):
        self._write_raw("profiles:\n  dev:\n    opener:\n      type: tmux\n")
        with pytest.raises(ConfigError) as exc:
            Config.load()
        # The known types are listed so the user can fix the typo.
        assert "unknown opener type 'tmux'" in str(exc.value)
        assert "cmux" in str(exc.value) and "zellij" in str(exc.value)

    def test_wrong_scalar_type_is_clean_error(self, config_home: Path):
        self._write_raw("version: not-a-number\n")
        with pytest.raises(ConfigError, match="valid number"):
            Config.load()


class TestConfigUpgrade:
    """Pre-1.1 configs load via an in-memory upgrade, with a stale-version warning."""

    def _write_raw(self, text: str) -> None:
        path = config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def test_v1_init_moves_to_hooks(self, config_home: Path, capsys: pytest.CaptureFixture[str]):
        self._write_raw("version: 1\nprofiles:\n  dev:\n    init: uv sync\n    opener:\n      type: noop\n")
        config = Config.load()
        assert config.profiles["dev"].hooks.init == "uv sync"
        assert config.profiles["dev"].hooks.background_init is None
        assert "upgraded in memory" in capsys.readouterr().err

    def test_v1_background_true_moves_init_to_background(self, config_home: Path):
        # v1 `init_background: true` meant "run init in the background" — the
        # script lands in hooks.background_init, preserving that behavior.
        self._write_raw(
            "version: 1\nprofiles:\n  dev:\n    init: uv sync\n    init_background: true\n"
            "    opener:\n      type: noop\n"
        )
        config = Config.load()
        assert config.profiles["dev"].hooks.init is None
        assert config.profiles["dev"].hooks.background_init == "uv sync"

    def test_v1_background_false_stays_sync(self, config_home: Path):
        self._write_raw(
            "version: 1\nprofiles:\n  dev:\n    init: uv sync\n    init_background: false\n"
            "    opener:\n      type: noop\n"
        )
        config = Config.load()
        assert config.profiles["dev"].hooks.init == "uv sync"
        assert config.profiles["dev"].hooks.background_init is None

    def test_missing_version_treated_as_v1(self, config_home: Path, capsys: pytest.CaptureFixture[str]):
        self._write_raw(
            "profiles:\n  dev:\n    init: uv sync\n    init_background: true\n    opener:\n      type: noop\n"
        )
        config = Config.load()
        assert config.profiles["dev"].hooks.background_init == "uv sync"
        assert "upgraded in memory" in capsys.readouterr().err

    def test_current_version_not_touched(self, config_home: Path, capsys: pytest.CaptureFixture[str]):
        self._write_raw(
            "version: 1.1\nprofiles:\n  dev:\n    hooks:\n      init: uv sync\n    opener:\n      type: noop\n"
        )
        config = Config.load()
        assert config.profiles["dev"].hooks.init == "uv sync"
        assert "upgraded" not in capsys.readouterr().err


class TestConfigCommand:
    def test_list_empty(self, config_home: Path):
        result = runner.invoke(app, ["config", "list"])
        assert result.exit_code == 0
        assert "builtin inplace" in result.output

    def test_list_shows_profiles(self, config_home: Path):
        _write_profile("dev", CmuxOpenerConfig(surfaces=[CmuxSurface(), CmuxSurface()]))
        result = runner.invoke(app, ["config", "list"])
        assert result.exit_code == 0
        assert "dev" in result.output
        assert "cmux" in result.output

    def test_set_default(self, config_home: Path):
        _write_profile("dev", CmuxOpenerConfig())
        result = runner.invoke(app, ["config", "set-default", "dev"])
        assert result.exit_code == 0
        assert config_path() == config_home / "wt" / "config.yml"
        assert Config.load().default_profile == "dev"

    def test_set_default_unknown_profile(self, config_home: Path):
        result = runner.invoke(app, ["config", "set-default", "nope"])
        assert result.exit_code == 1
        assert "Unknown profile" in result.output

    def test_edit_opens_editor(self, config_home: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("EDITOR", "myeditor --flag")
        with patch("softmaxwt.command.config.subprocess.run") as run:
            result = runner.invoke(app, ["config", "edit"])
        assert result.exit_code == 0
        # $EDITOR is split into argv (so "code -w" style commands work) and the
        # config path is appended; the file is seeded so the editor opens on it.
        run.assert_called_once_with(["myeditor", "--flag", str(config_path())], check=True)
        assert config_path().exists()

    def test_edit_visual_takes_precedence(self, config_home: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("EDITOR", "editor")
        monkeypatch.setenv("VISUAL", "visual")
        with patch("softmaxwt.command.config.subprocess.run") as run:
            runner.invoke(app, ["config", "edit"])
        assert run.call_args.args[0][0] == "visual"

    def test_edit_no_editor_set(self, config_home: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("EDITOR", raising=False)
        monkeypatch.delenv("VISUAL", raising=False)
        result = runner.invoke(app, ["config", "edit"])
        assert result.exit_code == 1
        assert "No editor set" in result.output
