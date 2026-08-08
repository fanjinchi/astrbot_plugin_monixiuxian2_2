# Tasks — equip-from-learned-skills

> 总跟踪：bd（本 change 落地后开 issue）；验收标准见 `specs/skill-system/spec.md`。

## 实现

- [ ] 1. `handlers/technique_handler.py`：修正 `handle_activate_technique` 未领悟提示语
      （删除"功法物品"引导，改为"需拥有秘籍并设为修习目标 / 闭关突破领悟"）；
      （可选）`handle_set_study_target` 未拥有提示补充获取途径
- [ ] 2. `config/items.json`：4001-4010 十件功法物品处理——与技能名对齐项保留为静态
      秘籍；其余标 `legacy` 并从 `shop_weight` 移除（方案见 design.md §2）
- [ ] 3. `core/skill_manager.py`（如需要）：`_find_skill_id_by_name` 增加物品名→技能名
      回退映射（对齐后物品名即技能名时已天然匹配）
- [ ] 4. 测试：未领悟不可激活（提示修正）；储物戒秘籍可设修习目标（对齐后）；
      无凭据设修习目标拒绝；转交后接收方可设修习目标、源玩家仍可装备且
      loadout 含该功法（spec Scenario）
- [ ] 5. 文档同步（AGENTS.md §14）：`current-design-report.md` 技能系统段、
      `project-architecture.md` 子系统表（装备=已领悟表唯一依据；秘籍=领悟凭据）

## 收尾

- [ ] 6. `uv run ruff format . && uv run ruff check .`；`uv run python -m pytest tests/ -v`
- [ ] 7. 归档 change：`openspec archive`（同步 delta specs → 主 specs），
      bd 关闭/关联（hz7 内容池、tt3 效果引擎不受影响）
