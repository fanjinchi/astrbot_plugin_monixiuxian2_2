# E2 验证记录（2026-11-19）

## 内容与配置

- 用户最终选择 B：28+4 战斗与叙事均批准；3 个 guardian 保持 `draft / 占位`。
- 正式 CSV hash：`enemies.csv=c2cbb6c388bd8847056e3bbdb61328c71be7c7b1bbcf137a07c2ea690f359ff0`，`world_bosses.csv=f442caa46848928898eb72924932f86f751fc14b3a6310985ffc001ee061f60e`。
- 正式 manifest：`research/approval-manifest.json`，整行表头 + `narrative_status=["定稿"]`。
- `config/enemies.json`：schema v2，28+4、32 个唯一 ID、4/4 `narrative_approved=true`、共享 Schema 0 错误；`enemy_groups=[low,mid,high,legacy_guardian]`，无 `top`。
- 正式配置 SHA-256：`f86e94acc1bad3d61b23bbb403e4218c5d53313df6ba0cbb5712acfacead2d21`。
- dry-run 未改文件；正式 sync 的预算与叙事双闸门均 0 FAIL，日志为 `research/formal-sync.log`。
- 真实 `EnemyCatalog.load` 加载正式配置成功，4/4 世界 Boss 文案批准。

## 自动化与数值验收

- 激活前基线：`uv run python -m pytest tests/ -q` → 1258 passed。
- 批准门槛：`tests/test_enemy_sync_gate.py` → 26 passed；目标文件 ruff format/check 通过。
- `sim_pve_acceptance.py`（28 只 × 双路线，3000 场/格 + 天花板档）→ 64 项全在带内。
- `sim_world_boss_anchor.py`（4 只 × 双路线 × 3 阶段，2000 场/格）→ 4 只全在 ±10% 锚带内。
- `python3 scripts/audit_pve_redesign.py --scope all` → clean (0 findings)。
- `functional_tests/cases/pve/pve-smoke.json` 的 `世界Boss` 正则与新回复兼容；按项目约定未主动运行真实平台用例。

## 回滚演练

- 同点备份目录：`/home/guigui/code/AstrBot/data/plugin_data/astrbot_plugin_monixiuxian2_2/e2-backup-20261119T215501`。
- DB、`enemies.json`、两个 CSV 的 SHA-256 与 `baseline.md` 全部一致。
- 备份内旧 `boss` 表与 `boss_next_spawn_time=1795097191` 可读取。
- 对备份 v1 `enemies.json` 调用真实 `load_catalog` 返回 `None`，确认回滚不会混读 v2 字段。
- 演练只读备份，未修改正式数据库或配置；实际回滚仍须代码 + DB + config 同点恢复，禁止部分回滚。

## 当前质量门

- 独立全量 pytest：**1280 passed**。
- `uv run ruff format --check .`：132 files already formatted。
- 产品范围 `ruff check main.py config_manager.py core data handlers managers models.py models_extended.py scripts tests utils`：All checks passed。
- 从 AstrBot 根目录按真实包路径导入 `data.plugins.astrbot_plugin_monixiuxian2_2.main` 成功，`XiuXianPlugin` 可加载。
- `ruff check .` 额外命中 `.trellis/scripts/` 的 70 个既有 lint 问题；这些工具脚本不在 E2 diff 内，未为本次改动扩大范围修复。
- 使用备份数据库的临时副本执行真实 `MigrationManager.migrate_or_reset()`：v39→v40 成功，7 个 players 行保持不变，旧 `boss` 表与 key 删除，5 张 `world_boss_*` 表保留；临时目录自动清理，正式数据库未触碰。

## 两轮代码复核与最终结果

- 第一轮复核修复：终态后 `WorldBossSpawnRejected` 不再阻断 outbox；v1 catalog 进入维护并停生成；poller 每轮 `ensure_connection`；补动态 targets、顶层 profile、断线恢复回归。
- 第二轮独立复审：**无 p0/p1 阻塞项**；新增真实异常仍指数退避、重连后仓储跟随新连接两条回归。
- 最终全量 pytest：**1282 passed**。
- 最终 `ruff format --check .`：132 files already formatted；产品范围 `ruff check`：All checks passed。
- 最终 `audit_pve_redesign.py --scope all`：clean (0 findings)。
- 最终 `git -c core.whitespace=cr-at-eol diff --check`：通过。
