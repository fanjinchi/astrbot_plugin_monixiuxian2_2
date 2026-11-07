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
    """A clean fixture with a correctly gated commit passes the E1 audit."""
    _prepare_e1_root(tmp_path, monkeypatch)
    _write(
        tmp_path,
        "managers/clean.py",
        "async def clean(self):\n"
        '    if getattr(self.db.conn, "_txn_depth", 0) == 0:\n'
        "        await self.db.conn.commit()\n",
    )

    report = _audit.Report()
    _audit.check_e1(report)

    assert report.findings == []


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


def test_commit_gate_is_checked_per_statement_not_per_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A gated function does not hide a bare commit in another function."""
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
        ("managers/dual_cultivation_manager.py", 3)
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
