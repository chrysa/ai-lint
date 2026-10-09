"""Typed domain operations supplied to the terminal review controller."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from prism_ai_lint.report import Report


@dataclass(frozen=True)
class TuiServices:
    """Keep domain operations explicit while the engine is extracted incrementally."""

    home_path: Callable
    config_dir: Callable
    session_duplicates: Callable
    is_generated_family: Callable
    compute_proposals: Callable
    frontmatter_of: Callable
    _writable: Callable
    load_json_file: Callable
    _ask: Callable
    advice: Callable
    _fr_plural: Callable
    _trash: Callable
    _affixes: Callable
    _scope_of: Callable
    _show_file: Callable
    _family_to_plugin: Callable
    proposal_fr: Callable
    apply_proposal: Callable
    read_text: Callable
    split_frontmatter: Callable
    set_frontmatter: Callable
    move_to_metadata: Callable
    backup: Callable
    dump_json: Callable
    feedback_rows: Callable[[Report], list[dict]]
    proposal_edits: Callable[[dict, dict], dict[Path, tuple[str, str]]]
    redact: Callable[[str], str]
    readonly_mechanical_agents: Callable[[list[Path]], list[Path]]
