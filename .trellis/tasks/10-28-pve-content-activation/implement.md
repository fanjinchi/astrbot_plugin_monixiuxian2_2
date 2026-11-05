# Implementation Plan: PVE 内容激活与旧 Boss 整删切流

## Dependencies and Gate

1. D 归档（新领域 + fixture 测试 + poller 函数 + 确定性 instance id + AC9 HP 锚证据）。
2. E1 归档（地板单源 + 消费者 + 事务叶子 + 通用文档收尾）。
3. 用户内容批准（combat / narrative 独立，外部门）。
4. 激活前备份：DB 文件、`config/enemies.json` 现文件、`system_config.boss_next_spawn_time` 现值、CSV 旧 SHA-256。

## Steps

1. 备份与基线：DB / 生成配置 / CSV hash 快照；跑一次完整 pytest 确认起点绿。
2. 内容门复核：用 draft CSV 跑一次 preview + 一次 formal（**带 draft manifest 或缺失 manifest 的敌人域调用**；正式 CLI 不带 `--approval-manifest` 时不是报错，而是跳过敌人域、照写其余 4 份配置，所以「应被拒」的证据必须来自敌人域调用）作为 fail-closed 证据；确认 `tests/test_enemy_sync_gate.py` 覆盖负例，并补一条正向用例：`status=final` + `narrative_status=占位` + manifest `narrative_status=["占位"]` → 0 错（现有只有负例 `:181`）。
3. 批准展示与 `status` 升级：向用户展示 28+4 的 `status` / `narrative_status` / manifest / hash / 列范围 / diff；manifest 的 `columns` 必须覆盖整行表头（含叙事列，否则列闸门 fail closed），`datasets` 键恰为 `enemies.csv` / `world_bosses.csv`。给出可复现模板（**`narrative_status` 必须按 CSV 实际填**）：`{"datasets": {"enemies.csv": {"sha256": "<sha256>", "columns": ["<CSV 整行表头>"], "narrative_status": ["占位"]}, "world_bosses.csv": {...}}}`——本批 28+4 全是 `占位`，只批战斗数值就写 `["占位"]`（闸门默认 `["定稿","豁免"]` 会让 32 行全拒）；用户同时批准叙事、CSV 升 `定稿` 后才写 `["定稿"]`；`豁免` 不会出现在 CSV。可复制命令（在**插件根目录**执行，直接产出 JSON）：
```bash
python3 - <<'PY'
import csv, hashlib, json

datasets = {}
for name in ("enemies.csv", "world_bosses.csv"):
    p = f"design_docs/content-design/{name}"
    raw = open(p, "rb").read()
    cols = next(csv.reader(open(p, encoding="utf-8")))
    datasets[name] = {
        "sha256": hashlib.sha256(raw).hexdigest(),
        "columns": cols,
        "narrative_status": ["占位"],  # 本批全占位；叙事获批定稿后改为 ["定稿"]
    }
print(json.dumps({"datasets": datasets}, ensure_ascii=False, indent=2))
PY
```
（输出可直接作为 manifest 文件内容；也可参考 `tests/test_enemy_sync_gate.py` 的 `_manifest` helper。）用户侧据此生成。用户确认后，**由用户侧**把对应行 `status` 改为 `final`，重算 CSV SHA-256 并生成 manifest；再次展示 diff。（AI 不得代改 CSV 状态或批准。）
4. **sync 前**：从现有 `config/enemies.json` 删除 `enemy_groups` 中 `key=top` 的组（手工透传段）。随后正式 sync：`sync_content_to_config.py --approval-manifest <path>`；校验 count 28+4、id 唯一、schema/hash；**正式产物必须含 `world_bosses[*].narrative_approved=true`**（由 manifest 叙事结论派生，见 R1；若 D 尚未扩 `build_world_boss_profile`/必需键/`from_dict`，先补 D 三处再 sync）；不手改配置。
5. 普通 PVE 切流（wiring 断言写法：v2 config 入库后 `load_catalog` 非 None 且 `PVECombatManager.catalog` 为同一实例的单元测试 + `main.py` 源码顺序静态断言；**不要依赖 XiuXianPlugin mock harness**——它 mock `.core` 后 `main.py` 的相对导入（如 `.core.encounter_store` / `.core.health`）会报 ModuleNotFoundError；单跑 `tests/test_feature_switches.py`（11 errors）与 `tests/test_rift_encounter_commands.py`（8 errors）都会炸，整仓跑绿只是前面用例把真实子模块预注册进 `sys.modules` 的顺序依赖）：`prepare_encounter` / `challenge_rift_beast` 默认出怪改走 `catalog.spawn_enemy(player_level, category, difficulty_multiplier)`，难度系数显式取自 `game_config.pve.difficulty_multiplier`（None→1.0）；**catalog 装配归 D**；若 D 归档时 `load_catalog` 仍位于 `PVECombatManager` 构造之后，E2 只把这一行上移（D 已上移则直接复用，任何情况不得第二次 load），以构造参数注入、不用 setter；源路径用 `Path(__file__).parent / "config" / "enemies.json"`；catalog None 时保持旧派生。保留 `low/mid/high` 为 v1 回落、`legacy_guardian` 保留（`key=top` 已在上一步删除）；把 `managers/enemy_manager.py:364-368` 的局部变量 `boss_config` 改名 `boss_mult`（AC3 判据前置）。补「28 名册可达 / 改难度旋钮生效 / 旧派生不命中 / 元婴段只出本段 7 只 / catalog=None 回落不刷守护 / v2 config 下 catalog 非 None」用例；同步 `enemy_catalog.spawn_enemy` docstring。
6. 旧 Boss 整删（与 step 7 同一 commit/检查点）：按 design §3 矩阵删代码 / 配置三元组 / 表（v40 `DROP` + `VERSION_SCHEMA_TABLES` + `system_config` 删键 + 专用 parity 用例）/ 测试；补机械面清理（`handlers/__init__.py`、`managers/__init__.py` 导出、`main.py` 的 `CMD_BOSS_*`/`boss_admins`/`_check_boss_admin`、`core/gm_manager.py` 的形参与帮助文本/`broadcast_callback`）；修正 `lint_narrative.py:318` 的 `world_bosses` 映射来源（改读 `enemies.json` v2；**不要删映射**——`:693` 的 `desc_tables` 含 `world_bosses.csv`、`:707` 直接 `name_maps[table]`，删了会 KeyError）；time-skip 标签改「灵眼下次刷新时间」、新 provider 追加表尾并同批改 registry/migration 注释；v40 登记 `VERSION_SCHEMA_TABLES[40]=()`，并在 `tests/test_pve_persistence_foundation.py:70` 的 `NEW_TABLES` 补 `40: ()`（**它定义在测试里，不在 `data/migration.py`**；boss 不得记入 v40 表集，否则回退用例会对 fresh 库 DROP 不存在的表）；按 R3 保留「生成Boss」+`BOSS_ADMINS` 并改接新领域（`gm_manager` 的 `boss_manager` 形参换成新领域服务、`broadcast_callback` 停用改走 outbox、帮助行改「生成Boss [profile_id]」；`main.py` 的 `BossManager`/`BossHandlers` 导入与构造、`:378` 回调、`:440` handler、`:490/:506` services 键、`:1246/:1257/:1282` 三个命令落点一并改），同时清理玩家可见文案（misc/shop/storage_ring）与 `managers/spirit_eye_manager.py:22` 注释；**本步与 step 7 必须同一 commit/检查点**（中间态会让 main.py 的 boss import 断裂）。
7. 新入口启用（与 step 6 同一 commit）：复用 D 归档后提供的 catalog 装配（不重复注入）；`boss.enabled` 语义与 comment 更新；注册 lifecycle poller（指数退避）与 outbox dispatcher；切新 handler；`生成Boss` 按 R3 改接新领域：不带参数触发 ensure，带 `profile_id` 强制该 Boss（供功能用例按 Boss 验证阶段/击杀/消散），`BOSS_ADMINS` 闸门保留。
8. 端到端验收：spawn→challenge→phase→defeated/dissipated→respawn；北京日 3 次；并发唯一末击；CAS 失败不扣次数；重启恢复；time-skip 矩阵；广播 partial success；**用正式 config 复跑 D AC9 HP 锚**（阶段 40/40/20 加权、±10%、3 次/日×2 日磨死）；记录零奖励过渡态。
9. 回滚演练与文档：备份恢复演练；按 R6 清单逐项同步（含 current-design-report `:78`/`:88`/`:224`、project-architecture `:17`/`:82`、api-overview `:121`/`:130-131`、content-design/README `:29`、sect-system-design `:252`）/ `handlers/misc_handler.py:131`、`handlers/shop_handler.py` 的 `ITEM_ACQUIRE_HINTS`、`handlers/storage_ring_handler.py:120/:528` 的掉落文案 / README / 修仙帮助 / metadata；并核对 `functional_tests/cases/pve/pve-smoke.json` 的「世界Boss」断言仍可命中；记录批准、sync、切流与回滚证据。

## Rollback Points

- RP1：sync 前（config / DB / CSV hash 备份）；
- RP2：旧删 + 切流 + 新启同一检查点前（代码、DB、config 三者同点备份）；
- 任一步失败：整组合回滚（git revert + 备份恢复），禁止只回滚一半或旧 / new 并存。

## Completion Evidence

- 内容批准记录（用户确认 + status 变更 + manifest/hash）+ sync 校验输出；
- 普通 PVE 切流证据（28 名册可达、旧派生不命中、top 组删除、legacy_guardian 回归）；
- 旧 Boss 静态清零报告 + `boss` 表不存在证据（v40 专用 parity + fresh 一致）+ lint_narrative 不再读已删文件；
- 端到端 / 并发 / time-skip / 广播测试摘要 + HP 锚复跑数据；
- 玩家可见文案核对（不再承诺 Boss 掉落）与 `functional_tests` 冒烟命中证据；
- 正向批准用例（占位经 manifest `["占位"]` 放行）记录；
- 回滚演练记录；
- 产品范围 ruff / 完整 pytest 摘要。
