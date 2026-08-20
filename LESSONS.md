# Lessons — wt

## `cmux --layout` with multiple surfaces per pane hangs the app

`cmux new-workspace --layout '{"pane":{"surfaces":[{...},{...}]}}'` (multiple
terminal surfaces stacked in one pane) **pins cmux at 100% CPU and requires a
force-restart.** Reproduced twice. The `--layout` JSON field is undocumented and
unvalidated in `cmux.schema.json` (`additionalProperties: true`; the keys
`children`/`direction`/`split` appear nowhere) — cmux returns `OK workspace:N`
then spins rendering a shape it can't handle.

The cmux opener therefore avoids `--layout` entirely and composes documented
primitives instead (`new-workspace --command`, `new-surface`, `new-split`,
`send`/`send-key`). **Do not reintroduce `--layout`.** Never run mutating cmux
commands during development without the user's explicit go-ahead — crashing their
running app is disruptive.
