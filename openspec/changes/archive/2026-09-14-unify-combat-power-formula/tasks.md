# Tasks — unify-combat-power-formula

## 1. 核心重构（models.py + 两处调用点）

- [x] 1.1 `models.py` 在 `Player.get_total_attributes`（:258-347，文件末尾）之后新增 `combat_power(self, equipped_items, pill_multipliers=None) -> int`：内部调用 `self.get_total_attributes(equipped_items, pill_multipliers)` 并返回 `damage + agility + speed + hp + armor_value//2`（逐项 `int()`，与两处现状逐位一致）；英文 Google 风格 docstring，注明含装备/心法、可选含临时丹药倍率、`block_armor_value`（格挡来源）不计入
- [x] 1.2 `managers/ranking_manager.py:125-132`：删内联五元求和，改为局部变量 `power = player.combat_power(equipped_items, None)`（与下游解包名一致）；`:122`「排行榜不含临时丹药」注释语义保留为调用处行内注释；**`:123` 的 `total_attrs` 语句不可删**（`:133`/`:144` 展示 `attrs["damage"]` 等仍依赖）
- [x] 1.3 `handlers/player_handler.py:187-194`：删内联五元求和，改为 `player.combat_power(equipped_items, pill_multipliers)`；核对 `equipped_items` 获取与异常分支逻辑保持原样；**`:185` 的 `total_attrs` 语句不可删**（`:260-264` 四主属性展示仍依赖）

## 2. 测试

- [x] 2.1 `tests/test_models.py` 新增战力测试（复用该文件既有 `load_package_module("models.py", ...)` 导入）：固定属性 `Player`（含天生护甲），断言（a）`combat_power` = 四主属性之和 + `armor_value//2`（钉取整）；（b）`pill_multipliers={"damage": 2.0}` 分支结果变化；（c）`block_armor_value` 不影响战力
- [x] 2.2 `uv run python -m pytest tests/ -v` 全绿；`uv run ruff format . && uv run ruff check .` 通过

## 3. 文档同步

- [x] 3.1 `AGENTS.md:127` 整行（含「已在 `ranking_manager.py` 和 `combat_manager.py` 中统一」错误声称）改为指针式约定：战力公式单一实现在 `Player.combat_power`（models.py），设计权威与公式文本见 `design_docs/current-design-report.md`，不再内联公式文本
- [x] 3.2 `README.md:799`/`:830` 历史 changelog BUG 修复表（v2.9.3 / v2.9.2，非"已知问题表"）的过时旧公式行**加注记**（如"（注：该公式已废弃，现状见 design_docs/current-design-report.md）"），不改写历史记录本身；实际缺陷文本为「物伤+法伤+物防+法防+精神力/10」——「物防+法防」对重复出现两次
- [x] 3.3 `design_docs/current-design-report.md:214` 的「战力公式（ranking_manager.py:125-126）」引用改指 `models.py` `Player.combat_power`；**同行修正括注**——原文「（含装备，不含临时丹药；玩家信息与排行榜同公式）」不准确：面板传 `pill_multipliers`（含临时丹药）、排行榜传 `None`，改为如实表述两调用点差异；`design_docs/api-overview.md:91`「战力公式权威实现」表述同步改指；`current-design-report.md:455` 与 `design_docs/project-architecture.md:85` 仅含公式文本无实现引用，核对无误即可

## 4. 收尾

- [x] 4.1 验证：面板（含临时丹药路径）与排行榜（不含）文本快照/数值比对与改造前一致；**比对覆盖排行顺序**（排序键与并列稳定性），不只显示数值
- [x] 4.2 按 AGENTS.md §7 版本 checklist 评估（纯重构无玩法变化，通常无需升版本号；若有遗漏则补）
- [x] 4.3 用 `bd` 为 Non-Goal 登记跟进 issue：创角文案遗留「精神力」展示文本（`handlers/player_handler.py:109,117` 旧五维文案清理）
- [x] 4.4 `openspec validate --change unify-combat-power-formula` 通过；本地 conventional commit
