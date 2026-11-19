# E2 激活前基线（2026-11-19）

- 质量基线：`uv run python -m pytest tests/ -q` → **1258 passed**。
- 审计基线：`python3 scripts/audit_pve_redesign.py --scope all` → **54 findings**，均为 E2 计划内的旧 Boss、旧配置、旧文案和 time-skip provider 清理项。
- 用户决策：完整 28+4 战斗内容已批准；叙事保持 `占位`，不批准广播。CSV 仍待用户侧执行 `status=draft→final`。
- 正式配置：尚未 sync，`config/enemies.json` 保持 v1。

## 同点备份

目录：`/home/guigui/code/AstrBot/data/plugin_data/astrbot_plugin_monixiuxian2_2/e2-backup-20261119T215501`

包含 SQLite 在线备份、`enemies.json`、两个源 CSV 和 `baseline.txt`。旧 `system_config.boss_next_spawn_time=1795097191`。

| 文件 | SHA-256 |
|---|---|
| `xiuxian_data_lite.db` | `be4203ad4ccdda486c3f7657c1a71054dcc8b24828853b8fe3015389a1149d23` |
| `enemies.json` | `461be7f8641e3a2ad1b1cffd23351116bafad84677adb124feea446f21841855` |
| `enemies.csv` | `b558813bbd8e0e4b85a43a07e4ca791e6ae45046c7d59aca42f99cf3268e7c3c` |
| `world_bosses.csv` | `99386e1b580fa4a962be6ff5089d0e4111f3dea8721da52fe23a8029dda9b05b` |

回滚必须按 E2 R6 同时恢复代码、数据库和生成配置，禁止部分回滚或新旧 Boss 双跑。

## 内容门槛复核

- `lint_narrative.py`：0 FAIL；PVE 文案仅报告既有 `占位` 待审警告。
- `validate_budget.py`：0 FAIL；28 名册矩阵、3 守护、词缀与 Boss 技能检查通过，其他 legacy 警告不属于本次变更。
- `tests/test_enemy_sync_gate.py`：26 passed。覆盖 combat-only 占位保持 `narrative_approved=false`、定稿为 true、显式豁免为 true，以及 draft/hash/列越权 fail closed。
- 目标文件 ruff format/check 通过。
