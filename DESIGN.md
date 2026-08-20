# Architecture

## Three orthogonal axes

A worktree session is described by three independent dimensions:

- **opener** (presentation / window management): `inplace` | `cmux` | `zellij` | `noop` | ...
- **isolation** backend: `raw` | `nono`
- **shell**: `claude` | `shell`

Plus optional lifecycle `hooks`: `init` (synchronous, pre-open, create only),
`surface_init` (inside every surface before its command, create and open), and
`background_init` (concurrent with the surfaces, create only). Surfaces can add
their own `init`, appended after `surface_init`.

Conceptually (not yet built):
- workspace type (worktree today; clone/cloud later)
- security profile (for nono or devcontainers)

The opener is the axis that decides *how* the worktree is surfaced; it
**composes with** the other two rather than replacing them (a cmux surface is
itself a `(shell, isolation_mode)` pair).

## Profile resolution

A **profile** is a named bundle of how-to-open-a-worktree settings: one opener
(discriminated on its `type` field) plus optional lifecycle `hooks`. The YAML
schema is in the README.

Resolution (`config.resolve_profile`), highest precedence last:

1. builtin `inplace` < `default_profile` < `--profile NAME` / `--opener NAME`
   (mutually exclusive; `--opener` uses that opener's defaults, no profile).
2. then fold `-o key=value` overrides (repeatable) onto the chosen opener and
   re-validate. `-o` reaches the opener's top-level scalar fields only (not
   nested `surfaces`); strings are coerced by pydantic (`"true"`→bool,
   `"claude"`→enum).

## Command contracts

Behavior that isn't visible in `--help`:

- **create** runs `hooks.init` synchronously before opening — surfaces (claude
  in particular) only start after it succeeds. `hooks.background_init` is for
  slow, non-blocking setup: it runs concurrently with the surfaces when the
  opener can host it (cmux/zellij give it its own surface/pane); others warn and
  run it synchronously after `init`. Both run with cwd = new worktree and
  `$ROOT_REPO` = origin repo.
- **surface init** (`hooks.surface_init` + the surface's own `init`) is baked
  into each surface's command: it runs in-process before the exec, inside the
  isolation sandbox, so its exports (direnv env, venv) land in the surface
  process itself. It runs on create *and* open. On failure the surface drops
  into `$SHELL` instead of running its command, keeping the error visible.
- **open** is the open half of create on an existing worktree; it never runs the
  create-only hooks, but surface init runs (it's part of the surface command).
  The cmux and zellij paths are idempotent — an existing workspace/tab is
  selected, not duplicated.
- **attach** is the dumb escape hatch: always inplace, single surface, current
  terminal, no profiles.
- **destroy** stops isolation sessions, then `close`s every opener, then removes
  the worktree and branch. It prompts only when something would be lost: a dirty
  tree, local-only commits on an unmerged branch, or an active Claude session.
- **gc** destroys (after one confirmation of the whole list) every worktree
  whose directory is gone or that is disposable by the same criteria. An active
  Claude session blocks collection — one that is running ("busy"/"working") or
  stopped mid-task waiting on the user ("waiting"/"blocked"); a session idling
  at rest doesn't — destroying under an idle session only orphans the process,
  the conversation survives via `claude --resume`.
- **ls**'s Sessions column reports isolation sessions and running Claude Code
  sessions (`claude agents --json`); cmux workspaces and zellij tabs aren't tracked.
