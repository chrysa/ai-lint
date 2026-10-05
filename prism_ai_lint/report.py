"""Report model and edit accumulator."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from prism_ai_lint.finding import Finding

DisabledCodesProvider = Callable[[], set[str]]
SeverityOverridesProvider = Callable[[], Mapping[str, str]]
LogFn = Callable[[int, str], None]
ReadTextFn = Callable[[Path], str | None]


def _empty_disabled_codes() -> set[str]:
    return set()


def _empty_severity_overrides() -> Mapping[str, str]:
    return {}


def _noop_log(level: int, message: str) -> None:
    return None


def _default_read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


_disabled_codes_provider: DisabledCodesProvider = _empty_disabled_codes
_severity_overrides_provider: SeverityOverridesProvider = _empty_severity_overrides
_log_fn: LogFn = _noop_log
_read_text_fn: ReadTextFn = _default_read_text


def configure_report_context(
    disabled_codes_provider: DisabledCodesProvider,
    severity_overrides_provider: SeverityOverridesProvider,
    log_fn: LogFn,
    read_text_fn: ReadTextFn,
) -> None:
    global _disabled_codes_provider, _severity_overrides_provider, _log_fn, _read_text_fn
    _disabled_codes_provider = disabled_codes_provider
    _severity_overrides_provider = severity_overrides_provider
    _log_fn = log_fn
    _read_text_fn = read_text_fn


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    edits: dict[Path, tuple[str, str]] = field(default_factory=dict)
    new_files: dict[Path, tuple[str, int]] = field(default_factory=dict)
    chmods: list[Path] = field(default_factory=list)
    moves: list[tuple[Path, Path]] = field(default_factory=list)
    seen: set = field(default_factory=set)
    budget: dict = field(default_factory=dict)
    stats: dict = field(default_factory=dict)
    agent_unknown: dict = field(default_factory=dict)
    proposals: list = field(default_factory=list)
    project_profiles: list = field(default_factory=list)
    desktop_compatibility: list = field(default_factory=list)

    def add(
        self,
        level: str,
        code: str,
        path: Path | str,
        msg: str,
        fixable: bool = False,
    ) -> None:
        if code in _disabled_codes_provider():
            return
        level = _severity_overrides_provider().get(code, level)
        self.findings.append(Finding(level, code, str(path), msg, fixable))
        _log_fn(3, f"finding {level}:{code} @ {path}")

    def count(self, level: str) -> int:
        return sum(1 for f in self.findings if f.level == level)

    def edit(self, path: Path, old: str, new: str) -> None:
        """Register a text change, chaining with an earlier change to the same file."""
        if path in self.new_files:
            self.new_files[path] = (new, self.new_files[path][1])
        elif path in self.edits:
            self.edits[path] = (self.edits[path][0], new)
        elif old != new:
            self.edits[path] = (old, new)

    def current(self, path: Path) -> str | None:
        if path in self.new_files:
            return self.new_files[path][0]
        if path in self.edits:
            return self.edits[path][1]
        return _read_text_fn(path)
