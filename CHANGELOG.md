# Changelog

All notable changes to `agent-config-lint`. Dates are ISO 8601.

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
