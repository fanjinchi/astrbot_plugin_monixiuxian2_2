# Tasks — equip-from-learned-skills-and-transfer

> 总跟踪：bd（本 change 落地后开 issue）；验收标准见 `specs/skill-system/spec.md`。

## 实现

- [ ] 1. `core/skill_manager.py`：`skill_tome` 配置读取（enabled/cost_lingshi/cooldown）；
      `create_skill_tome(player, skill_name)`：解析技能名 → 校验已领悟 → 校验消耗/冷却
      → 生成同名秘籍入储物戒（复用 StorageRingManager.store_item，事务内扣灵石/记冷却）
- [ ] 2. `handlers/technique_handler.py`：
      - `CMD_CREATE_SKILL_TOME = "功法成册"` + handler（@player_required）
      - 修正 `handle_activate_technique` 未领悟提示语（去除"功法物品"引导）
- [ ] 3. `main.py`：注册 `功法成册` 指令（+ `require_whitelist`）；帮助文本
      （`handlers/misc_handler.py` `/修仙帮助` 功法段）
- [ ] 4. `config/game_config.json`：`skill_system.skill_tome` 默认配置；
      `data/default_configs.py` 同步；`_conf_schema.json` 如需暴露动态配置
- [ ] 5. `config/items.json`：4001-4010 十件功法物品处理——与技能名对齐项保留为
      静态秘籍；其余标 `legacy` 并从 `shop_weight` 移除（方案见 design.md §4）
- [ ] 6. 测试 `tests/test_skill_tome.py`：成册成功/未领悟拒绝/灵石扣减/冷却；
      转交后源玩家仍可装备且 loadout 含功法；接收方秘籍可设修习目标；
      储物戒秘籍不构成装备资格（spec Scenario）
- [ ] 7. 文档同步（AGENTS.md §14）：`current-design-report.md` 技能系统段、
      `project-architecture.md` 子系统表、`content-design/README.md`（如需）

## 收尾

- [ ] 8. `uv run ruff format . && uv run ruff check .`；`uv run python -m pytest tests/ -v`
- [ ] 9. 归档 change：`openspec archive`（同步 delta specs → 主 specs），
      bd 关闭/关联（hz7 内容池、tt3 效果引擎不受影响）
