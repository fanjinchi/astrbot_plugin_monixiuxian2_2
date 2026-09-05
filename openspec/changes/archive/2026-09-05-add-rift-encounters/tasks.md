# Tasks: add-rift-encounters

## 1. 谜题引擎（纯逻辑）

- [x] 1.1 新增 `core/rift_puzzle_manager.py`：`RiftPuzzle` 数据类（family/template/question_text/answer/attempts_left）+ 谜题族注册表（按族随机抽取）+ `check()` 三态校验（正确/错误/非法输入，非法不耗次数；design D3）
- [x] 1.2 五行破阵生成器：生克映射表 + 三模板（相克破阵/轮转补缺/逆生溯源），题面嵌入生克对照碑文
- [x] 1.3 洛书数阵生成器：洛书基阵 8 种旋转/镜像 × 整体平移量变体，随机挖空一格，碑注给出目标和数
- [x] 1.4 灵龟辨窟生成器：2-3 个真假话逻辑模板（构造保证唯一解），碑铭语句与洞窟（甲/乙/丙）随机置换
- [x] 1.5 答案校验按族判定合法形式（五行字/数字/甲乙丙），尝试次数默认 2（可配置 `puzzle_attempts`）
- [x] 1.6 新增 `tests/test_rift_puzzle_manager.py`：覆盖三族生成正确性（含幻方约束满足、辨窟唯一解验证）、实例随机独立性（不缓存复用上一实例）、次数消耗、非法输入、边界（机会耗尽）

## 2. 遭遇机制、可选 PvE 与传承改造

- [x] 2.1 新增 `core/encounter_store.py`：`EncounterStore` 内存 pending 表（每玩家 puzzle/beast/legacy 各一，`expires_at` 惰性过期，同类覆盖刷新；design D1/D8）；`main.py` 装配单例并注入 RiftManager/AdventureManager（GM 经 `rift_mgr.force_*` 触达，不改 GMManager 构造函数）
- [x] 2.2 `finish_exploration` 删除自动 `trigger_pve_combat` 调用，基础奖励不再被战斗修改；结算后追加 `_roll_encounters()` 独立判定谜题/妖兽遭遇（顶层 `puzzle_rate`/`beast_rate` 默认，条目 `encounter_rate` 覆盖；design D4/D5）
- [x] 2.3 `managers/pve_combat_manager.py`：新增 `challenge_rift_beast(player, enemy_group_key)`——只负责战斗并返回（胜负/战报/敌人修为），有组 key 走 `spawn_enemy_from_group`，无则回落 `spawn_enemy`；**胜负判定显式比较 `result.winner == player.user_id`，禁止 `enemy_` 前缀判定**（定向组敌人是 `guardian_` 前缀，design D5）
- [x] 2.4 `managers/rift_manager.py`：先把 `finish_exploration:389-413` 的掉落入库块抽为 `_store_dropped_items(player, dropped_items)`（结算/破阵/迎战三处复用）；实现响应逻辑 `answer_puzzle`（答对掉落 roll 入库 + 修为基数×0.2；design D6）、`accept_beast_challenge`（胜=敌人修为+掉落 roll 入库且返回 `pve_won=True`，负或平局视同失败 hp=1 且机缘消耗；design D5）、`accept_legacy_challenge`（复用 `challenge_legacy_guardian`，平局视同失败，胜利按 pending 的 legacy_type 建传承实例；design D8）；无 pending/过期/热重载丢失 → "机缘已消散"提示
- [x] 2.5 秘境传承触发改挂起：`finish_exploration` 移除内联守护挑战（`:415-448`），命中 `legacy_chance` → pend 来源 `rift` 的 legacy 遭遇，结算消息提示 `/探索秘境 传承`
- [x] 2.6 历练传承同构改造：`adventure_manager._maybe_trigger_legacy`（`:359`）改为 pend 来源 `adventure` 的 legacy 遭遇，保留现有 try/except 异常降级（不中断历练结算）
- [x] 2.7 `data/default_configs.py` 的 `RIFT_CONFIG` 增加 `puzzle_rate`/`beast_rate`/`encounter_ttl_seconds`/`puzzle_attempts` 默认值与字段说明注释；**读取处按 `explore_events` 先例回落默认值**（存量配置文件不会被合并新键，design D4）

## 3. 指令入口

- [x] 3.1 `handlers/rift_handlers.py`：`handle_rift_explore` 改为子命令分发（数字→进入秘境；`破阵 <答案>`→作答；`破阵` 无答案→用法提示不耗次数；`传承`→应邀挑战；其他→用法提示；design D2）；**`迎战` 例外：不经 handler，见 3.2**
- [x] 3.2 `main.py`：`handle_rift_explore` 签名改为 `(event, action: str = "", value: str = "")`，docstring 按固定格式更新；**迎战分支直调 `rift_mgr.accept_beast_challenge`**（不经 rift_handlers 的 yield 字符串，与 `handle_rift_complete` 直调 `finish_exploration` 模式一致），随后消费 `pve_won` 调 `sect_mgr.advance_master_progress(user_id, "win_pve")`（复用 `main.py:1213-1223` try/except 模式）；`handlers/misc_handler.py` 的 `/修仙帮助` 文本加入新用法

## 4. GM 强制触发

- [x] 4.1 `core/gm_manager.py` + `handlers/gm_handler.py`：新增 `触发秘境谜题 [目标]`、`触发秘境妖兽 [目标]`、`触发秘境传承 [目标]` 子命令，目标解析复用既有优先级（@提及 > ID > 本人）但须 **`single_token_is_target=True`**（参照 `cmd_give_legacy`，`core/gm_manager.py:439-441`；防止单数字 token 被当数值参数回落发送者），调用 `rift_mgr.force_puzzle_encounter/force_beast_encounter/force_legacy_encounter`；GM 强触缺省上下文：谜题修为基数取秘境 1 级 `exp_range` 生成、妖兽 `rift_level=1`+`enemy_group=None`、传承 `legacy_type="rift"`（design D4/D8）
- [x] 4.2 更新 GM 帮助文本（`修仙GM帮助` 输出）包含三个新子命令

## 5. 测试秘境脚手架（验证后拆除）

- [x] 5.1 `data/migration.py` **双播种**：`_create_all_tables` 的 `default_rifts` 加 id 7「试炼古境」行（覆盖全新安装/重建库）+ 新增 `MIGRATION_TASKS` 版本任务 `INSERT OR IGNORE` 同一行（覆盖存量 v32 库升级；design D7）
- [x] 5.2 `config/rift_config.json` + `data/default_configs.py`：新增 id 7 条目，`enemy_group: "rift_test"`、`encounter_rate: 1.0`
- [x] 5.3 `config/enemies.json`：新增 `rift_test` 组（无 `level_range`，1-2 个石傀儡模板，低倍率）+ `data/default_configs.py` 敌人默认配置同步

## 6. 测试与质量门

- [x] 6.1 新增/更新 `tests/`：遭遇判定（含不互斥同时触发、覆盖刷新、过期）、可选 PvE 三结果分支（含定向组 `guardian_` 前缀敌人的胜负判定回归）、传承遭遇流转（挂起→应邀胜利获传承/失败消耗/平局消耗/无视消散）、子命令分发解析（含破阵无答案）、GM 强制触发；**改写 `tests/test_rift_adventure_narrative.py:288-334` 两个传承内联挑战断言为应邀制**
- [x] 6.2 `functional_tests/cases/` 新增秘境遭遇域用例（GM 强制触发 → 破阵/迎战/传承 → 断言奖励与零惩罚；前提：测试实例需将测试号配置进 GM_ADMINS）
- [x] 6.3 `uv run python -m pytest tests/ -v` 全绿 + `uv run ruff format . && uv run ruff check .` 通过

## 7. 文档与版本

- [x] 7.1 按 §14 同步 `design_docs/current-design-report.md`（秘境 PvE 强制→可选、奖励切割、遭遇机制、传承挑战应邀制、师承 win_pve 来源变化）及相关资料，新资料登记 `design_docs/README.md`
- [x] 7.2 `metadata.yaml` 版本号 + `README.md` 更新日志
- [x] 7.3 `design_docs/api-overview.md` 更新（新模块与新子命令路由）

## 8. 收尾（用户验证通过后执行）

- [x] 8.1 用户在测试平台验证完毕 → 拆除测试脚手架：删 rift_config id 7 条目、enemies.json `rift_test` 组、移除双播种（`default_rifts` 种子行 + 对应迁移任务），新增删除 rifts 表 id 7 行的迁移版本
- [ ] 8.2 正式秘境怪物生态配置立项（走 §15 design_docs 内容管线，另行提案）
