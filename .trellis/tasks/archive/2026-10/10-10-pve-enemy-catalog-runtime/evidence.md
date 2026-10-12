# Completion Evidence — child B PVE 固定名册内容管线与敌人运行时（2026-10-12）

范围声明：本 child 只交付代码基座 + preview 验收。**未执行正式内容 sync**（内容仍 `status=draft`）、**未切调用方**（普通 PVE 运行时仍走动态路径）、**未实现 Step 7 奖励经济**（固定 profile 的 `exp` 恒 0 为占位）。

## 1. schema / adapter 与 manifest 格式（R1，AC1/AC2）

- `core/enemy_schema.py`（新增，纯 stdlib，无 astrbot 依赖，供 sync 脚本经 importlib 文件加载复用）：
  - `SCHEMA_VERSION=2` / `PROFILE_VERSION=1`；`build_enemy_profile` / `build_world_boss_profile`（CSV 行→profile，逐字段校验：稳定 id 唯一、段位∈{练气,筑基,金丹,元婴}、tier∈{normal,elite,boss}（`tier=guardian` 动态匹配行由 adapter 跳过、不入名册）、normal 禁词条、elite 必带词条且∈{狂暴,坚甲,嗜血}、boss 必带 boss_skill 且∈四类、level 落 `level_range` 内、五维正整数、护甲整数）；错误按行归属（`{name}/{id}: …`）。
  - 词条→触发技、Boss 机制、世界 Boss 招牌技映射的**单一真相**：`AFFIX_TRIGGER_SKILLS`（仅嗜血为触发技；狂暴/坚甲为纯面板已烘入 CSV 绝对值）、`BOSS_SKILL_MECHANICS`（拱土疗伤 on_defense heal 12%/7%、狼王连咬 on_attack combo 15%/0.5、鳞甲反震 on_defense counter 20%/0.3、九尾现形 ultimate boss_rage ≤30% buff damage 0.10×3r）、`WORLD_BOSS_SIGNATURE_SKILLS`（连咬/反震/灼烧 dot 20%/0.15×3、绞杀 stun 15%）；`validate_enemy_document` 拒绝 legacy 死键（difficulty_coefficients/templates/category_multipliers/level_range/jitter）与 schema_version≠2；世界 Boss 校验阶段阈值降序 `60/20`、phase 倍率、48h/每日3次/12h/24h、招牌技白名单。
  - 结构不变量与 `design_docs/content-design/sim_pve_acceptance.py`（验收模拟器）常数互锁：`tests/test_enemy_catalog_runtime.py::TestSimParity` 用 ast 静态提取 sim 常数逐 dict 断言相等。
- `scripts/sync_content_to_config.py` 敌人域（新增独立受闸域）：
  - **preview 模式** `--enemies-preview-out PATH`：真实只读 CSV 渲染到指定路径（CLI 守卫拒绝 `config/` 目录下任何目标——预览文档无专项组透传键，落进正式目录会毁掉守护/秘境数据；`TestCliPreviewGuard` 负向覆盖），`source.mode=preview`、`approval=null`；与 `--approval-manifest` 互斥（preview 不得接受或伪造正式批准状态）。
  - **正式模式** `--approval-manifest PATH`：fail closed 闸门 `check_approval`——缺 manifest（`缺少 --approval-manifest：敌人正式写路径拒绝执行（fail closed）`）、行 `status≠final`（`status 非 final（draft 内容只能 preview 渲染）`；`status` 列即 R1 所说的等价机器字段=战斗数值闸门，与叙事独立批准）、manifest CSV SHA-256 漂移（`CSV SHA-256 漂移`）、获批数据集外/列范围越权（`列越权`）、`narrative_status` 未在 manifest `narrative_status` 决策列表获批（`未在 manifest 叙事决策中获批`）。战斗列批准与叙事批准是**相互独立的闸门**（manifest 列范围不覆盖占位叙事，叙事须单独进 `narrative_status` 决策），任一闸门未过都拒绝正式写（无"部分写入"通道）；guardian 行（动态匹配、无数值列）不阻塞名册 final。
  - 正式输出确定性排序（按 id），`source` 内嵌 CSV 审计（路径/SHA-256/行数）与 approval（manifest 路径+SHA+datasets 决策副本）；`enemy_groups`/`drop_tables`/`naming` 从现有 config 透传（专项组与掉落不在 CSV 治理域）。
  - **操作说明（AC2）**：战斗数值批准 = 行 `status=final` + manifest 战斗列范围；`narrative_status`（占位→定稿/豁免）为独立决策项，两者可分离批准；未批准前任何 sync 运行只打印 `enemy/world-boss domain: SKIPPED`，不写 `config/enemies.json`。
- `tests/test_enemy_sync_gate.py`（新增 24 例）：preview 28+4 渲染/确定性/validator 干净/SHA 审计；CLI 守卫（preview 拒写 `config/`、tmp 路径可写）；正式五类负向（缺 manifest、draft、hash 漂移、列越权、未批叙事）全部 fail closed 且不产出文档；guardian-draft 不阻塞；happy path 正式渲染 + 透传 + approval datasets + 无 legacy 键；schema 负例矩阵（垃圾数值、normal+词条、未知词条/段位、level 越界、未知招牌技、阶段升序、legacy 文档、逐行错误归属）。

## 2. 不可变 catalog / resolver（R2，AC4 的代码基座）

- `managers/enemy_catalog.py`（新增）：
  - `EnemyCombatProfile`/`WorldBossProfile` frozen dataclass + `from_dict`（白名单挑选已知字段、未知键忽略——文档由 sync 确定性生成，`validate_enemy_document` 在写入口严格拦截 legacy 死键/未知枚举/重复 id，profile 内未知键无现实注入通道；skill 列表逐 dict 复制防外部变异）；`EnemyCatalog` 构造即 `validate_enemy_document`，失败抛 `EnemyCatalogError`；`.roster`/`.world_bosses` 不可变 tuple；`(realm_segment, category)` 索引 + 段位等级带（由 28 只 `level_range` 推导，边界外钳制）。
  - `spawn_enemy(player_level, category, difficulty_multiplier)`：段位由等级定、池内随机取一只，绝对面板直通；**难度只在 `profile_to_enemy` 单点乘伤害**（`max(1, int(dmg×mult))`，HP/护甲/身法/迅捷/暴击/词条不受影响）；注入 rng 可确定性重放；user_id 形状 `enemy_{id}_{seq}_{token}`。
  - `load_catalog(path)` 对旧 v1 config 返回 None（动态路径继续服务，Batch 5 切流钩子），v2 坏档抛错；`EnemyCatalog.read_document` 暴露原始 JSON。
  - 专项组兼容（R4）的实际交付形态：未新增独立的 `group_to_profile` 函数——定向组生成保持 `EnemyManager.spawn_enemy_from_group` 原入口与选组来源（秘境兽 enemy_group_key、传承守护 `get_guardian_group_key()`），输出改为**统一档案形状**的 Enemy（`profile_id`=模板 key、真实 `level_index`、模板 `trigger_skills`/`ultimates` passthrough），战斗入口与固定名册共用**同一个** `build_enemy_fighter` mapper；守护胜率按 Step 3「只做兼容适配，不重新平衡」不变。
- 旧动态路径治理（即刻生效的语义修正，非切流）：
  - `managers/enemy_manager.py`：`difficulty_coefficients` 加载/属性删除（死配置，Step 3 定案清尸）；`spawn_enemy` 与 `spawn_enemy_from_group` 难度块改为**只乘伤害**（原三乘违规点 :367-370/:475-478）；两条路径 `Enemy` 新增 `level_index`（`_actual_level()` 1-based 语义，修坑 #3/#5）与 `profile_id/affix/boss_skill/trigger_skills/ultimates` 字段（默认值向后兼容）；守护组模板的 trigger_skills/ultimates 经配置 passthrough（现有守护模板无技能→行为不变）。
  - `data/default_configs.py` + `config/enemies.json`：`difficulty_coefficients` 块删除（工程性 config 变更，非内容填充）；`tests/test_pve_enemy.py` fixture 同步。

## 3. profile→Fighter 映射与世界 Boss profile（R3/R5，AC3/AC6）

- `build_enemy_fighter(enemy)` = **唯一 Enemy→FighterState mapper**：`managers/pve_combat_manager.py::_build_enemy_fighter` 已委托（含测试 shim 分支），catalog 与战斗管理器共用一条映射。
  - 蒙手口径 `weapon_k=0.5`/`base_damage=5` 显式（与 sim 附录 C.4 一致，原引擎 fallback 值不变）；`block_armor_value` 护甲透传；`level_index>0` 才覆盖（0=旧档缺省→保持引擎默认 1，专项组旧行为逐点一致）；`crit_rate>0` 时 /100 覆盖、否则保持默认 0.15（Step 3 定案接线）；`trigger_skills`/`ultimates` dict 复制透传。
  - 纯运行时职责：不写库、不发奖、不触平台（grep 审计确认无 db/发送调用）。
- 世界 Boss 4 只 profile：五维/招牌技/阶段 (0.60,0.20)/倍率 1.10·0.90·0.50/48h/每日 3 次/击杀 12h/消散 24h 元数据完整入档（`tests/test_enemy_catalog_runtime.py::TestFourLayerConsistency[wb_*]` 逐字段断言）；本 child 不做实例/生命周期（归 child D）。
- **AC3 验收方式**：真实只读 CSV→`/tmp` preview→catalog→profile→Enemy→Fighter 四层逐字段一致性（28 只 + 4 只参数化全矩阵，`PREVIEW_DOC` 于测试导入期由真实 CSV 现场渲染，validator 零错误）；正式 generated config 同链路复验明确留父计划 Batch 5（bd `hua`）。**未宣称固定名册启用。**

## 4. 难度只乘伤害回归与专项组兼容（AC4/AC5）

- `TestDifficultyOnlyDamage`：catalog carrier 2.5× 仅伤害变（含暴击/技能不动）；动态路径经 game_config stub + 确定性 random monkeypatch 断言 hp/armor/agility/speed/level_index 跨倍率全等、damage==max(1,int(×2.0))（config 无关不变量）。
- `TestSpecialistGroups`：`spawn_enemy_from_group` guardian_low/mid/high 按玩家等级 5/15/40 定向命中、crit 8/10/12 入 Fighter、组路径难度同样只乘伤害（同种子对照）、未知组 ValueError；秘境兽 `spawn_enemy_from_group(enemy_group_key)` 调用点不变（pve_combat_manager 兼容 shim 加载链全绿）。
- 全量既有战斗/秘境/宗门/传承测试未改动即通过（1055 passed）。

## 5. 质量门摘要（AC7）

- `uv run ruff format managers/ core/ scripts/ tests/ data/`（本 child 触及域）→ 113 files unchanged；`uv run ruff check` 同域 → **All checks passed**。
- `uv run python -m pytest tests/ -q` → **1055 passed in 7.29s**（新增 test_enemy_sync_gate 22 例 + test_enemy_catalog_runtime 56 例）。
- preview 复跑：`uv run python scripts/sync_content_to_config.py --enemies-preview-out /tmp/enemies_preview_v2.json` → `Preview rendered 28 roster + 4 world-boss profiles`；enemies.csv sha256=b558813b…（1 表头 + 31 数据行：28 名册 + 3 guardian 动态匹配行），world_bosses.csv sha256=99386e1b…（1 表头 + 4 行）。
- ⚠ 全仓 `ruff check .` 存在 70 处**既有**告警，全部位于 `.trellis/scripts/**`（用户 2026-10-11 已有未提交改动，mtime 早于本会话；本会话未触碰、`ruff format .` 亦未改写它们）。非本 child 范围，待用户自行处置。

## 6. AC 对照

| AC | 状态 | 证据 |
|---|---|---|
| AC1 | ✅ | validator 负例矩阵 + 确定性排序（golden）测试 |
| AC2 | ✅ | 正式写五类负向 fail closed；preview 不触正式 config；操作说明=本文件 §1 与 sync docstring（status=战斗闸门、narrative_status 独立） |
| AC3 | ✅（preview 链路）| 28+4 四层逐字段参数化测试；正式 config 复验→Batch 5（bd hua） |
| AC4 | ✅（代码基座+难度语义）| catalog resolver 无 exp/等级/类别/抖动派生；难度只乘伤害回归（catalog+动态双路径）；旧动态入口的**调用方退役**留 Batch 5 切流 |
| AC5 | ✅ | 守护/秘境组定向生成 + 唯一 mapper 回归测试 |
| AC6 | ✅ | WB 4 只 preview profile 完整（copy-to-snapshot 输入）；无正式 sync、无实例/DB 写入 |
| AC7 | ✅ | 全量 ruff/pytest 绿（触及域）；既有 .trellis/scripts 告警非本范围（§5 ⚠） |

## 7. 遗留 / 交接

- bd `astrbot_plugin_monixiuxian2_2-hua`：Batch 5 正式 sync 复验 + 固定名册切流（含 spawn_enemy→resolver 替换、动态路径退役、正式文档四层一致性复跑）。
- child C（历练结算）/ child D（世界 Boss 域）消费本 child 的 `EnemyCatalog` 与 `build_enemy_fighter`；child E 负责旧入口退役清单与切流闸门。
- 玩家侧 `base_crit_rate` 物化（Step 3 定案第三项）不属本 child（无消费者改动）。
- functional_tests 域检查：`grep -r difficulty_multiplier functional_tests/cases/` 零命中，无用例钉住旧难度语义；真实平台回归由用户发起（项目约定）。
