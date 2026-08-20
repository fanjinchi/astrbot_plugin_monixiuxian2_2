# Tasks: unify-sect-commands

## 1. 宗门统一入口

- [x] 1.1 在 `handlers/sect_handlers.py` 新增 `handle_sect_entry` 分发器：解析首参子命令 → 路由表分发；无参数/未知子命令输出导航帮助；缺参子命令输出各自用法示例（对照 spec「统一指令入口与子命令路由」「子命令功能覆盖」）
- [x] 1.2 路由表覆盖全部子命令：创建/加入/退出/信息/列表/捐献/任务/丹房/建设/镇派功法/晋升/宝库/师承/踢出/传位/职位/排行/贡献排行/悬赏/商店，复用现有 `SectHandlers` 各处理方法与 `RankingManager` 排行逻辑
- [x] 1.3 `main.py` 注册单一 `CMD_SECT = "宗门"` 指令路由至分发器（docstring 遵循固定格式），删除 18 个旧指令常量与路由方法（含 `CMD_RANK_SECT`/`CMD_RANK_CONTRIBUTION` 路由，常量若被白名单等他处引用则保留常量、仅删路由）

## 2. 宗门悬赏拆分

- [x] 2.1 `managers/bounty_manager.py`：`get_bounty_list` 拆出宗门视图（按玩家宗门 `sect_id` 过滤）；`accept_bounty` 加来源类型校验（全局拒宗门、宗门拒非本宗/全局）
- [x] 2.2 `check_bounty_status`/`complete_bounty`/`abandon_bounty` 对活跃悬赏做类型归属校验，跨类型拒绝并提示对方入口；`add_bounty_progress` 完成提示语按模板类型指向正确指令
- [x] 2.3 `handlers/bounty_handlers.py` 移除「🏯 宗门悬赏」分区，全局列表只呈现无 `sect_id` 悬赏；提示语更新
- [x] 2.4 `handlers/sect_handlers.py` 实现「悬赏」子命令组（查看/接取/进度/完成/放弃），无宗门玩家拒绝并提示先加入宗门（对照 spec「宗门悬赏独立入口」）
- [x] 2.5 `core/gm_manager.py` 新增 GM 子命令「清除悬赏」：确认二次确认 + 数字 ID 定位（遵循「清除CD」模式），清除目标进行中悬赏记录与 `system_config.bounty_abandon_cd_<uid>` 冷却键；GM 帮助文本同步（对照 gm-commands delta）

## 3. 宗门专属内容（秘境/商店/历练标记）

- [x] 3.1 `managers/rift_manager.py` 秘境列表渲染前按 faction_id 过滤掉非本宗的 `sect_id + access=sect_member` 秘境（移除 🔒 锁定标注分支）；准入校验 `_check_sect_access` 不动
- [x] 3.2 `config/sect_factions.json` 为默认宗门新增 `shop` 商品池配置（商品引用既有物品配置 id + `price` 贡献点 + 可选 `min_position`），`config_manager.py`/`data/default_configs.py` 同步默认值
- [x] 3.3 `managers/sect_manager.py` 实现宗门商店：列表展示（职阶门槛标注）、贡献点扣减与商品发放（事务保护）、无宗门/未配置商品池的提示
- [x] 3.4 `handlers/sect_handlers.py` 实现「商店」子命令组（查看/购买），接入分发器
- [x] 3.5 `managers/adventure_manager.py` 结算消息：事件带 `sect_id` 时前缀「🏯 宗门际遇 · {事件名}」，普通事件文案不变

## 4. 帮助与文档

- [x] 4.1 `handlers/misc_handler.py`「修仙帮助」宗门章节重写：列出新子命令对照表（含商店/悬赏），删除旧指令说明
- [x] 4.2 更新 `design_docs/current-design-report.md` §4.8（商店/秘境可见性/历练标记同步）与 `design_docs/api-overview.md` 指令索引；`README.md` 追加更新日志；`metadata.yaml` 版本号递增

## 5. 测试与验证

- [x] 5.1 更新/新增 `tests/` 单测：子命令分发（无参导航/未知子命令/缺参提示）、悬赏类型分流全交叉组合（全局接宗门悬赏拒、宗门接全局拒、跨类型状态/完成/放弃拒，含校验顺序先于冷却/活跃）、GM 清除悬赏（清记录+清冷却/无可清提示）、秘境列表过滤、宗门商店购买（贡献不足/职阶门槛/无宗门）、历练事件标记
- [x] 5.3 质量门禁：`uv run ruff format . && uv run ruff check .`，`uv run python -m pytest tests/ -v` 全绿

> 注：functional_tests 用例改写已移至配套 change `update-sect-functional-tests`，不属于本 change 范围。
