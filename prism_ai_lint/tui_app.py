"""Structured terminal review with explicit actions and human validation."""

from __future__ import annotations

import datetime as dt
import difflib
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from prism_ai_lint._markup import shorten_description
from prism_ai_lint.content_validation import CriticalContentValidator
from prism_ai_lint.report import Report
from prism_ai_lint.restore_log import RestoreLog
from prism_ai_lint.terminal_view import Tty
from prism_ai_lint.tui_services import TuiServices

NOT_DETECTED = "not detected"
SKIPPED_ACTIONS = "skipped actions"
SKIPPED_PROPOSALS = "skipped proposals"


class TuiApp:
    """Drive terminal review using the engine's existing domain operations."""

    def __init__(self, services: TuiServices, full_yes: bool = False) -> None:
        self.services = services
        self.full_yes = full_yes
        self.debug_log = None
        self.t = Tty(services.home_path)
        self.position: int = 0
        self.chosen: list[str] = []
        self._reviews = {
            "dups": self._review_duplicates,
            "families": self._review_families,
            "restructure": self._review_proposals,
            "descriptions": self._review_descriptions,
            "misc": self._review_misc,
        }

    def preview_conversion(self, plans: list[dict], render) -> None:
        """Expose conversion plans without starting a writable review session."""
        self.t.rule("AGENT CONVERSION")
        print(render(plans))

    def apply_conversion_interactive(self, plan: dict, converter) -> bool:
        """Guide user through conversion approval and application."""
        self.t.rule("APPLY AGENT CONVERSION")
        print(f"Target: {plan['target']}")
        print(f"From: {plan['source']} → To: {plan['target_tool']}")
        if plan.get("diagnostics"):
            print("\nWarnings:")
            for diag in plan["diagnostics"]:
                print(f"  · {diag}")
        print("\nReview the conversion plan above before proceeding.")
        while True:
            response = input("Apply this conversion? [y/n/details]: ").strip().lower()
            if response == "y":
                return True
            elif response == "n":
                return False
            elif response == "details":
                print("\nFull plan:")
                print(converter.render_text([plan]))
            else:
                print("Enter 'y', 'n', or 'details'.")

    def setup_flow(self, report: Report, scaffold_mode: bool) -> None:
        """Guide user through setup generation (--generate flow)."""
        self.t.rule("SETUP GENERATION")
        if not scaffold_mode:
            print("  Run with --generate to preview setup, or --generate --fix to apply.")
            return
        print("  The following configuration will be generated:")
        print(f"    · Instructions: {sum(1 for f in report.new_files if f.suffix == '.md')}")
        print(f"    · Settings: {sum(1 for f in report.new_files if 'settings' in f.name)}")
        print(f"    · Hooks: {sum(1 for f in report.new_files if 'hooks' in f.parts)}")
        print("  Review --diff to inspect each file before applying.")

    def _count(self, action: str) -> None:
        self.done[action] = self.done.get(action, 0) + 1

    def _section_rule(self, title: str) -> None:
        self.t.rule(f"[{self.position}/{len(self.chosen)}] {title}")

    def _overview(self, report: Report) -> None:
        self.t.rule("PROJECT OVERVIEW")
        for profile in report.project_profiles:
            print(
                f"  {self.services.home_path(profile['path'])}: {profile['kind']} ({profile['confidence']} confidence)"
            )
            print("    Evidence: " + ", ".join(profile.get("signals") or ["no detected signals"]))
        if not report.project_profiles:
            print("  No project profiles available in this scan.")
        print("  Review applies only to the scanned roots; omitted projects were not inspected.")
        print("  Critical content requires an explicit diff approval.")
        self.t.rule("AUTONOMY READINESS")
        for repo in self.repos:
            tests = "detected" if (repo / "tests").is_dir() else NOT_DETECTED
            ci = "detected" if (repo / ".github" / "workflows").is_dir() else NOT_DETECTED
            docs = "detected" if (repo / "README.md").is_file() else NOT_DETECTED
            print(f"  {self.services.home_path(str(repo))}: tests {tests}; CI {ci}; README {docs}")
        print("  These are filesystem signals, not a verification that tests or CI pass.")

        # Expanded readiness checks
        for repo in self.repos:
            has_precommit = (repo / ".pre-commit-config.yaml").is_file()
            has_makefile = (repo / "Makefile").is_file()
            has_pyproject = (repo / "pyproject.toml").is_file()
            has_claude = (repo / "CLAUDE.md").is_file()
            signals = []
            if has_precommit:
                signals.append("pre-commit hooks")
            if has_makefile:
                signals.append("Makefile")
            if has_pyproject:
                signals.append("pyproject.toml")
            if has_claude:
                signals.append("CLAUDE.md")
            if signals:
                print(f"    Tooling: {', '.join(signals)}")

        for desktop in report.desktop_compatibility:
            if not desktop["detected"]:
                continue
            print(f"  Desktop: {self.services.home_path(desktop['path'])}; " + ", ".join(desktop["frameworks"]))
            for os_name, state in desktop["os"].items():
                observed = "observed" if state["ci_runner_observed"] else "not observed"
                print(f"    {os_name}: CI runner {observed}; runtime compatibility unverified")

    def _findings_board(self) -> None:
        self.t.rule("FINDINGS")
        if not self.rows:
            print("  No findings in this scan.")
            return
        grouped: dict[tuple[str, str, str], list[dict]] = {}
        for row in self.rows:
            key = (row["level"], row["category"], row["fix_mode"])
            grouped.setdefault(key, []).append(row)
        for (severity, category, mode), rows in grouped.items():
            print(f"  {severity.upper()} / {category} / {mode}: {len(rows)}")
            for row in rows[:5]:
                print(f"    {row['code']} · {self.services.home_path(row['path'])}: {row['next_action']}")
            if len(rows) > 5:
                print(f"    +{len(rows) - 5} more; use --details or --format json for the complete report")

    def _pick_sections(self) -> list[str]:
        if self.full_yes:
            return [section[0] for section in self.sections]
        while True:
            pick = self.services._ask("\nSections (1,3; Enter = all; f = findings; ? = help; q = quit): ", "")
            if pick.lower() == "q":
                return []
            if pick == "":
                return [section[0] for section in self.sections]
            if pick.lower() == "f":
                self._findings_board()
                continue
            if pick == "?":
                print("  Choose section numbers separated by commas. Enter reviews every section.")
                print("  Each action can be kept or skipped; critical diffs require typing approve.")
                continue
            selected = self._parse_selection(pick)
            if selected is not None:
                return selected

    def _parse_selection(self, pick: str) -> list[str] | None:
        if not re.fullmatch(r"\d+(?:\s*,\s*\d+)*", pick):
            print("  Invalid selection; enter section numbers, f, ?, or q.")
            return None
        numbers = [int(number) for number in pick.split(",")]
        if not all(1 <= number <= len(self.sections) for number in numbers):
            print("  Section number out of range; choose from the list above.")
            return None
        selected = {self.sections[number - 1][0] for number in numbers}
        return [section[0] for section in self.sections if section[0] in selected]

    def run(self, rep: Report, repos: list[Path], policy: dict, user_scope: bool) -> int:
        self.policy = policy
        self.repos = repos
        self.rows = self.services.feedback_rows(rep)
        self.manual_count = sum(row["fix_mode"] == "manual" for row in self.rows)
        if not self.full_yes and not sys.stdin.isatty():
            print("\n-i a besoin d'un vrai terminal (pas d'un pipe) : relance-le directement dans ton shell.")
            return 0
        self._start_session(user_scope)
        self._inventory(rep, user_scope)
        self._build_sections()
        self._overview(rep)
        self._findings_board()
        if not self.sections:
            print(f"\n{self.t.grn}Rien à revoir.{self.t.r}")
            return 0
        self.t.rule("REVUE INTERACTIVE")
        print(
            f"Rien n'est supprimé : ce que tu retires part dans {self.t.cyan}{self.services.home_path(str(self.trash_root))}{self.t.r},"
        )
        print("et un script restore.sh annule toute la session. À chaque question : ? pour l'aide.\n")
        for i, (_, label, _) in enumerate(self.sections, 1):
            print(f"  {self.t.b}{i}{self.t.r}. {label}")
        self.chosen = []
        self.reviewed = []
        try:
            self.chosen = self._pick_sections()
            if not self.chosen:
                return 0
            for position, code in enumerate(self.chosen, 1):
                self.position = position
                self.reviewed.append(code)
                self._run_section(code)
        except KeyboardInterrupt:
            print("\nReview interrupted; completed actions are listed below.")
        return self._summary()

    def _start_session(self, user_scope: bool) -> None:
        self.cfg = self.services.config_dir()
        self.roots = ([self.cfg] if user_scope else []) + [r / ".claude" for r in self.repos]
        stamp = dt.datetime.now().strftime("%Y%m%dT%H%M%S%f")
        self.trash_root = Path(os.path.expanduser(f"~/.cache/prism-ai-lint/trash/{stamp}"))
        self.restore = RestoreLog(self.trash_root / "restore.sh")
        self.done: dict[str, int] = {}

    def _inventory(self, rep: Report, user_scope: bool) -> None:
        # ---- inventory
        groups = self.services.session_duplicates([self.cfg] if user_scope else [], [r / ".claude" for r in self.repos])
        self.families = [(w, m) for w, m in groups if w == "DUP_SIMILAR" and self.services.is_generated_family(m)]
        self.dups = [(w, m) for w, m in groups if (w, m) not in self.families]
        order = {"DUP_EXACT": 0, "DUP_NAME": 1, "DUP_SIMILAR": 2}
        self.dups.sort(key=lambda g: (order[g[0]], -len(g[1])))
        self.props = self.services.compute_proposals(self.roots, self.repos, self.policy)
        self.limit = self.policy["tokens"]["skill_description_chars"]
        self._description_inventory()
        self.udata = self.services.load_json_file(self.cfg / "settings.json")
        self.misc = []
        if "opus" in str(self.udata.get("model", "")).lower():
            self.misc.append("model")
        self.misc += [f for f in rep.findings if f.code == "GENERATE_USER_MCP"]

    def _description_inventory(self) -> None:
        self.long_desc = []
        self.long_desc_ro = 0  # read-only skills skipped (symlinked / synced stores)
        for r in self.roots:
            for sk in sorted(r.glob("skills/*/SKILL.md")):
                meta = self.services.frontmatter_of(sk)
                if len((meta or {}).get("description", "")) > self.limit and (meta or {}).get(
                    "disable-model-invocation", ""
                ).lower() not in ("true", "yes", "on", "1"):
                    if self.services._writable(sk):
                        self.long_desc.append(sk)
                    else:
                        self.long_desc_ro += 1

    def _build_sections(self) -> None:
        self.sections = [
            (
                "dups",
                f"Doublons chargés ensemble ({sum(1 for g in self.dups if g[0] != 'DUP_SIMILAR')} "
                f"sûrs, {sum(1 for g in self.dups if g[0] == 'DUP_SIMILAR')} à juger)",
                len(self.dups),
            ),
            (
                "families",
                f"Familles générées ({len(self.families)}) : même modèle, noms différents",
                len(self.families),
            ),
            (
                "restructure",
                f"Restructurations ({len(self.props)}), ~{sum(p['gain'] for p in self.props)} tokens/session en jeu",
                len(self.props),
            ),
            ("descriptions", f"Descriptions de skills trop longues ({len(self.long_desc)})", len(self.long_desc)),
            ("misc", f"Modèle par défaut et serveurs MCP ({len(self.misc)})", len(self.misc)),
        ]
        self.sections = [s for s in self.sections if s[2]]

    def _run_section(self, code: str) -> None:
        try:
            self._reviews[code]()
        except (OSError, StopIteration) as error:
            self._failure(error)

    def _failure(self, error: Exception) -> None:
        if self.debug_log:
            self.debug_log(repr(error))
        print(f"  {self.t.red}Action failed: {error}{self.t.r}")
        self._count("failed actions")

    def _review_duplicates(self) -> None:
        self._section_rule(f"DOUBLONS ({self.services._fr_plural(len(self.dups), 'groupe')})")
        print("  Inspect each group before removing copies. Removed files are kept in the session trash.")
        auto_all = self.full_yes
        for number, (why, group) in enumerate(self.dups, 1):
            members = [member for member in group if Path(member["path"]).exists()]
            if len(members) < 2:
                continue
            try:
                answer = self._duplicate_group(number, why, members, auto_all)
            except OSError as error:
                self._failure(error)
                continue
            if answer == "q":
                break
            if answer == "A":
                auto_all = True

    def _duplicate_group(self, n: int, why: str, members: list[dict], auto_all: bool) -> str:
        remove, reason = self.services.advice(why, members)
        label = {"DUP_EXACT": "copies identiques", "DUP_NAME": "même nom", "DUP_SIMILAR": "quasi-doublons"}[why]
        if auto_all and remove:
            self._remove_duplicates(members, remove)
            return ""
        self._render_duplicates(n, label, members, remove, reason)
        answer = self._duplicate_answer(members, remove)
        if answer.lower() == "q":
            return "q"
        if answer.lower() in ("s", "g"):
            self._count("groupes gardés tels quels")
            return answer
        targets = (
            remove
            if answer in ("", "A")
            else [int(number) - 1 for number in re.findall(r"\d+", answer) if 0 < int(number) <= len(members)]
        )
        self._remove_duplicates(members, targets)
        return answer

    def _remove_duplicates(self, members: list[dict], targets: list[int]) -> None:
        if not targets:
            self._count("groupes gardés tels quels")
        for index in dict.fromkeys(targets):
            path = Path(members[index]["path"])
            if not path.exists():
                continue
            self.services._trash(path, self.trash_root, self.restore)
            self._count("doublons retirés")
            print(f"  {self.t.grn}Removed{self.t.r} {self.t.short(str(path), self.t.width - 12)}")

    def _duplicate_answer(self, members: list[dict], remove: list[int]) -> str:
        if self.full_yes:
            # Apply only a non-empty safe recommendation; otherwise keep the group.
            return "" if remove else "g"
        default = "appliquer le conseil" if remove else "tout garder"
        while True:
            answer = self.services._ask(
                f"  Entrée = {default} · g = tout garder · 2,3 = retirer · v2 = voir "
                "· A = conseil pour tous les groupes sûrs · s = passer · q = fin des doublons : ",
                "",
            )
            low = answer.lower()
            if low.startswith("v") and low[1:].isdigit() and 0 < int(low[1:]) <= len(members):
                self.services._show_file(Path(members[int(low[1:]) - 1]["path"]), self.t)
            elif answer == "?":
                print("  Retirer = déplacer dans la corbeille de la session (restore.sh pour annuler).")
            else:
                return answer

    def _render_duplicates(self, n: int, label: str, members: list[dict], remove: list[int], reason: str) -> None:
        print(
            f"\n{self.t.b}[{n}/{len(self.dups)}] {label}{self.t.r} · {self.services._fr_plural(len(members), members[0]['kind'])}"
        )
        descs = [m["desc"] for m in members]
        pre, suf = self.services._affixes(descs)
        if len(pre) + len(suf) > 30:
            print(f"  {self.t.dim}description commune : « {pre}…{suf} »{self.t.r}")
        wname = max(len(m["name"]) for m in members)
        for i, m in enumerate(members):
            mark = f"{self.t.red}✗{self.t.r}" if i in remove else f"{self.t.grn}✓{self.t.r}"
            mtime = dt.datetime.fromtimestamp(m["file"].stat().st_mtime).strftime("%d/%m/%y")
            end = len(m["desc"]) - len(suf) if suf else None
            var = m["desc"][len(pre) : end] if len(pre) + len(suf) > 30 else m["desc"]
            print(
                f"  {mark} {self.t.b}{i + 1:>2}{self.t.r} {m['name']:<{wname}}  {self.services._scope_of(m):<11} "
                f"{m['lines']:>4} l.  {mtime}  "
                f"{self.t.dim}{self.t.short(str(m['path']), self.t.width - wname - 40)}{self.t.r}"
            )
            if var.strip():
                print(f"       {self.t.dim}{var.strip()[: self.t.width - 8]}{self.t.r}")
        print(
            f"  {self.t.yel}Conseil :{self.t.r} {reason}"
            + (f" → retirer {', '.join(str(i + 1) for i in remove)}" if remove else "")
        )

    def _review_families(self) -> None:
        self._section_rule(f"FAMILLES GÉNÉRÉES ({len(self.families)})")
        print(
            f"{self.t.dim}Ces éléments suivent le même modèle (seuls le nom ou le modèle d'IA "
            f"changent) : ce ne sont pas des\n"
            f"doublons. Ils coûtent des tokens à chaque requête ; si tu ne t'en sers que "
            f"dans certains projets, un\n"
            f"plugin à activer là-bas est plus léger.{self.t.r}"
        )
        for n, (_, members) in enumerate(self.families, 1):
            members = [m for m in members if Path(m["path"]).exists()]
            if len(members) < 2:
                continue
            names = [m["name"] for m in members]
            stem = os.path.commonprefix(names).rstrip("-_") or names[0]
            toks = sum((len(m["desc"]) + 40) // 4 for m in members)
            print(
                f"\n{self.t.b}[{n}/{len(self.families)}] {stem}-*{self.t.r} · "
                f"{self.services._fr_plural(len(members), members[0]['kind'])} · ~{toks} tokens/session"
            )
            print("  " + ", ".join(nm[len(stem) :].lstrip("-_") or nm for nm in names))
            ans = (
                "p"
                if self.full_yes
                else self.services._ask(
                    "  Entrée = garder · p = en faire un plugin · k = mettre de côté (parked/) · q = fin : ",
                    "",
                ).lower()
            )
            if ans == "q":
                break
            if ans == "p":
                print("     " + self.services._family_to_plugin(members, stem, self.policy, self.restore))
                self._count("familles transformées en plugin")
            elif ans == "k":
                for member in members:
                    self._park_member(member)
                self._count("familles mises de côté")
            else:
                self._count(SKIPPED_ACTIONS)

    def _park_member(self, member: dict) -> None:
        source = Path(member["path"])
        root = next(root for root in self.roots if source.is_relative_to(root))
        destination = root / "parked" / source.relative_to(root)
        if destination.exists():
            raise FileExistsError(f"{destination} already exists")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
        self.restore.append(f"mv {shlex.quote(str(destination))} {shlex.quote(str(source))}")

    def _review_proposals(self) -> None:
        self._section_rule(f"RESTRUCTURATIONS ({len(self.props)})")
        explain = {
            "agent-pack": "Les agents d'un pack sont listés à chaque requête. En plugin, ils ne se chargent que dans les projets où tu l'installes.",
            "skill-family": "Des skills d'un même domaine, regroupés en plugin : chargés seulement là où ils servent.",
            "split-skill": "Un SKILL.md trop long est lu en entier à chaque usage ; les sections de référence iront dans references/, lues au besoin.",
            "command-to-skill": "Les commandes sont l'ancien format ; un skill garde le même /nom et gagne les options des skills.",
            "rule-paths": "Une règle sans 'paths:' se charge partout ; avec, seulement quand Claude touche ces fichiers.",
            "procedure-to-skill": "Une procédure dans CLAUDE.md est relue à chaque session ; en skill, seulement quand elle sert.",
        }
        accept_kind: set[str] = set()
        skip_kind: set[str] = set()
        last_kind = None
        for number, proposal in enumerate(self.props, 1):
            kind = proposal["kind"]
            if kind in skip_kind:
                self._count(SKIPPED_PROPOSALS)
                continue
            if kind != last_kind:
                print(f"\n{self.t.dim}{explain[kind]}{self.t.r}")
                last_kind = kind
            gain = f"~{proposal['gain']} tokens/session" if proposal["gain"] else "per-use"
            print(f"[{number}/{len(self.props)}] {self.services.proposal_fr(proposal)} ({gain})")
            answer = self._proposal_answer(kind, accept_kind, skip_kind)
            if answer.lower() == "q":
                break
            self._proposal_action(proposal, answer)

    def _proposal_answer(self, kind: str, accept: set[str], skip: set[str]) -> str:
        if self.full_yes:
            return "o"
        if kind in accept:
            return "o"
        extra = " · k = mettre de côté" if kind == "agent-pack" else ""
        answer = self.services._ask(
            f"  o = appliquer{extra} · Entrée = passer · A = appliquer tous les '{kind}' "
            f"· S = passer tous les '{kind}' · q = fin : ",
            "",
        )
        if answer == "A":
            accept.add(kind)
            return "o"
        if answer == "S":
            skip.add(kind)
        return answer

    def _proposal_action(self, proposal: dict, answer: str) -> None:
        try:
            if proposal["kind"] == "agent-pack" and answer.lower() == "k":
                self._park_proposal(proposal)
            elif answer.lower() in ("o", "y"):
                self._apply_reviewed_proposal(proposal)
            else:
                self._count(SKIPPED_PROPOSALS)
        except (OSError, StopIteration) as error:
            self._failure(error)

    def _park_proposal(self, proposal: dict) -> None:
        root = proposal["root"]
        source = proposal["path"]
        destination = root / "parked" / source.relative_to(root)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
        self.restore.append(f"mv {shlex.quote(str(destination))} {shlex.quote(str(source))}")
        self._count("packs mis de côté")

    def _apply_reviewed_proposal(self, proposal: dict) -> None:
        edits = self.services.proposal_edits(proposal, self.policy)
        validator = CriticalContentValidator([*self.repos, self.cfg])
        critical = [path for path, (old, new) in edits.items() if validator.validation_reason(path, old, new)]
        source = Path(proposal["path"]) if edits else None
        if source is not None and source not in critical:
            critical.append(source)
        if critical and not self._approve_edits(edits, critical):
            self._count("critical proposals refused")
            return
        result = self.services.apply_proposal(
            proposal,
            self.policy,
            self.restore,
            self.trash_root,
            expected_edits=edits if critical else None,
        )
        print(f"     {self.t.grn}{result}{self.t.r}")
        self._count("restructurations appliquées")

    def _approve_edits(self, edits: dict[Path, tuple[str, str]], critical: list[Path]) -> bool:
        self.t.rule("CRITICAL CONTENT VALIDATION")
        for path, (old, new) in edits.items():
            difference = "".join(
                difflib.unified_diff(
                    old.splitlines(True),
                    new.splitlines(True),
                    fromfile=f"before/{self.services.home_path(str(path))}",
                    tofile=f"after/{self.services.home_path(str(path))}",
                )
            )
            print(self.services.redact(difference))
        print("  Critical files: " + ", ".join(self.services.home_path(str(path)) for path in critical))
        if self.full_yes:
            return True
        answer = self.services._ask(
            "  Type approve to apply these exact changes; Enter or any other answer refuses: ", ""
        )
        if answer != "approve":
            print("  Refused; no proposal changes written.")
            return False
        return True

    def _review_descriptions(self) -> None:
        self._section_rule(f"DESCRIPTIONS TROP LONGUES ({len(self.long_desc)})")
        print(
            f"{self.t.dim}La description de chaque skill est relue à chaque tour. Version courte "
            f"proposée ; le texte complet\n"
            f"reste dans metadata.full_description.{self.t.r}"
        )
        if self.long_desc_ro:
            print(
                f"{self.t.dim}({self.services._fr_plural(self.long_desc_ro, 'skill')} en lecture seule "
                f"ignoré{'s' if self.long_desc_ro > 1 else ''} : liens vers un store synchronisé.){self.t.r}"
            )
        for number, path in enumerate(self.long_desc, 1):
            if not self._review_description(number, path):
                break

    def _short_description(self, desc: str) -> str:
        return shorten_description(desc, self.limit)

    def _review_description(self, n: int, sk: Path) -> bool:
        text = self.services.read_text(sk) or ""
        desc = (self.services.split_frontmatter(text)[0] or {}).get("description", "")
        proposal = self._short_description(desc)
        print(
            f"\n{self.t.b}[{n}/{len(self.long_desc)}] {sk.parent.name}{self.t.r} {self.t.dim}{len(desc)} → "
            f"{len(proposal)} caractères{self.t.r}"
        )
        print(f"  {self.t.dim}avant :{self.t.r} {desc[:200]}{'…' if len(desc) > 200 else ''}")
        print(f"  {self.t.grn}après :{self.t.r} {proposal}")
        ans = (
            "o" if self.full_yes else self.services._ask("  o = appliquer · Entrée = passer · q = fin : ", "")
        ).lower()
        if ans == "q":
            return False
        if ans == "o":
            new = self.services.set_frontmatter(text, {"description": proposal})
            new = self.services.move_to_metadata(
                self.services.set_frontmatter(new, {"full_description": desc}), ["full_description"]
            )
            try:
                self._write_text(sk, new)
            except OSError as e:
                self._failure(e)
                return True
            self._count("descriptions raccourcies")
        else:
            self._count(SKIPPED_ACTIONS)
        return True

    def _write_text(self, path: Path, new: str) -> None:
        saved = self.services.backup([path])
        snapshot = saved / str(path.resolve()).lstrip("/")
        self.restore.append(f"cp {shlex.quote(str(snapshot))} {shlex.quote(str(path))}")
        path.write_text(new, encoding="utf-8")

    def _review_misc(self) -> None:
        self._section_rule("MODÈLE ET MCP")
        for item in self.misc:
            if item == "model":
                self._review_model()
            else:
                self._review_mcp(item.message)

    def _review_model(self) -> None:
        print(
            f"Modèle par défaut : {self.t.b}{self.udata['model']}{self.t.r}. "
            "Opus sert à chaque session et aux subagents qui en héritent."
        )
        if not self.full_yes and (
            self.services._ask(
                "  o = passer à Sonnet par défaut (/model opus au besoin) · Entrée = garder : ", ""
            ).lower()
            != "o"
        ):
            self._count(SKIPPED_ACTIONS)
            return
        self.udata["model"] = "sonnet"
        self._write_text(self.cfg / "settings.json", self.services.dump_json(self.udata))
        self._count("modèle changé")

    def _review_mcp(self, message: str) -> None:
        match = re.search(r"(claude mcp add .+)$", message)
        if not match:
            return
        command = match.group(1)
        print(f"Serveur MCP proposé : {self.t.b}{command}{self.t.r}")
        if self.full_yes:
            self._count(SKIPPED_ACTIONS)
            return
        if self.services._ask("  o = lancer la commande · Entrée = passer : ", "").lower() != "o":
            self._count(SKIPPED_ACTIONS)
            return
        result = subprocess.run(shlex.split(command), check=False)
        if result.returncode:
            self._failure(OSError(f"MCP command exited with status {result.returncode}"))
        else:
            self._count("serveurs MCP ajoutés")

    def _summary(self) -> int:
        # ---- summary
        self.t.rule("BILAN")
        print(f"  {len(self.reviewed)} section(s) revue(s) / {len(self.chosen)} selected")
        print(f"  {self.manual_count} manual finding(s) remain in the scan report")
        if self.done:
            for action, n in self.done.items():
                print(f"  {n:>4}  {action}")
        else:
            print("  aucune modification")
        if self.restore:
            print(
                f"\n  Pour tout annuler : {self.t.cyan}{self.services.home_path(str(self.restore.script))}{self.t.r}  (run this script to undo edits and moves)"
            )
        return sum(
            v
            for k, v in self.done.items()
            if "gardés" not in k
            and k not in ("critical proposals refused", "failed actions", SKIPPED_PROPOSALS, SKIPPED_ACTIONS)
        )
