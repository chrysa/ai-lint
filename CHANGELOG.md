# Changelog

All notable changes to `agent-config-lint`. Dates are ISO 8601.

## 2026.09.27-14

### Added
- Running with no arguments now prints the help instead of silently scanning the
  current directory. The help gained a `defaults:` block listing the effective
  defaults (scope, mode, report language, scaffolding, token budget, MCP cap, rtk),
  plus usage examples.
- Per-run log: each run appends one JSON line to
  `~/.cache/agent-config-lint/logs/<date>.log` (timestamp, version, arguments,
  repository count, elapsed time, finding counts by level and code, fixed/applied
  counts, exit code). Counts and codes only — never file contents or secrets.
  Best-effort: a logging failure never changes the run's result.
- `llmtrim` companion CLI check: when subagents carry the llmtrim route marker but
  the `llmtrim` binary is not on `PATH`, the tool reports it (`LLMTRIM_MISSING`) so
  you can install llmtrim or remove the dead route agents. Skipped under `--no-cli`.
- `make help` and `make selfcheck` targets.

### Changed
- `RTK_MISSING` now spells out both ways forward: install rtk, or set
  `permissions.require_rtk = false` to skip rtk routing. `RTK_MISSING` and
  `LLMTRIM_MISSING` appear in the brief report's "broken" section.
- The project format hook no longer reformats `agent-config-lint.py`; the single
  distribution file keeps its dense hand-authored layout (it is still linted).

## 2026.09.27-13

### Added
- `--lang en|fr` selects the language of the brief report. Defaults to French
  when `$LANG` starts with `fr`, English otherwise. The interactive review
  stays French.
- Test suite (`tests/`, pytest) reproducing a miniature user + project
  environment in temporary directories, with `make test` and `make lint`
  runnable without installing anything globally. The interactive review is
  fuzzed across every answer combination and must never raise.

### Fixed
- Removed the dead, shadowed English `interactive()` implementation. Only the
  French one ever ran; the copy was unreachable.
- Interactive keys `s`/`S` and `a`/`A` no longer collapse together. `_ask` keeps
  the answer's case, so "skip one" (`s`) and "skip all of this kind" (`S`) are
  distinct in the restructuring and duplicate sections.
- French count phrases agree in number (`1 groupe`, not `1 groupes`) via a
  `_fr_plural` helper.
- `find_duplicates` labels each group from its source (identical body vs same
  name) instead of the fragile `group in by_hash.values()` value scan, which
  could mislabel a name group as an exact duplicate.
- `rtk rewrite` support is detected from its stdout, not its exit code. rtk
  0.42.1 exits 3 on a successful rewrite, which previously disabled all rtk
  routing.
- `restore_trash` validates its target, reports an empty session instead of a
  misleading "0 files", restores each file inside `try/except` so one failure
  no longer aborts the rest, and exits non-zero when nothing could be restored.

### Performance
- `find_duplicates` buckets its similarity pass by kind and prunes pairs whose
  set sizes cannot reach the Jaccard threshold.
- The attribution scan runs a single whole-file regex before any per-line work
  and no longer calls `Path.resolve()` on every file (only on a file whose name
  matches the script). A 6000-file tree drops from ~22s to ~4s; a read-only
  `--user` run over a large real user scope finishes in a couple of seconds.
- More generated directories are skipped during the attribution scan
  (`.next`, `target`, `vendor`, `coverage`, `.terraform`, ...).
