# Tasks: cleanup-legacy-fields-and-docs

## 1. 装备遗留字段固化迁移（bd-gxo）

- [x] 1.1 编写一次性固化脚本：对 `config/weapons.json` 全部词条计算 `damage = max(现有 damage, physical_damage + magic_damage)`、`armor_value = max(现有 armor_value, physical_defense + magic_defense)`，写入显式键后删除 `physical_damage`/`magic_damage`/`physical_defense`/`magic_defense`/`mental_power` 五个遗留键
- [x] 1.2 脚本内置零变化校验：迁移前后用同一解析逻辑输出全部词条的 `(damage, armor_value, agility, speed, hp)` 五元组 diff，diff 非空则中止不写入；保留校验输出供审查
- [x] 1.3 全量 `rg` 断言：确认 19 个 config JSON 中不再有任何遗留五维键（`equip_effects` 与丹药效果键除外）

## 2. 代码清理（bd-gxo）

- [x] 2.1 删除 `core/equipment_manager.py`（约 103-111 行）的五维回退映射，保留 `equip_effects` 法器映射
- [x] 2.2 删除 `managers/combat_manager.py`（约 309-318 行）的同款五维回退
- [x] 2.3 删除 `core/shop_manager.py`（约 554-561 行）的同款五维回退
- [x] 2.4 删除 `managers/pve_combat_manager.py` 的死代码函数 `calculate_equipment_atk_bonus`/`calculate_equipment_defense`
- [x] 2.5 删除 `tests/test_pve_combat.py` 中对这两个死函数的引用与测试用例

## 3. level_up_rate 接入突破计算（bd-nec）

- [x] 3.1 修改 `core/breakthrough_manager.py:calculate_breakthrough_success_rate`：`final_rate = base + player.level_up_rate/100 + temp_bonus`，破境丹 cap 与连败保底逻辑不变；信息行仅在 >0 时输出"永久加成：+X%"
- [x] 3.2 修改 `handlers/player_handler.py:180`：仅在 `level_up_rate > 0` 时显示"突破成功率+X%"项
- [x] 3.3 在 `models.py` 的 `level_up_rate` 字段注释中说明语义（整数百分点永久加成，当前无产出途径）
- [x] 3.4 新增/更新突破成功率测试：覆盖 `level_up_rate=0` 零变化、>0 参与计算且受丹药 cap 钳制两个 scenario

## 4. 过时文档修正（bd-iae / bd-rau）

- [x] 4.1 重写 `design_docs/current-design-report.md`，内容对照当前代码：CombatEngine 四属性（damage/agility/speed/hp）、Muxxu 公式、减法护甲、99 级十境界、新 Player 模型
- [x] 4.2 在 `design_docs/level-exp-curve/exp-curve-report.md` 的旧失败惩罚（10% 总修为）与旧双修漏洞分析段落加注"历史背景：v3.7.0 已修复"标记

## 5. 回归验证与版本联动

- [x] 5.1 运行 `uv run ruff format . && uv run ruff check .` 无错误
- [x] 5.2 运行 `timeout 120 uv run python -m pytest tests/ -q` 全绿（注意使用 tests/helpers.py 的 load_module 模式）
- [x] 5.3 更新 `metadata.yaml` 版本号、`README.md` 更新日志（末尾追加），按需同步 `handlers/misc_handler.py` 修仙帮助文本
- [ ] 5.4 关闭 bd issue：gxo、nec、iae、rau（附本变更提交引用）
- [ ] 5.5 `git pull --rebase && git push`，确认 `git status` 显示 up to date
