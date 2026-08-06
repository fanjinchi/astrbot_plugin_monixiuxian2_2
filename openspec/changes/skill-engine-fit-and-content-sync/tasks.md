# Tasks: skill-engine-fit-and-content-sync

## 1. 键名统一（A3，bd: lvb）

- [x] 1.1 config/skills.json：全部 trigger_skill 与 ultimate 的 `effect` 键改名为 `effect_type`（6 个功法）
- [x] 1.2 设计表迁移：design_docs/content-design/skills.csv、weapon-skills.md 示例、weapons.csv 的 trigger_skills_json 中 `effect`→`effect_type`
- [x] 1.3 tests/ 中所有构造技能 dict 的 fixture 统一为引擎键（trigger_timing/effect_type/trigger_rate/effect_value）
- [x] 1.4 验证：`timeout 120 uv run python -m pytest tests/ -q` 全绿

## 2. 效果注册表重构（bd: 711，与 §1 同 PR）

- [x] 2.1 managers/combat_manager.py：`_process_trigger_skills` 的 if/elif 分支平移为 `EFFECT_HANDLERS` 注册表（damage_bonus/combo/stun/counter/damage_reduction 五个 handler，签名 `(attacker, defender, skill, state) -> float`）
- [x] 2.2 派发改查表：未知 `effect_type` 记 `logger.warning` 并跳过，不中断战斗
- [x] 2.3 FighterState 新增 `battle_flags: dict` 字段（通用战斗内状态容器，本 change 仅定义容器）
- [x] 2.4 验证：现有 combat 测试全绿 + 新增未知 effect_type 告警用例

## 3. 大招必放制 + 战况解锁门槛（bd: iup，C 方案）

- [x] 3.1 core/skill_manager.py `_apply_star_to_def`：归一化时为 ultimate 注入默认 `trigger_rate = 1.0`（引擎不加默认逻辑）
- [x] 3.2 FighterState 新增自身行动计数；combat_manager 大招循环前加解锁判定：`min_action_index` + 可选 `trigger_self_hp_below` / `trigger_opponent_hp_below`（AND 语义，未解锁跳过且不消耗限次）
- [x] 3.3 config/skills.json：万剑归宗加 `min_action_index`+`trigger_opponent_hp_below: 0.4`（斩杀型），开天辟地加 `min_action_index`+`trigger_self_hp_below: 0.5`（逆袭型）
- [x] 3.4 验证：开局 N 动内不放、达阈值后必放、每场一次、多功法独立，各一条测试

## 4. 升星机制重做（bd: plt）

- [x] 4.1 data/database_extended.py `learn_or_star_up`：`MAX_STAR = 3`（读 config），满星返回标志位不再 +1
- [x] 4.2 core/skill_manager.py：`STAR_UP_RATE_BONUS`/`STAR_UP_EFFECT_BONUS` 合并为 `STAR_UP_BONUS = 0.10`（config 可调），rate/value 均按 `(1+b)^(star-1)` 乘法缩放，rate 截断 1.0
- [x] 4.3 满星重复参悟 → 修为补偿：品级修为基数表 × 折算比例（初值 50%）写入 config，调用处发补偿并生成玩家可见提示文案
- [x] 4.4 验证：3 星后星级不变、补偿修为到账、乘法幅度 1.21× 各一条测试

## 5. config→引擎契约测试（bd: arx）

- [x] 5.1 新增契约测试：config/skills.json 真数据 → `_apply_star_to_def` → `get_battle_loadout`，断言每个 trigger/ultimate 具备引擎可读键（effect_type/trigger_timing/trigger_rate≥0）
- [x] 5.2 契约测试：万剑归宗/开天辟地经真实路径后在战斗中可触发（修复前红灯、修复后绿灯）
- [x] 5.3 scripts/sim_balance_regression.py（或新增 sim 入口）改走生产 loadout + 引擎路径，禁止测试内重实现结算逻辑

## 6. CSV→config 转换脚本（bd: riw）

- [x] 6.1 scripts/sync_content_to_config.py：读 weapons.csv/heart_methods.csv（skills.csv 同步按 D8 范围调整推迟，脚本 docstring 已注明），name 键控 merge（同名更新/新名新增/表外不动）
- [x] 6.2 status 过滤（仅 draft/final）+ `bonus_damage→damage` 键名映射 + 引擎键契约校验（trigger 四键齐全、trigger_timing 词表、rate 值域；passive_bonus 五键词表校验防静默忽略；ultimate 校验随 skills 同步一并落地）
- [x] 6.3 写盘前调用 validate_budget.py，FAIL 中止不写盘；--dry-run 输出变更摘要
- [x] 6.4 用本脚本把武器 v1（9 标杆件+狼牙棒）与心法 v1（17 draft）入库，diff 审查后生效（养气诀 id 从 heart_002 改为 heart_004 避开与焚天诀冲突；test_equipment_manager 烤死的青铜剑旧数值断言已随标杆件重做更新）

## 7. 配平 — 移出本 change（2026-08-06 m00291 用户拍板）

不配平：功法尚未丰富，届时重做池子统一重新设定数值。bd `dhh` 保留为独立 issue（依赖 lvb/iup），随功法池重做执行。本 change 交付后游戏处于「引擎已活、功法数值超模」中间态（未上线可接受）。大招门槛字段与斩杀/逆袭条件已在 §3 配置到位，仅数值不降档。

## 8. 收尾

- [x] 8.1 `uv run ruff format . && uv run ruff check .` 通过
- [x] 8.2 metadata.yaml 版本号 v3.8.0 + README.md 更新日志 + handlers/misc_handler.py 修仙帮助文本（功法/大招生效、升星 3 星封顶说明）
- [x] 8.3 关闭 bd：lvb / iup / 711 / plt / riw / arx（**dhh 保留**，随功法池重做）；wxg 在武器入库后关闭 —— **待独立代码审查通过后执行**（subagent 基建已删，审查由用户/恢复后的 reviewer 进行）
- [ ] 8.4 `openspec archive` 本 change（合并并验证后）—— 同待审查
