# wt

CLI for managing isolated git worktree sessions. Each new worktree can be launched with a preconfigured profile describing the desired terminal layout and isolation mode.

## Axes

- **opener** — how the worktree is surfaced: `inplace` (replace this terminal,
  the default), `cmux` (spawn a cmux workspace with multiple terminals),
  `zellij` (open a new tab with multiple panes in the current zellij session),
  or `noop` (create only, open nothing).
- **isolation** — `raw` (default) or `nono` ([nono](https://nono.sh/) sandbox;
  set `$WT_NONO_PROFILE` to the nono profile to sandbox with).
- **shell** — `claude` or a plain `shell`.

## Quick start

```bash
# Create a worktree and open it (default: inplace, plain shell)
wt create my-feature

# Create only the worktree, don't open it
wt create my-feature --opener noop

# Open with an ad-hoc opener (cmux: claude tab + shell tab)
wt create my-feature --opener cmux

# Open as a new tab in the current zellij session (claude pane + shell pane)
wt create my-feature --opener zellij

# Open with a custom profile (see Profiles below)
wt open my-feature --profile dev

# Attach in the current terminal (always inplace)
wt attach my-feature -s claude

# List worktrees (dirty state, local-only commits, PR status)
wt ls

# Add the live-sessions column (queries claude/nono; a bit slower)
wt ls --sessions

# Tear down. Asks for confirmation only if unmerged work would be lost.
wt destroy my-feature

# Tear down the worktree you're currently inside, no confirmation
wt self-destroy

# Destroy every worktree with nothing of value (one confirmation for the list)
wt gc
```

## Profiles

Profiles are opener configs in `~/.config/wt/config.yml`. `wt config list` shows
them; `wt config edit` opens the file in `$EDITOR`; `wt config set-default <name>`
picks the default. Override individual opener fields ad hoc with `-o key=value`,
e.g. `wt create foo -o focus=true`.

```yaml
version: 1.1
# Profile to use. If not set, the builtin fallback is a one-surface `inplace`.
default_profile: dev
profiles:
  dev:
    # Lifecycle hooks: shell snippets run at defined points of a session.
    # All run with cwd = the worktree and $ROOT_REPO = origin repo.
    hooks:
      # Runs synchronously at create time, before anything opens. Surfaces
      # (claude in particular) only start after it succeeds.
      init: |
        cp "$ROOT_REPO/.envrc" .envrc
        direnv allow
        uv sync
      # Runs inside every surface before its command starts — on create AND
      # every `wt open`. This is how per-worktree env (direnv, venv) gets into
      # the surface process itself. Runs once per surface: keep it fast. If it
      # fails, the surface drops into $SHELL so the error stays visible.
      surface_init: |
        eval "$(direnv export bash)"
      # Slow, non-blocking setup. Runs concurrently with the surfaces in its
      # own "init" surface/pane on openers that can host it (cmux, zellij);
      # others warn and run it synchronously after `init`.
      background_init: |
        pnpm install
    opener:
      type: cmux
      focus: true
      layout: tabs
      surfaces:
        - { shell: claude, mode: raw }
        # A surface can add its own init, appended after hooks.surface_init.
        - { shell: shell,  mode: raw, init: "echo welcome" }
```

Before config version 1.1 the hooks lived at the profile level as `init` plus a
bool `init_background`. Old configs still load — upgraded in memory, with a
warning — but update the file to the `hooks:` block.

The `zellij` opener instead adds a tab (named after the worktree) to a running
zellij session, with one pane per surface:

```yaml
profiles:
  dev:
    opener:
      type: zellij
      # Move focus to the new tab. Default false: it opens in the background and
      # focus stays on your current tab.
      focus: false
      # Target session. Defaults to the current $ZELLIJ_SESSION_NAME; set this to
      # open from a terminal that isn't itself inside zellij.
      session: null
      surfaces:
        # The first surface becomes the tab's initial command (its pane_options
        # are ignored). Later surfaces pass pane_options verbatim to
        # `zellij action new-pane` — e.g. "-d right" / "-d down" for the split
        # direction, or "-f" to float. See `zellij action new-pane --help`.
        - { shell: claude, mode: raw }
        - { shell: shell,  mode: raw, pane_options: "-d down" }
```

## How it works

Worktrees are created under `.worktrees/` in the repo root on a `wt/<name>`
branch, started from the trunk branch — `$WT_TRUNK_NAME`, default `main` —
which is also the merge target for the `ls`/`destroy`/`gc` status checks. See
`DESIGN.md` for the opener / isolation / shell architecture.

## Similar tools

Imbue's [mngr](https://github.com/imbue-ai/mngr) is very similar. Like `mngr`,
`wt` is sandbox-agnostic — current default isolation is `raw`, but it can change.

## Development

`wt` is developed in the Softmax monorepo and mirrored to
[Metta-AI/wt](https://github.com/Metta-AI/wt) with Copybara. Issues and pull
requests on the mirror are welcome — maintainers import accepted changes into
the monorepo. Every file in the mirror is overwritten on sync, so don't commit
to it directly.
