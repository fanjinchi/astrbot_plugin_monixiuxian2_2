"""Regression tests for the executable PVE redesign audit gates."""

import json
from pathlib import Path

import pytest

from tests.helpers import load_module

_audit = load_module("audit_pve_redesign", "scripts/audit_pve_redesign.py")


def _write(root: Path, rel: str, text: str) -> Path:
    """Write one fixture file below the isolated audit root."""
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _prepare_e1_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Create the minimal valid files required by the complete E1 audit."""
    monkeypatch.setattr(_audit, "ROOT", tmp_path)
    _write(
        tmp_path,
        "config/game_config.json",
        json.dumps({"combat": {"base_crit_rate": 0.05}}),
    )
    _write(tmp_path, "data/default_configs.py", "base_crit_rate = 0.05\n")
    _write(
        tmp_path,
        "managers/combat_manager.py",
        "crit_rate = self._base_crit_rate\n",
    )
    _write(tmp_path, "managers/pve_combat_manager.py", "base_crit_rate = 0.05\n")


def test_clean_e1_fixture_has_no_findings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A clean fixture without business-layer commits passes the E1 audit."""
    _prepare_e1_root(tmp_path, monkeypatch)
    _write(
        tmp_path,
        "managers/clean.py",
        "async def clean(self):\n    await self.db.update_player(player)\n",
    )

    report = _audit.Report()
    _audit.check_e1(report)

    assert report.findings == []


@pytest.mark.parametrize(
    "formula",
    [
        "math.ceil(max_hp * DEFEAT_HP_FLOOR_RATIO)",
        "math.ceil(player.base_hp * local_ratio)",
    ],
)
def test_duplicate_defeat_floor_formula_is_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, formula: str
) -> None:
    """The old fallback and a renamed equivalent both fail the formula-level gate."""
    _prepare_e1_root(tmp_path, monkeypatch)
    _write(
        tmp_path,
        "managers/adventure_manager.py",
        "import math\n"
        "class AdventureManager:\n"
        "    def _defeat_hp_floor(self, player):\n"
        "        max_hp = player.base_hp\n"
        "        local_ratio = 0.01\n"
        f"        return max(1, {formula})\n",
    )

    report = _audit.Report()
    _audit.check_e1(report)

    findings = [
        finding
        for finding in report.findings
        if finding.contract == "e1.floor-formula-single-source"
    ]
    assert [(finding.path, finding.line) for finding in findings] == [
        ("managers/adventure_manager.py", 6)
    ]


def test_health_domain_remains_the_only_allowed_floor_formula(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The canonical HealthService formula does not self-hit the audit."""
    _prepare_e1_root(tmp_path, monkeypatch)
    _write(
        tmp_path,
        "core/health.py",
        "import math\n"
        "def defeat_hp_floor(player):\n"
        "    return max(1, math.ceil(player.max_hp * DEFEAT_HP_FLOOR_RATIO))\n",
    )

    report = _audit.Report()
    _audit.check_e1(report)

    assert not [
        finding
        for finding in report.findings
        if finding.contract == "e1.floor-formula-single-source"
    ]


def test_scanner_excludes_only_itself_from_scripts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Audit rule strings do not self-hit while other scripts remain scanned."""
    monkeypatch.setattr(_audit, "ROOT", tmp_path)
    audit_path = _write(
        tmp_path,
        "scripts/audit_pve_redesign.py",
        "BossManager\nboss_next_spawn_time\n",
    )
    _write(tmp_path, "scripts/other.py", "BossManager\n")
    monkeypatch.setattr(_audit, "__file__", str(audit_path))

    findings = _audit._scan_words(("BossManager",))

    assert [(finding.path, finding.line) for finding in findings] == [
        ("scripts/other.py", 1)
    ]


def test_unrelated_conditional_else_one_is_not_a_hp_floor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-HP default of one does not trigger the defeat-floor rule."""
    _prepare_e1_root(tmp_path, monkeypatch)
    _write(
        tmp_path,
        "data/database_extended.py",
        "def get_star_level(row):\n    return row[0] if row else 1\n",
    )

    report = _audit.Report()
    _audit.check_e1(report)

    assert not [
        finding
        for finding in report.findings
        if finding.contract == "e1.no-hardcoded-floor"
    ]


@pytest.mark.parametrize(
    "statement",
    ["player.current_hp = 1", "final_hp = result if won else 1"],
)
def test_real_hardcoded_hp_floor_is_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, statement: str
) -> None:
    """Direct and conditional defeat-HP assignments of one remain forbidden."""
    _prepare_e1_root(tmp_path, monkeypatch)
    _write(
        tmp_path,
        "managers/pve_combat_manager.py",
        f"base_crit_rate = 0.05\n{statement}\n",
    )

    report = _audit.Report()
    _audit.check_e1(report)

    assert [
        (finding.contract, finding.path, finding.text)
        for finding in report.findings
        if finding.contract == "e1.no-hardcoded-floor"
    ] == [("e1.no-hardcoded-floor", "managers/pve_combat_manager.py", statement)]


def test_every_non_owner_commit_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both raw and legacy post-write-gated business commits are rejected."""
    _prepare_e1_root(tmp_path, monkeypatch)
    _write(
        tmp_path,
        "managers/dual_cultivation_manager.py",
        "class Manager:\n"
        "    async def _create_request(self):\n"
        "        await self.db.conn.commit()\n"
        "    async def gated(self):\n"
        '        if getattr(self.db.conn, "_txn_depth", 0) == 0:\n'
        "            await self.db.conn.commit()\n",
    )

    report = _audit.Report()
    _audit.check_e1(report)

    findings = [
        finding
        for finding in report.findings
        if finding.contract == "e1.ungated-commit"
    ]
    assert [(finding.path, finding.line) for finding in findings] == [
        ("managers/dual_cultivation_manager.py", 3),
        ("managers/dual_cultivation_manager.py", 6),
    ]


def test_commit_allowlist_is_per_lifecycle_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An owner file does not hide commits in its unrelated functions."""
    _prepare_e1_root(tmp_path, monkeypatch)
    _write(
        tmp_path,
        "data/leaf_write.py",
        "class _LeafWriteCM:\n"
        "    async def __aexit__(self):\n"
        "        await self.conn.commit()\n"
        "    async def unrelated(self):\n"
        "        await self.conn.commit()\n",
    )

    report = _audit.Report()
    _audit.check_e1(report)

    findings = [
        finding
        for finding in report.findings
        if finding.contract == "e1.ungated-commit"
    ]
    assert [(finding.path, finding.line) for finding in findings] == [
        ("data/leaf_write.py", 5)
    ]


def test_storage_ring_style_foreign_depth_gate_is_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rejected storage-ring depth-only branch is visible to the E1 audit."""
    _prepare_e1_root(tmp_path, monkeypatch)
    _write(
        tmp_path,
        "core/storage_ring_manager.py",
        "class StorageRingManager:\n"
        "    async def store_item(self):\n"
        '        if getattr(self.db.conn, "_txn_depth", 0) > 0:\n'
        "            return await self._store_item_inner(player)\n",
    )

    report = _audit.Report()
    _audit.check_e1(report)

    findings = [
        finding
        for finding in report.findings
        if finding.contract == "e1.legacy-depth-gate"
    ]
    assert [(finding.path, finding.line) for finding in findings] == [
        ("core/storage_ring_manager.py", 3)
    ]


def test_legacy_own_txn_and_raw_begin_are_detected_globally(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Legacy leaf transaction shapes outside the original nine files fail."""
    _prepare_e1_root(tmp_path, monkeypatch)
    _write(
        tmp_path,
        "handlers/legacy.py",
        "async def write(self):\n"
        '    own_txn = getattr(self.db.conn, "_txn_depth", 0) == 0\n'
        '    await self.db.conn.execute("BEGIN IMMEDIATE")\n',
    )

    report = _audit.Report()
    _audit.check_e1(report)

    findings = [
        (finding.contract, finding.path, finding.line)
        for finding in report.findings
        if finding.contract
        in {"e1.legacy-depth-gate", "e1.legacy-own-txn", "e1.leaf-raw-begin"}
    ]
    assert sorted(findings) == [
        ("e1.leaf-raw-begin", "handlers/legacy.py", 3),
        ("e1.legacy-depth-gate", "handlers/legacy.py", 2),
        ("e1.legacy-own-txn", "handlers/legacy.py", 2),
    ]


def _prepare_e2_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Create a minimal v2 config root for the narrative audit."""
    monkeypatch.setattr(_audit, "ROOT", tmp_path)
    _write(tmp_path, "core/time_skip_registry.py", "_PROVIDER_MODULES = ()\n")


def test_combat_only_narrative_false_is_valid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Combat-only activation may generate false narrative approval flags."""
    _prepare_e2_root(tmp_path, monkeypatch)
    _write(
        tmp_path,
        "config/enemies.json",
        json.dumps(
            {
                "schema_version": 2,
                "enemy_groups": [],
                "world_bosses": [{"id": "wb_lq_ba", "narrative_approved": False}],
            }
        ),
    )

    report = _audit.Report()
    _audit.check_e2(report)

    assert report.findings == []


def test_narrative_approval_must_be_a_boolean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing or non-boolean narrative decision still fails closed."""
    _prepare_e2_root(tmp_path, monkeypatch)
    _write(
        tmp_path,
        "config/enemies.json",
        json.dumps(
            {
                "schema_version": 2,
                "enemy_groups": [],
                "world_bosses": [{"id": "wb_lq_ba", "narrative_approved": "true"}],
            }
        ),
    )

    report = _audit.Report()
    _audit.check_e2(report)

    assert [finding.contract for finding in report.findings] == [
        "e2.narrative-approved"
    ]
