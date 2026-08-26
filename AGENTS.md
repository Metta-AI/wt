# AGENTS.md — wt

CLI for isolated git worktree sessions (`wt` entry point). User docs in
`README.md`, architecture in `DESIGN.md`. Pure-Python package; minimal deps.

This directory is mirrored to the public
[Metta-AI/wt](https://github.com/Metta-AI/wt) repo; development happens in the
Softmax monorepo. Pull requests on the mirror are welcome; they are applied to
the monorepo and close once the change lands.

## Tests & lint

```bash
# From this directory.
uv run --extra test pytest tests -v
```


Tests run the real `wt` CLI as a subprocess against a throwaway git repo (see
`tests/conftest.py`); `XDG_CONFIG_HOME` is pointed at the test dir so your real
`~/.config/wt` is never read, and `SHELL=/usr/bin/true` makes inplace execs
return harmlessly.

## Source layout

- `command/` — one module per CLI command, self-registering on import (wired in
  `cli.py`).
- `opener/` — how a worktree is surfaced (inplace/cmux/zellij/noop...); registry +
  `Opener` ABC in `common.py`.
- `isolation/` — sandbox backends (raw/nono); same registry shape as opener.
- `config.py` — profiles, YAML config, `resolve_profile` precedence.
- `graphite.py` — reads graphite's data.
- `worktree.py` — `git` subprocess wrappers and parsing.

## Gotchas

- **Never run mutating cmux commands during development** without the user's
  explicit go-ahead — you can hang or crash their running terminal. In
  particular do not reintroduce `cmux --layout`; see `LESSONS.md`.
- The cmux opener only scrapes state from `--json` commands; mutating commands'
  stdout is not a stable interface.
- `wt destroy` must survive root-owned/read-only files left by bazel builds
  (`_force_remove_dir`); there's a regression test for it.

## Debugging nono sandbox denials

When a command fails inside the `nono` isolation mode: `nono why --path <p> --op
read|write` (or `--host`/`--port`) explains a denial; `nono learn -- <cmd>`
traces what a command actually accesses (needs `sudo` on macOS); `nono audit
list --recent 5` reviews past sessions; `--dry-run` previews grants; `-v/-vv`
for detail. Sensitive paths (`~/.ssh`, `~/.aws`, shell dotfiles, …) are always
blocked regardless of flags. For profile authoring, run `nono profile guide`.
The sandbox profile name comes from `$WT_NONO_PROFILE` (`isolation/nono.py`);
nono mode refuses to run without it.

