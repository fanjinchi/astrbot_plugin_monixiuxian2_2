#!/usr/bin/env python3
"""Audit the PVE redesign cleanup contracts.

The Trellis tasks for the PVE enemy / world-boss redesign used to spell out
machine checks as prose (grep commands, file:line inventories).  That drifted
on every edit.  This script is the single executable source of those checks:
the task docs now say "run this, expect exit 0" instead of copying greps.

Scopes map to Trellis children:

- ``e1``: cross-system cleanup (health floor single source, legacy ``Player.hp``
  zeroing, transaction-owner-only commits, crit materialization on both build points).
- ``e2``: old-Boss removal (code / config triple / table version / keys /
  player-visible copy) plus the content-activation guards.
- ``all``: both.

Exit codes: ``0`` clean, ``1`` findings, ``2`` bad usage.  Run from the plugin
root (``python3 scripts/audit_pve_redesign.py --scope all``).

Product code must stay ruff-clean; this script is dev tooling under
``scripts/`` (outside the product-scope ruff path).
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Directories that hold shippable plugin code (product scope).
CODE_DIRS = ("handlers", "managers", "core", "data", "utils", "scripts")
CODE_FILES = ("main.py", "models.py", "models_extended.py", "config_manager.py")


@dataclass
class Finding:
    """One contract violation."""

    contract: str
    path: str
    line: int
    text: str


@dataclass
class Report:
    """Collected findings grouped by contract."""

    findings: list[Finding] = field(default_factory=list)

    def add(self, contract: str, path: str, line: int, text: str) -> None:
        """Record one violation."""
        self.findings.append(Finding(contract, path, line, text.strip()))

    def extend(self, items: list[Finding]) -> None:
        """Merge another batch of findings."""
        self.findings.extend(items)


def _iter_py_files() -> list[Path]:
    """Yield every product Python file under the plugin root."""
    files: list[Path] = []
    for name in CODE_FILES:
        p = ROOT / name
        if p.is_file():
            files.append(p)
    for d in CODE_DIRS:
        for p in sorted((ROOT / d).rglob("*.py")):
            if "__pycache__" in p.parts or p.resolve() == Path(__file__).resolve():
                continue
            files.append(p)
    return files


def _qualname(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str:
    """Return the class/function-qualified name of an AST node."""
    parts = []
    current = node
    while current is not None:
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            parts.append(current.name)
        current = parents.get(current)
    return ".".join(reversed(parts))


def _is_defeat_floor_formula(node: ast.AST) -> bool:
    """Return whether a ceil call recomputes an HP-times-ratio defeat floor."""
    if not (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "ceil"
    ):
        return False
    for candidate in ast.walk(node):
        if not isinstance(candidate, ast.BinOp) or not isinstance(
            candidate.op, ast.Mult
        ):
            continue
        names = [
            item.id if isinstance(item, ast.Name) else item.attr
            for item in ast.walk(candidate)
            if isinstance(item, (ast.Name, ast.Attribute))
        ]
        has_hp = any("hp" in name.lower() for name in names)
        has_ratio = any(
            "ratio" in name.lower() or "floor" in name.lower() for name in names
        ) or any(
            isinstance(item, ast.Constant) and item.value == 0.01
            for item in ast.walk(candidate)
        )
        if has_hp and has_ratio:
            return True
    return False


def _scan_words(
    words: tuple[str, ...], skip_paths: tuple[str, ...] = ()
) -> list[Finding]:
    """Return whole-word matches of ``words`` in product Python files.

    Word matching (``\\b``) is deliberate: the replacement modules are named
    ``world_boss_manager`` / ``world_boss_handlers``, which contain the legacy
    names as substrings and must not be reported.
    """
    pattern = re.compile(r"\b(" + "|".join(re.escape(w) for w in words) + r")\b")
    out: list[Finding] = []
    for path in _iter_py_files():
        rel = path.relative_to(ROOT).as_posix()
        if any(rel.startswith(s) for s in skip_paths):
            continue
        for idx, text in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(text):
                out.append(Finding("word:" + ",".join(words), rel, idx, text))
    return out


def check_e1(report: Report) -> None:
    """Check cross-system cleanup contracts (child E1)."""
    # 1. Health floor single source: the ratio lives in core/health.py only,
    #    adventure_manager keeps a module-level re-export for legacy imports.
    ratio_sites = _scan_words(("DEFEAT_HP_FLOOR_RATIO",))
    allowed = {"core/health.py", "managers/adventure_manager.py"}
    for f in ratio_sites:
        if f.path not in allowed and not f.path.startswith("tests/"):
            report.add("e1.floor-single-source", f.path, f.line, f.text)

    # Constant allowlists alone miss renamed/local formula copies. Match the
    # AST shape ceil(hp * ratio), not merely the shared constant's spelling.
    for path in _iter_py_files():
        rel = path.relative_to(ROOT).as_posix()
        if rel == "core/health.py" or rel.startswith(("tests/", "scripts/")):
            continue
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        for node in ast.walk(ast.parse(text)):
            if _is_defeat_floor_formula(node):
                report.add(
                    "e1.floor-formula-single-source",
                    rel,
                    node.lineno,
                    lines[node.lineno - 1],
                )

    # 2. No ambiguous Player.hp attribute reads outside the legacy Boss module
    #    (legacy module is removed by E2).
    hp_pattern = re.compile(r"\bplayer\.hp\b")
    for f in _iter_py_files():
        rel = f.relative_to(ROOT).as_posix()
        if rel == "managers/boss_manager.py" or rel.startswith("tests/"):
            continue
        for idx, text in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if hp_pattern.search(text):
                report.add("e1.no-player-hp", rel, idx, text)

    # 3. Match assignments to the HP values used by defeat settlement instead
    #    of treating every unrelated conditional expression ending in 1 as HP.
    for f in _iter_py_files():
        rel = f.relative_to(ROOT).as_posix()
        if rel.startswith(("tests/", "scripts/")):
            continue
        text = f.read_text(encoding="utf-8")
        lines = text.splitlines()
        for node in ast.walk(ast.parse(text)):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            target_names = [
                target.attr if isinstance(target, ast.Attribute) else target.id
                for target in targets
                if isinstance(target, (ast.Attribute, ast.Name))
            ]
            if not {"current_hp", "final_hp"}.intersection(target_names):
                continue
            value = node.value
            if isinstance(value, ast.IfExp):
                value = value.orelse
            if (
                isinstance(value, ast.Constant)
                and type(value.value) is int
                and value.value == 1
            ):
                report.add(
                    "e1.no-hardcoded-floor",
                    rel,
                    node.lineno,
                    lines[node.lineno - 1],
                )

    # 4. Only transaction lifecycle owners may commit. A post-write depth
    #    gate is not an ownership boundary and no longer whitewashes a commit.
    commit_owners = {
        "data/data_manager.py::_TransactionCM.__aexit__",
        "data/leaf_write.py::_LeafWriteCM.__aexit__",
        "data/migration.py::MigrationManager.migrate_or_reset",
    }
    for d in ("handlers", "managers", "core", "utils", "data"):
        for path in sorted((ROOT / d).rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            lines = text.splitlines()
            tree = ast.parse(text)
            parents = {
                child: parent
                for parent in ast.walk(tree)
                for child in ast.iter_child_nodes(parent)
            }
            rel = path.relative_to(ROOT).as_posix()
            for node in ast.walk(tree):
                qualname = _qualname(node, parents)

                if (isinstance(node, ast.Attribute) and node.attr == "_txn_depth") or (
                    isinstance(node, ast.Constant) and node.value == "_txn_depth"
                ):
                    depth_owner = (
                        rel == "data/data_manager.py"
                        and qualname
                        in {
                            "_TransactionCM.__aenter__",
                            "_TransactionCM.__aexit__",
                            "DataBase.connect",
                        }
                    ) or (
                        rel == "data/leaf_write.py"
                        and qualname
                        in {
                            "_ensure_txn_ownership",
                            "_LeafWriteCM.__aenter__",
                            "_LeafWriteCM.__aexit__",
                        }
                    )
                    if not depth_owner:
                        report.add(
                            "e1.legacy-depth-gate",
                            rel,
                            node.lineno,
                            lines[node.lineno - 1],
                        )

                if isinstance(node, ast.Name) and node.id == "own_txn":
                    report.add(
                        "e1.legacy-own-txn",
                        rel,
                        node.lineno,
                        lines[node.lineno - 1],
                    )

                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "execute"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)
                    and node.args[0].value.strip().upper().startswith("BEGIN")
                ):
                    begin_owner = (
                        (
                            rel == "data/data_manager.py"
                            and qualname == "_TransactionCM.__aenter__"
                        )
                        or (
                            rel == "data/leaf_write.py"
                            and qualname == "_LeafWriteCM.__aenter__"
                        )
                        or (
                            rel == "data/migration.py"
                            and qualname.startswith("MigrationManager.")
                        )
                    )
                    if not begin_owner:
                        report.add(
                            "e1.leaf-raw-begin",
                            rel,
                            node.lineno,
                            lines[node.lineno - 1],
                        )

                if not (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "commit"
                ):
                    continue
                if f"{rel}::{qualname}" in commit_owners:
                    continue
                report.add(
                    "e1.ungated-commit",
                    rel,
                    node.lineno,
                    lines[node.lineno - 1],
                )

    # 5. Crit materialization: config key present in both the live config and
    #    the defaults, and both build points actually read it.
    cfg = ROOT / "config/game_config.json"
    combat = json.loads(cfg.read_text(encoding="utf-8")).get("combat", {})
    if "base_crit_rate" not in combat:
        report.add(
            "e1.crit-materialized",
            "config/game_config.json",
            0,
            "combat.base_crit_rate missing",
        )
    defaults_text = (ROOT / "data/default_configs.py").read_text(encoding="utf-8")
    if "base_crit_rate" not in defaults_text:
        report.add(
            "e1.crit-materialized",
            "data/default_configs.py",
            0,
            "base_crit_rate missing",
        )
    combat_mgr = (ROOT / "managers/combat_manager.py").read_text(encoding="utf-8")
    if (
        not re.search(r"crit_rate\s*=\s*self\._base_crit_rate", combat_mgr)
        and "crit_rate=self._base_crit_rate" not in combat_mgr
    ):
        report.add(
            "e1.crit-player-wired",
            "managers/combat_manager.py",
            0,
            "build_fighter_from_player does not pass crit_rate",
        )
    pve_mgr = (ROOT / "managers/pve_combat_manager.py").read_text(encoding="utf-8")
    if "base_crit_rate" not in pve_mgr:
        report.add(
            "e1.crit-monster-wired",
            "managers/pve_combat_manager.py",
            0,
            "_build_enemy_fighter does not pass base_crit_rate",
        )


def check_e2(report: Report) -> None:
    """Check old-Boss removal and content-activation contracts (child E2)."""
    # 1. Legacy Boss symbols must be gone (whole-word; new modules are
    #    world_boss_* and must not trip this).
    legacy = ("BossManager", "boss_handlers", "BOSS_CONFIG", "boss_manager")
    for f in _scan_words(legacy):
        report.add("e2.legacy-symbols", f.path, f.line, f.text)

    # 2. Legacy config attribute / loader must be gone.
    for f in _scan_words(("boss_config",)):
        if f.path.startswith("tests/"):
            continue
        report.add("e2.legacy-config-attr", f.path, f.line, f.text)

    # 3. Legacy config file itself must be gone.
    legacy_cfg = ROOT / "config/boss_config.json"
    if legacy_cfg.exists():
        report.add(
            "e2.legacy-config-file", "config/boss_config.json", 0, "file still exists"
        )

    # 4. Legacy key may survive only inside the v40 DELETE statement / tests.
    key_pattern = re.compile(r"boss_next_spawn_time")
    for f in _iter_py_files():
        rel = f.relative_to(ROOT).as_posix()
        if rel.startswith("tests/") or rel == "data/migration.py":
            continue
        for idx, text in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if key_pattern.search(text):
                report.add("e2.legacy-key", rel, idx, text)

    # 5. Player-visible copy must not promise Boss drops.
    copy_pattern = re.compile(r"Boss\s*(击杀)?\s*掉落|挑战Boss获取奖励")
    for path in sorted((ROOT / "handlers").rglob("*.py")):
        for idx, text in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if copy_pattern.search(text):
                report.add(
                    "e2.player-copy",
                    path.relative_to(ROOT).as_posix(),
                    idx,
                    text,
                )

    # 6. Time-skip provider must not import the removed module.
    registry = (ROOT / "core/time_skip_registry.py").read_text(encoding="utf-8")
    if "managers.boss_manager" in registry:
        report.add(
            "e2.time-skip-provider",
            "core/time_skip_registry.py",
            0,
            'string "managers.boss_manager" still in _PROVIDER_MODULES',
        )

    # 7. Generated v2 config must carry a boolean narrative decision on world
    #    bosses and no legacy top group; false is valid for combat-only approval.
    enemies_cfg = ROOT / "config/enemies.json"
    doc = json.loads(enemies_cfg.read_text(encoding="utf-8"))
    if doc.get("schema_version") == 2:
        groups = [g.get("key") for g in doc.get("enemy_groups", [])]
        if "top" in groups:
            report.add(
                "e2.top-group",
                "config/enemies.json",
                0,
                "enemy_groups still has key=top",
            )
        for wb in doc.get("world_bosses", []):
            if not isinstance(wb.get("narrative_approved"), bool):
                report.add(
                    "e2.narrative-approved",
                    "config/enemies.json",
                    0,
                    f"world boss {wb.get('id')!r} missing boolean narrative_approved",
                )


def main(argv: list[str] | None = None) -> int:
    """Run the requested audit scope and print findings."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scope",
        choices=("e1", "e2", "all"),
        default="all",
        help="which child contract set to audit",
    )
    args = parser.parse_args(argv)

    report = Report()
    if args.scope in ("e1", "all"):
        check_e1(report)
    if args.scope in ("e2", "all"):
        check_e2(report)

    if not report.findings:
        print(f"[audit] scope={args.scope}: clean (0 findings)")
        return 0

    for f in report.findings:
        print(f"{f.contract}\t{f.path}:{f.line}\t{f.text[:120]}")
    print(f"[audit] scope={args.scope}: {len(report.findings)} finding(s)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
