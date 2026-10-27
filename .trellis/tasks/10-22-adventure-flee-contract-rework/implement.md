# Implement — 逃跑契约重拍落地

对应：`prd.md` / `design.md`。执行顺序如下，每步验证通过再进下一步。测试影响面清单以 design.md §5/§6 的实扫定稿为准（16 条 pytest + 3 条 functional）。

## 前置

- [ ] 0. 读 `.trellis/spec/backend/` 相关 index（trellis-before-dev）；确认工作树干净或已知的无关改动不冲突。

## Step 1 — 触发范围（R1 / AC1）

- [ ] 1.1 `_offers_choice` 去 `HIGH_RISK_LEVELS` 闸门，改判 `flee.enabled` + snapshot combat 存在性（**承重判定，docstring 写明未遇敌直通靠它**，design.md §2-D1）；删除 `HIGH_RISK_LEVELS` 常量；同步该方法 docstring。
- [ ] 1.2 pytest 先红后绿：补低/中风险遇敌挂 `pending_choice` 正向用例；`test_kill_switch_skips_pending_entirely` 补 LOW 段；`test_low_risk_finish_settles_win_without_pending` 改名/改 docstring 为「未遇敌直通」口径。
- [ ] 1.3 处理 design.md §6 表里 14 条 LOW_ROUTE 翻红用例（:488/:537/:879 前半/:897/:909 前半/:925/:1101/:1151/:1233/:1257/:1287/:1495/:1538/:1605）——逐条选 (a) 关触发保未遇敌原意 或 (b) 补一步 resolve_adventure_choice 落终态；`test_concurrent_finish_cas_is_exactly_two` 前提失效需重写。
- [ ] 1.4 修 `tests/test_sect_content_link.py::test_adventure_settlement_marks_sect_event`：monkeypatch `_should_trigger_combat` 为 False。
- [ ] 1.5 验证：`uv run python -m pytest tests/test_adventure_settlement_state_machine.py tests/test_sect_content_link.py -v`

## Step 2 — 收益收紧与传承门控（R2 / R3 / AC2 / AC3）

- [ ] 2.1 新增 `FLED_REWARD_RATIO = 0.3` 常量（注释引 §Q4）与 `_fled_rewards(snapshot)` helper（exp/gold 均 int 截断；注释写明败场灵石是归零、逃跑更宽是 §Q4 原意，design.md §2-D2）。
- [ ] 2.2 `resolve_adventure_choice` fled 分支与 `_replay_terminal` fled 分支改用 `_fled_rewards`。
- [ ] 2.3 `_grant_route_drops` 加 fled 跳过（claim 照记）；`_grant_legacy_trigger` 改为仅 `resolved_win` 执行；`_grant_effects` 传入终态；三处 docstring 同步新契约。
- [ ] 2.4 pytest：改 `test_flee_success_records_fled_without_hp_loss` 的全额断言为 int(1000×0.3)=300 + 无掉落/传承（现存唯一钉 fled 全额的断言；实扫确认没有钉 fled 掉落/传承、loss 传承的旧断言）；新补反向用例：fled/loss 三 claim 全记录但本体未执行（储物戒与传承表无变化）、win 传承不变。
- [ ] 2.5 验证：同 1.5，两文件绿。

## Step 3 — 文案（R4 / AC4，共 4 处 + 注释清理）

- [ ] 3.1 `_render_pending` 逃跑条目补代价说明；fled `combat_msg` 改「白跑大半」口径（文案以 design.md §4 为草案，用户审定稿）。
- [ ] 3.2 `handlers/adventure_handlers.py:32`（历练信息）与 `handlers/misc_handler.py:144`（修仙帮助）去掉「仅高/极高风险」限定，同步全段口径。
- [ ] 3.3 注释清理（R5）：`DEFAULT_FLEE_PARAMS` 头注（:127-129）、`adventure_manager.py:325/:334` 日志警告「临时默认系数」、`data/default_configs.py:596-597` 注释，全部改封板口径；扫本文件其它首版契约表述（:577-580、:1571 等）；`main.py:1509` 注释「基础收益照常发放」同步。

## Step 4 — functional_tests sect 适配（R6 / AC6，3 条用例）

- [ ] 4.1 `sect-bounty-lifecycle.json`（4 循环）与 `sect-adventure-event-marker.json`（3 循环）：「GM 触发历练结算」步 match 放宽为 `已强制结算|未能不战而结`；每循环后插 GM「强制历练迎战」步，match 容纳 `没有等待应战的历练遭遇` 与 `已代【…】应战并结算历练` 双分支（正则同时容 🚶 历练归来/💥 历练受挫两头）；终局断言不变。注意这两条是 deterministic+seed 42，遇敌分支是确定性的，改完要在两种种子走向下都核一遍正则。
- [ ] 4.2 `sect-master-chain-gm.json`：同样双分支改造；「师承任务【采药历练】完成！」断言从 GM 结算步**移位**到收敛点（加一步 `#宗门 师承` 面板查询断【破境之礼】解锁）。
- [ ] 4.3 `uv run python scripts/test_suite_ctl.py sync-cases` 同步到平台目录（命令与 functional_tests/README.md 一致）；真实平台回归由用户发起，不自动跑。

## Step 5 — 文档同步（R7 / AC7）

- [ ] 5.1 父 PRD `10-10-pve-enemy-world-boss-redesign/prd.md` 第 51、118 行改重拍口径并标注「2026-10-19 重拍，见 §Q4」；子任务地图补记本 child。
- [ ] 5.2 grep `design_docs/` 与 `README.md` 首版契约残留（已知点：`README.md:138-139` 指令表、`design_docs/current-design-report.md` 待核），有则同步。

## Step 6 — 质量门与收尾（AC5 / AC8）

- [ ] 6.1 `uv run ruff format . && uv run ruff check .`
- [ ] 6.2 `uv run python -m pytest tests/ -v` 全量绿
- [ ] 6.3 `git diff config/adventure_config.json data/default_configs.py` 只许注释修正、不许数值/键变化（AC8）
- [ ] 6.4 trellis-check；bd `-w07` 关闭（reason 引交付摘要）；`-2v2` 因 blocks 解除自动回 ready
- [ ] 6.5 版本 checklist：metadata.yaml version、README 更新日志（追加）；修仙帮助文本已在 3.2 覆盖；commit 由用户确认后执行

## Review gates

- Step 2 后：自查 claim 表语义未破（`_effects_complete` 对 fled/loss 仍能为真）。
- Step 4 后：自查三条 sect 用例双分支正则与平台 `loader.validate_case` 兼容，且每个 send 仍只配一个断言。
- 全部完成后：trellis-check + 按 AGENTS.md 会话收尾。

## Rollback

单提交 revert 即回首版契约；无 schema/config 数值变更，无数据迁移。
