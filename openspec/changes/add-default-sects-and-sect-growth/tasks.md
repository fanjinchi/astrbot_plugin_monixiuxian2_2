# Tasks: add-default-sects-and-sect-growth

## 1. 数据库迁移与模型

- [ ] 1.1 `data/migration.py` 新增迁移版本：`sects` 加列 `is_system`(默认0)/`faction_id`(可空)/`status`(默认 normal)/`destruction_tier`(可空)；`player_skills` 加列 `origin_sect_id`(可空)/`sect_bound`(默认0)
- [ ] 1.2 同步 `models_extended.py`（Sect 模型新字段）与功法记录模型；确认存量数据默认值零行为变化

## 2. 配置层

- [ ] 2.1 `data/default_configs.py` 新增 `SECT_FACTIONS`（2 个示例默认宗门：正派学院风 + 风格迥异乡，含 elders/建筑物/destruction 结构）与 `SECT_TASKS`（建设任务池 + 师承任务链示例）默认值
- [ ] 2.2 `config_manager.py` 注册加载 `sect_factions.json`、`sect_tasks.json`，并做结构校验（必填字段、引用的功法/心法/物品 id 存在性），启动日志报警
- [ ] 2.3 扩展 `config/sect_config.json`：positions 增加 `promotion`/`benefits`；接线 `scale_ratio`（移除 `sect_manager.py:229`、`database_extended.py:148` 硬编码）
- [ ] 2.4 扩展现有内容配置的可选字段（不改现有条目行为）：`skills.json` 新增宗门功法池示例、`heart_methods.json`/`weapons.json` 增加 `sect_id`/`sect_bound`/`treasure`/`min_position` 示例条目、`bounty_templates.json`/`rift_config.json`/`adventure_config.json` 增加 `sect_id` 示例

## 3. 默认宗门播种与出入宗门

- [ ] 3.1 `managers/sect_manager.py` 新增 `ensure_system_sects()` 幂等 upsert 播种，`main.py` 初始化时调用；默认宗门名加入建宗禁用名校验
- [ ] 3.2 「加入宗门」改造为统一入口：按 `is_system` 分流（默认宗门校验 `join_level_range`，玩家宗门走现有逻辑）
- [ ] 3.3 离宗回收钩子：收拢「退出宗门/踢出成员/弃道重修」三路径，回收 `treasure` 宝物归还宗门；`sect_bound` 功法/心法离宗保留可用（不回收不封印）；储物戒赠予/交易路径拒绝一切宗门绑定物
- [ ] 3.4 合并两套职位权限定义：删除 `sect_manager.py` 硬编码 `POSITION_PERMISSIONS`，权限判断统一读 `sect_config.json`

## 4. 宗门建设机制

- [ ] 4.1 接线 `sect_fairyland`：洞天等级按配置为全体成员提供闭关修为加成（`core/cultivation_manager.py` 结算点读取）
- [ ] 4.2 接线 `elixir_room_level` + `sect_elixir_get`：丹房按等级解锁丹药领取，日重置（接线 `reset_sect_elixir_get()` 调用点）
- [ ] 4.3 接线 `mainbuff/secbuff` 镇派功法位：镶嵌与全员被动生效
- [ ] 4.4 建筑升级指令与消耗校验（资材+建设度），建设任务池（`sect_tasks.json` construction_tasks）结算贡献与资材

## 5. 师承任务链

- [ ] 5.1 任务链匹配与进度存储（玩家 JSON：当前链 id+阶段+计数），按境界段匹配
- [ ] 5.2 阶段目标行为计数挂钩（PvE 胜场/历练完成/突破成功/捐献，复用悬赏式挂钩点）
- [ ] 5.3 阶段结算与奖励发放（贡献/修为/宗门功法领悟机会），长老署名文案展示；新指令路由与帮助文本

## 6. 职阶晋升与福利

- [ ] 6.1 「宗门晋升」指令：双门槛校验（贡献+境界），默认宗门无宗主通道，玩家宗门保留任命/传位
- [ ] 6.2 福利接线：每日灵石并入「签到」加发；`core/shop_manager.py` 结算读职阶折扣；传承解锁资格校验（`benefits.unlocks` / `min_position`）

## 7. 内容联动过滤

- [ ] 7.1 悬赏：`bounty_manager.py` 榜单查询与接取校验按 `sect_id` 过滤
- [ ] 7.2 秘境：`rift_manager.py` 准入校验 `sect_member`
- [ ] 7.3 历练：`adventure_manager.py` 事件组抽取按玩家宗门过滤
- [ ] 7.4 功法池注入：`core/skill_manager.py` 领悟池组装点按玩家宗门注入专属池，获得时打归属标记

## 8. 测试与文档

- [ ] 8.1 单元测试：播种幂等、拜入境界校验、离宗宝物回收三路径与功法保留可用、晋升双门槛、洞天/丹房加成、建设任务结算、绑定物禁赠（`tests/test_sect_*.py`，用 `tests/helpers.py` load_module）
- [ ] 8.2 `uv run ruff format . && uv run ruff check .` + `uv run python -m pytest tests/ -v` 全绿
- [ ] 8.3 文档同步：`design_docs/current-design-report.md` §4.8 重写、`api-overview.md`、`project-architecture.md`、`README.md` 更新日志、`metadata.yaml` 版本 bump、`handlers/misc_handler.py` 帮助文本
- [ ] 8.4 功能测试用例由配套 change `add-sect-functional-tests` 覆盖（其他 agent 实施），本 change 仅保证用例所需的指令链路可用
