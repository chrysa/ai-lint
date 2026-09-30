"""Machine-readable feedback contract for findings."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from ai_lint.finding import Finding

_WHY_MANUAL_FR = {
    "IMPORT_MISSING": "l'import cible un fichier absent ; le corriger ou le retirer est un choix",
    "SKILL_MISSING": "dossier de skill sans SKILL.md ; le completer ou le supprimer est un choix",
    "INSTR_LONG": "raccourcir un fichier d'instructions detruirait du contenu (a faire a la main / -i)",
    "SKILL_LONG": "raccourcir le corps du skill detruirait du contenu",
    "SKILL_NAME": "renommer le dossier change la commande /nom et l'historique git",
    "PERM_EXEC_RUNNER": "impossible de deviner les commandes internes autorisees a lister",
    "SKILL_BROAD_TOOLS": "restreindre les outils depend de ce que le skill fait vraiment",
    "PLUGIN_MANIFEST": "le nom du plugin est un identifiant reference ailleurs",
    "MISPLACED": "deplacer/supprimer le fichier est un choix",
    "ATTR_HOOK_CONFLICT": "un hook commit-msg existe deja ; le modifier est un choix",
    "ATTR_HISTORY": "reecrire l'historique publie est ta decision",
    "API_KEY_LEAK": "l'outil ne revoque ni ne supprime jamais une cle ; a revoquer a la main",
    "SETTINGS_UNKNOWN_KEY": "cle peut-etre plus recente que le schema ; supprimer serait risque",
    "TOKEN_AGENT_PACK": "regrouper des subagents en plugin se fait en revue (-i)",
    "SECRET_INLINE": "un secret en clair doit etre retire a la main (reference ${VAR}/vault)",
}
_WHY_MANUAL_EN = {
    "IMPORT_MISSING": "the import targets a missing file; fixing or removing it is a choice",
    "SKILL_MISSING": "skill directory without SKILL.md; completing or deleting it is a choice",
    "INSTR_LONG": "shortening an instruction file would destroy content (do it by hand / -i)",
    "SKILL_LONG": "shortening the skill body would destroy content",
    "SKILL_NAME": "renaming the folder changes the /name command and git history",
    "PERM_EXEC_RUNNER": "the exact inner commands to allow cannot be guessed",
    "SKILL_BROAD_TOOLS": "narrowing tools depends on what the skill actually does",
    "PLUGIN_MANIFEST": "the plugin name is an identifier referenced elsewhere",
    "MISPLACED": "moving/deleting the file is a choice",
    "ATTR_HOOK_CONFLICT": "a commit-msg hook already exists; changing it is a choice",
    "ATTR_HISTORY": "rewriting published history is your decision",
    "API_KEY_LEAK": "the tool never revokes or deletes a key; rotate it yourself",
    "SETTINGS_UNKNOWN_KEY": "the key may be newer than the schema; removing it would be risky",
    "TOKEN_AGENT_PACK": "grouping subagents into a plugin is done in review (-i)",
    "SECRET_INLINE": "an inline secret must be removed by hand (reference ${VAR}/vault)",
}

INTERACTIVE_FIX_CODES = {
    "DUP_EXACT",
    "DUP_NAME",
    "DUP_SIMILAR",
    "TOKEN_AGENT_PACK",
    "TOKEN_SKILL_DESC",
    "TOKEN_MODEL",
}


@dataclass(frozen=True)
class FeedbackRenderer:
    lang: str
    brief_table: Mapping[str, tuple[str, str, str]]
    hints: Mapping[str, tuple[str, str]]
    categories: Sequence[tuple[str, str]]

    def manual_reason(self, code: str) -> str:
        table = _WHY_MANUAL_EN if self.lang == "en" else _WHY_MANUAL_FR
        return table.get(code, "")

    def category(self, code: str) -> str:
        return next((category for prefix, category in self.categories if code.startswith(prefix)), "other")

    def fix_mode(self, finding: Finding) -> str:
        if finding.fixable:
            return "auto"
        if finding.code in INTERACTIVE_FIX_CODES or finding.code.startswith("DUP_"):
            return "interactive"
        return "manual"

    def finding_feedback(self, finding: Finding, status: str = "open") -> dict[str, Any]:
        data = asdict(finding)
        reason = self.manual_reason(finding.code)
        data.update(
            {
                "status": status,
                "category": self.category(finding.code),
                "fix_mode": self.fix_mode(finding),
                "evidence": {
                    "path": finding.path,
                    "message": finding.message,
                },
                "manual_reason": reason or None,
                "next_action": self.next_action(finding, status),
            }
        )
        return data

    def next_action(self, finding: Finding, status: str) -> str:
        action = self.action_for(finding.code)
        if status == "fixed":
            return "review the applied change" if self.lang == "en" else "relire le changement applique"
        if finding.fixable:
            prefix = "run with --fix to apply" if self.lang == "en" else "lancer avec --fix pour appliquer"
            return f"{prefix}: {action}" if action else prefix
        if self.fix_mode(finding) == "interactive":
            prefix = "run with -i to review interactively" if self.lang == "en" else "lancer avec -i pour arbitrer"
            return f"{prefix}: {action}" if action else prefix
        return (
            action
            or self.manual_reason(finding.code)
            or (
                "review this finding and update the relevant configuration"
                if self.lang == "en"
                else "examiner ce finding et ajuster la configuration concernee"
            )
        )

    def action_for(self, code: str) -> str:
        entry = self.brief_table.get(code)
        if entry:
            return entry[2]
        return self.hints[code][0] if code in self.hints else ""
