## 1. Close bd `dhh` — 功法预算审计

- [x] 1.1 运行 `uv run python design_docs/content-design/validate_budget.py`，确认 0 FAIL。
- [x] 1.2 运行 `uv run python scripts/sync_content_to_config.py --dry-run`，确认 skills 无异常删除/写入。
- [x] 1.3 通过 grep 确认 `config/skills.json` 中不存在「御剑术」「开天辟地」等旧超预算功法，且 `万剑归宗` 的 `effect_value ≤ 2.0`。
- [x] 1.4 在 bd 中关闭 `astrbot_plugin_monixiuxian2_2-dhh`，close reason 引用本次审计结果。

## 2. 心法配置增加 `route_multiplier`（工作区已实现，验证即可）

- [x] 2.1 `design_docs/content-design/heart_methods.csv` 已含 `route_mult_ling` / `route_mult_ti` 列，v1 池 18 个心法全部 1.0。
- [x] 2.2 `config/heart_methods.json` 每个心法条目已含 `route_multiplier: {"灵修": 1.0, "体修": 1.0}`。
- [x] 2.3 `design_docs/content-design/README.md` 已更新列约定。
- [x] 2.4 更新 `design_docs/content-design/heart-methods.md`，补充心法 `route_multiplier` 机制说明（v1 池全 1.0，语义与 `route` 装备校验区分）。

## 3. 同步脚本扩展（工作区已实现，验证即可）

- [x] 3.1 `scripts/sync_content_to_config.py` 的 `_build_heart` 已解析 `route_mult_ling` / `route_mult_ti` 并写入 `route_multiplier`。
- [x] 3.2 运行 `uv run python scripts/sync_content_to_config.py`，验证 `config/heart_methods.json` 被正确重写且字段完整。
- [x] 3.3 运行 dry-run 验证 legacy/draft/final 语义未变。

## 4. 属性计算接入心法路线倍率（工作区已实现，验证即可）

- [x] 4.1 `models.py` `Player.get_total_attributes` 已在 `item_type == "main_technique"` 分支读取 `item.get_route_multiplier(self.cultivation_type)`。
- [x] 4.2 百分比被动（`hp_percent` / `damage_percent` / `agility_percent` / `speed_percent`）已按 `value * route_mult` 生效。
- [x] 4.3 `armor_value` 平加项已按 `int(value * route_mult)` 后累加。
- [x] 4.4 未声明 `route_multiplier` 时走 `Item.get_route_multiplier` 的 1.0 缺省。

## 5. 测试

- [x] 5.1 在 `tests/test_models.py` 或新增测试文件中验证：灵修/体修玩家装备同一路线倍率为 1.0 的心法，属性计算与旧逻辑一致。
- [x] 5.2 新增测试：构造 `route_multiplier.体修 = 1.2` 的心法，验证体修玩家 `damage_percent` / `armor_value` 被正确放大。
- [x] 5.3 新增测试：未声明 `route_multiplier` 的心法按 1.0 处理，不报错。
- [x] 5.4 在 `tests/test_content_design_apply.py` 中新增测试：heart_methods CSV 的 `route_mult_ling` / `route_mult_ti` 经 `_build_heart` 正确写入 JSON 的 `route_multiplier` 字段。
- [x] 5.5 运行 `uv run python -m pytest tests/ -v`，全量通过。

## 6. 质量门与 bd 收尾

- [x] 6.1 运行 `uv run ruff format . && uv run ruff check .`，无错误。
- [x] 6.2 运行 `uv run python -m pytest tests/ -v`，全部 green。
- [x] 6.3 在 bd 中关闭 `astrbot_plugin_monixiuxian2_2-f4t`，close reason 引用本次实现。
