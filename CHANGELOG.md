# Changelog

All notable changes to `claude-lint`. Dates are ISO 8601.

## 2026.09.28-25

### Fixed
- Type-checking (mypy) now passes and runs in CI. Fixed the real defects it found:
  guarded every `split_rule(...)` result before indexing (an unparseable permission
  rule could have raised), made `hook_text` always a string, and renamed a shadowed
  loop variable. Remaining mypy noise (bare generics, unannotated defs, un-narrowable
  dict/JSON/regex values) is disabled by code; full strict typing is deferred.

## 2026.09.28-24

### Changed
- The implementation now lives in an importable module `claude_lint.py`; `claude-lint.py`
  is a thin CLI wrapper. This lets coverage and mypy see the real code (previously the
  hyphenated filename made it invisible to both). Behaviour and the `./claude-lint.py`
  invocation are unchanged.
- Added a mypy config (bug-catching subset; full strict deferred) and coverage config
  (`make typecheck`, `make cov`), plus a `claude_lint` shim removed in favour of the rename.

### Fixed
- `check_attribution` no longer risks a None membership test on an unreadable
  commit-msg hook (`hook_text` is always a string).
## 2026.09.28-23

### Changed
- Align with chrysa shared-standards code-style: ruff now selects N (naming) and the
  code is formatted to a 100-char line length (`ruff format`, enforced in `make lint`
  and CI). Renamed the `_L` i18n helper to `_loc`. The project format hook now formats
  the main file too. E501 is delegated to the formatter (it only nagged on
  unsplittable string literals). Dependencies live in `pyproject.toml`.

## 2026.09.28-22

### Added
- Editable YAML catalog. `--print-catalog` exports the reference sets (known
  settings keys, hook events, tools, skill/agent fields) and per-check metadata
  (severity, category, action, doc ref) as one YAML file; `--catalog FILE` overlays
  an edited copy to extend the reference data and override a check's severity
  (`error`/`warn`/`info`/`off`), `enabled` flag, or `→ fix` action — without
  touching the engine. Requires PyYAML (optional; degrades gracefully when absent).
- New settings keys recognised: disableWorkflows, ultracode, subagentPromptCacheTtl,
  strictKnownMarketplaces, blockedMarketplaces.

## 2026.09.28-20

### Fixed
- `ATTR_HOOK_CONFLICT` no longer fires on a commit-msg hook that actually strips
  attribution. Recognition is now by behaviour (the hook removes a Co-Authored-By /
  Generated-with trailer), not by the tool's name, so hooks installed under the
  former name are recognised — this had flooded the warning across every repo.

## 2026.09.28-19

### Added
- Progress bar on stderr during the repository scan, shown by default. It appears
  only on an interactive stderr at the default verbosity; `-v` (per-repo logs),
  `-q`, `--format json`, a pipe and CI stay silent, and it never touches stdout.

## 2026.09.28-18

### Added
- Every finding in `--details` now shows a `→ fix` / `→ solution` line proposing a
  concrete action, without needing `-v`. The action comes from the brief table for
  headline codes and the built-in hint for the long tail; a test asserts every
  emitted code resolves to an action.
- `SKILL_LONG` on a read-only (synced/symlinked) skill now says so, so it reads as
  fix-upstream rather than a repeatable local action.

## 2026.09.28-17

### Added
- The `--details` report quantifies token cost: each context-weighing finding is
  annotated with its estimated `~N tokens/session`, and the block ends with a
  **Potential savings** total (findings + restructurings).
- GitHub Actions CI (`.github/workflows/ci.yml`): ruff, pytest and the self-check,
  on Python 3.9 / 3.11 / 3.13, with a read-only `permissions` block.

### Changed
- Renamed the project and executable to `claude-lint` (`claude-lint.py`). The cache
  directory is now `~/.cache/claude-lint/`; `--restore` still reads the former
  `~/.cache/agent-config-lint/trash/` so pre-rename sessions stay restorable.
- The policy file is now `.claude-lint.toml` (example: `claude-lint.example.toml`);
  the former `.agent-lint.toml` is still accepted.

## 2026.09.27-16

### Fixed
- `SKILL_MISSING` no longer fires on a grouping directory that only holds nested
  skill subdirectories (e.g. `gitnexus/gitnexus-cli/`, `ui-styling/ui-styling/`).
  Such a folder is not itself a skill.
- `ATTR_TRACE` no longer flags a line that forbids attribution ("NEVER add a
  Co-Authored-By trailer", "strip the Generated-with line"). A negation near the
  pattern marks the line as documentation, not a trace, so anti-attribution
  guidance in commit instructions and plans is left alone.

## 2026.09.27-15

### Fixed
- `-i` no longer crashes with `PermissionError` on read-only skills. Skills reached
  through a symlink (a synced/managed store) or in a non-writable directory are
  detected up front: the shorten-description section skips them (with a one-line
  note) and the restructuring section no longer proposes a split/move that would
  fail. The description write is also wrapped so any residual write error is
  reported per item instead of aborting the whole review.
- `skill-family` restructuring no longer fails with "Destination path already
  exists" when a target directory is present; it falls back to a prefixed name.

### Changed
- Once "apply to all" (`A`) is chosen in the duplicates section, each remaining
  group is applied with a single receipt line instead of reprinting the full
  listing, so a scope with dozens of identical project-vs-user pairs stays readable.

## 2026.09.27-14

### Added
- Running with no arguments now prints the help instead of silently scanning the
  current directory. The help gained a `defaults:` block listing the effective
  defaults (scope, mode, report language, scaffolding, token budget, MCP cap, rtk),
  plus usage examples.
- Per-run log: each run appends one JSON line to
  `~/.cache/claude-lint/logs/<date>.log` (timestamp, version, arguments,
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
- The project format hook no longer reformats `claude-lint.py`; the single
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
