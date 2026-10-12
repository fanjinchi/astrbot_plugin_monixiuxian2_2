"""Child B（10-10-pve-enemy-catalog-runtime）内容闸门与 preview 渲染测试。

覆盖 R1/AC1/AC2：
- schema 负例矩阵（缺列/非法值/越权字段/旧动态派生字段）；
- sync adapter 正式写闸门 fail closed：draft 行、缺 manifest、SHA-256
  漂移、列越权、占位叙事未获批，任何一条都不产出文档；
- preview 渲染（真实只读 CSV → 内存文档）：28+4、确定性、审计头。

不触碰 config/：正式写入路径全部在 --dry-run 或内存层被拦截。
"""

import csv
from pathlib import Path

from tests.helpers import PLUGIN_ROOT, load_module

_schema = load_module("enemy_schema", "core/enemy_schema.py")
_sync = load_module("sync_content_to_config", "scripts/sync_content_to_config.py")

DESIGN_DIR = PLUGIN_ROOT / "design_docs" / "content-design"

CSV_NAMES = (_schema.ROSTER_CSV, _schema.WORLD_BOSS_CSV)


def _rewrite_csvs(src_dir: Path, dst_dir: Path, *, status: str, narrative: str):
    """Copy enemy CSVs into dst_dir rewriting status/narrative columns.

    守护者行（tier=guardian）保持原 draft/占位——它不进名册 sections，
    也不应被审批闸门误伤（透传专项组配置源，R4）。
    """
    dst_dir.mkdir(parents=True, exist_ok=True)
    for name in CSV_NAMES:
        rows = list(csv.DictReader((src_dir / name).open(encoding="utf-8")))
        fields = list(rows[0].keys())
        for r in rows:
            if (r.get("tier") or "").strip() != "guardian":
                r["status"] = status
                r["narrative_status"] = narrative
        with (dst_dir / name).open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)


def _manifest(design_dir: Path, *, columns=None, narrative=None, break_hash=False):
    """Build an approval manifest over the CSVs in design_dir."""
    datasets = {}
    for name in CSV_NAMES:
        digest = _schema.sha256_file(design_dir / name)
        fields = list(csv.DictReader((design_dir / name).open(encoding="utf-8")))[0]
        cols = list(fields) if columns is None else columns.get(name, list(fields))
        if break_hash:
            digest = "0" * 64
        datasets[name] = {
            "sha256": digest,
            "columns": cols,
            "narrative_status": (["定稿", "豁免"] if narrative is None else narrative),
        }
    return {"datasets": datasets}


def _render(design_dir, manifest=None, existing=None):
    return _sync.render_enemy_document(
        design_dir,
        manifest=manifest,
        manifest_path=None,
        existing_config=existing,
    )


# ────────────────────────────── preview：真实 CSV 全量渲染 ──────────────────


class TestPreviewRendering:
    def test_real_csv_28_plus_4(self):
        doc, errors = _render(DESIGN_DIR)
        assert errors == []
        assert len(doc["enemies"]) == 28
        assert len(doc["world_bosses"]) == 4
        assert doc["schema_version"] == _schema.SCHEMA_VERSION
        assert doc["profile_version"] == _schema.PROFILE_VERSION

    def test_preview_never_carries_approval_state(self):
        doc, _ = _render(DESIGN_DIR)
        assert doc["source"]["mode"] == "preview"
        assert doc["source"]["approval"] is None

    def test_preview_is_deterministic_and_sorted(self):
        a, _ = _render(DESIGN_DIR)
        b, _ = _render(DESIGN_DIR)
        assert a == b
        ids = [e["id"] for e in a["enemies"]]
        assert ids == sorted(ids)
        wb_ids = [w["id"] for w in a["world_bosses"]]
        assert wb_ids == sorted(wb_ids)

    def test_preview_document_passes_validator(self):
        doc, _ = _render(DESIGN_DIR)
        assert _schema.validate_enemy_document(doc) == []

    def test_csv_sha256_audited_in_source_header(self):
        doc, _ = _render(DESIGN_DIR)
        for name in CSV_NAMES:
            assert doc["source"][name]["sha256"] == _schema.sha256_file(
                DESIGN_DIR / name
            )


# ────────────────────────────── 正式写闸门（fail closed） ────────────────────


class TestFormalApprovalGate:
    def test_missing_manifest_rejected(self):
        # 正式写路径缺 manifest 必须 fail closed（render(manifest=None) 本身
        # 是 preview 模式——正式入口未带 --approval-manifest 时 main() 直接
        # 跳过该域，config/enemies.json 不被触碰）
        errs = _schema.check_approval(None, {}, {}, require_final=True)
        assert errs == [errs[0]]
        assert "缺少 --approval-manifest" in errs[0]

    def test_draft_rows_rejected(self, tmp_path):
        design = tmp_path / "design"
        _rewrite_csvs(DESIGN_DIR, design, status="draft", narrative="定稿")
        doc, errors = _render(design, manifest=_manifest(design))
        assert doc == {}
        assert any("status 非 final" in e for e in errors)

    def test_hash_drift_rejected(self, tmp_path):
        design = tmp_path / "design"
        _rewrite_csvs(DESIGN_DIR, design, status="final", narrative="定稿")
        manifest = _manifest(design, break_hash=True)
        doc, errors = _render(design, manifest=manifest)
        assert doc == {}
        assert any("SHA-256 漂移" in e for e in errors)

    def test_column_overreach_rejected(self, tmp_path):
        design = tmp_path / "design"
        _rewrite_csvs(DESIGN_DIR, design, status="final", narrative="定稿")
        fields = list(
            csv.DictReader((design / _schema.ROSTER_CSV).open(encoding="utf-8"))
        )[0]
        shrunk = {
            _schema.ROSTER_CSV: [c for c in fields if c != "description"],
            _schema.WORLD_BOSS_CSV: list(
                csv.DictReader((design / _schema.WORLD_BOSS_CSV).open(encoding="utf-8"))
            )[0],
        }
        doc, errors = _render(design, manifest=_manifest(design, columns=shrunk))
        assert doc == {}
        assert any("列越权" in e for e in errors)

    def test_placeholder_narrative_not_approved_rejected(self, tmp_path):
        design = tmp_path / "design"
        _rewrite_csvs(DESIGN_DIR, design, status="final", narrative="占位")
        doc, errors = _render(design, manifest=_manifest(design))
        assert doc == {}
        assert any("未在 manifest 叙事决策中获批" in e for e in errors)

    def test_guardian_draft_rows_do_not_block_formal(self, tmp_path):
        """守护者行是专项组配置源（不写进名册 sections），draft 不拦 Batch 5。"""
        design = tmp_path / "design"
        _rewrite_csvs(DESIGN_DIR, design, status="final", narrative="定稿")
        # 恢复 guardian 行为 draft/占位
        path = design / _schema.ROSTER_CSV
        rows = list(csv.DictReader(path.open(encoding="utf-8")))
        for r in rows:
            if (r.get("tier") or "") == "guardian":
                r["status"] = "draft"
                r["narrative_status"] = "占位"
        with path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        existing = {"enemy_groups": [], "drop_tables": {}, "naming": {}}
        doc, errors = _render(design, manifest=_manifest(design), existing=existing)
        assert errors == []
        assert doc["enemy_groups"] == []

    def test_formal_happy_path_carries_approval_and_passthrough(self, tmp_path):
        design = tmp_path / "design"
        _rewrite_csvs(DESIGN_DIR, design, status="final", narrative="定稿")
        existing = {
            "enemy_groups": [{"key": "legacy_guardian"}],
            "drop_tables": {"low": []},
            "naming": {"normal": "{name}"},
        }
        doc, errors = _render(design, manifest=_manifest(design), existing=existing)
        assert errors == []
        assert doc["source"]["mode"] == "formal"
        assert doc["source"]["approval"]["datasets"]
        assert doc["enemy_groups"] == existing["enemy_groups"]
        assert doc["drop_tables"] == existing["drop_tables"]
        # 旧动态派生字段不得混入正式文档
        assert "difficulty_coefficients" not in doc
        assert _schema.validate_enemy_document(doc) == []

    def test_formal_requires_existing_config(self, tmp_path):
        design = tmp_path / "design"
        _rewrite_csvs(DESIGN_DIR, design, status="final", narrative="定稿")
        doc, errors = _render(design, manifest=_manifest(design), existing=None)
        assert doc == {}
        assert any("透传源" in e for e in errors)


# ────────────────────────────── schema 负例矩阵 ─────────────────────────────


class TestSchemaNegatives:
    def _row(self):
        rows = list(
            csv.DictReader((DESIGN_DIR / _schema.ROSTER_CSV).open(encoding="utf-8"))
        )
        return {r["id"]: r for r in rows if r["tier"] != "guardian"}

    def test_garbage_numeric_rejected(self):
        row = dict(self._row()["mon_lq_zhu"])
        row["hp"] = "七十七"
        errors: list[str] = []
        out = _schema.build_enemy_profile(row, "t", errors)
        assert out is None and any("hp" in e for e in errors)

    def test_normal_declaring_affix_rejected(self):
        row = dict(self._row()["mon_lq_zhu"])
        row["affix"] = "嗜血"
        errors: list[str] = []
        assert _schema.build_enemy_profile(row, "t", errors) is None
        assert any("affix" in e for e in errors)

    def test_unknown_affix_rejected(self):
        rows = list(
            csv.DictReader((DESIGN_DIR / _schema.ROSTER_CSV).open(encoding="utf-8"))
        )
        elite = {r["id"]: r for r in rows if r["tier"] == "elite"}
        row = dict(next(iter(elite.values())))
        row["affix"] = "无敌"
        errors: list[str] = []
        assert _schema.build_enemy_profile(row, "t", errors) is None
        assert any("elite affix" in e for e in errors)

    def test_unknown_segment_rejected(self):
        row = dict(self._row()["mon_lq_zhu"])
        row["segment"] = "化神"
        errors: list[str] = []
        assert _schema.build_enemy_profile(row, "t", errors) is None
        assert any("segment" in e for e in errors)

    def test_level_outside_range_rejected(self):
        row = dict(self._row()["mon_lq_zhu"])
        row["level"] = "99"
        errors: list[str] = []
        assert _schema.build_enemy_profile(row, "t", errors) is None
        assert any("outside level_range" in e for e in errors)

    def test_world_boss_unknown_skill_key_rejected(self):
        rows = list(
            csv.DictReader((DESIGN_DIR / _schema.WORLD_BOSS_CSV).open(encoding="utf-8"))
        )
        row = dict(rows[0])
        row["skill_key"] = "灭世"
        errors: list[str] = []
        assert _schema.build_world_boss_profile(row, "t", errors) is None
        assert any("skill_key" in e for e in errors)

    def test_world_boss_phase_thresholds_rejected(self):
        rows = list(
            csv.DictReader((DESIGN_DIR / _schema.WORLD_BOSS_CSV).open(encoding="utf-8"))
        )
        row = dict(rows[0])
        row["phase_thresholds"] = "20/60"
        errors: list[str] = []
        assert _schema.build_world_boss_profile(row, "t", errors) is None
        assert any("phase_thresholds" in e for e in errors)

    def test_legacy_dynamic_keys_rejected_in_document(self):
        doc, _ = _render(DESIGN_DIR)
        doc = dict(doc)
        doc["difficulty_coefficients"] = {"normal": 0.85}
        assert any(
            "difficulty_coefficients" in e for e in _schema.validate_enemy_document(doc)
        )
        doc.pop("difficulty_coefficients")
        doc["schema_version"] = 1
        assert any("schema_version" in e for e in _schema.validate_enemy_document(doc))

    def test_row_errors_are_attributable_per_row(self):
        """每行错误须带该行 ctx（共享 sink 泄漏回归防护）。"""
        rows = list(
            csv.DictReader((DESIGN_DIR / _schema.ROSTER_CSV).open(encoding="utf-8"))
        )
        bad = [r for r in rows if r["tier"] != "guardian"][:2]
        bad[0] = dict(bad[0], hp="x")
        bad[1] = dict(bad[1], segment="化神")
        errors: list[str] = []
        for row in bad:
            ctx = f"row[{row['id']}]"
            before = len(errors)
            _schema.build_enemy_profile(row, ctx, errors)
            assert len(errors) > before, f"{ctx}: 应产生错误"
            assert all(e.startswith(f"row[{row['id']}]") for e in errors[before:])
