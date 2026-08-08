## 1. 设计表修正（skills.csv / heart_methods.csv）

- [x] 1.1 skills.csv：common_001 基础吐纳 / common_002 铁布衫 / draft_leiji 雷击诀 三行 `status` 由 legacy 改为 draft；heart_methods.csv：heart_001 长春功 `status` 由 legacy 改为 draft（新手默认心法，保留重导）
- [x] 1.2 万剑归宗行：`name` 由「万剑归宗（重做）」改为「万剑归宗」，`id` 由 draft_wanyu 改为 spirit_001（与 config 既有条目对齐，避免 player_skills 断裂）。**附带修复**：5 个大招行（万剑归宗/金身诀/真龙诀/九剑归一/天魔解体）触发技 5 槽只写 4 空，导致 route_mult_ling 错位落在 effect_value 槽（skills 从未同步故未暴露）——已补空槽归位
- [x] 1.3 天魔解体行：ultimate `effect_value` 由 2.1 改为 1.8（÷7≈25.7%，满足大招预算约束）
- [x] 1.4 heart_methods.csv 心法 skill_pool 挂载（**已在提案阶段完成**，apply 时核对：12/18 心法，覆盖通用/灵修/体修/传承池与系数梯度 1.0/0.8/0.6/0.5/0.3；确认 skill_id 与技能入库后 id 一致）

## 2. 同步脚本修复与技能同步扩展（scripts/sync_content_to_config.py）

- [x] 2.1 修复 `_build_heart` exp_multiplier：`_num(...) or 1.0` 改为「None 时 0.0、保留 0.0」，与 equipment_manager 默认值一致
- [x] 2.2 新增 `_build_skill`：字段映射（trigger_condition→trigger_timing 映射表 attack→on_attack / defend→on_defense / crit→on_crit / round_start→round_start；trigger_rate/effect_type/effect_value；ultimate_json 原样；route_multiplier={"灵修":mult_ling,"体修":mult_ti} 默认 1.0；pool/learn_coefficient/ref_source/design_note/trigger_name/status 不入库）
- [x] 2.3 新增技能契约校验：触发技四键齐全 + timing 在映射表内 + rate ∈ (0,1] + effect_value 数值；大招复用现有无 trigger_rate 校验（ult 版）；违规报错中止不写盘
- [x] 2.4 新增技能 merge（config/skills.json 为**池分组 dict**——加载器 `_load_items_data` 展平为 name→def 并注入 `_group`）：同名 UPDATE 保留既有 id、仅数值字段按 CSV 更新；新名按 pool 列入组 ADD。**注：技能持久化键保持 `trigger_condition`**（归一化层 skill_manager.py:347 在加载时注入引擎契约键 trigger_timing）
- [x] 2.5 **merge 扩展为 reconcile（全量重导）**：导入全部 draft/final 行后删除列表中不在导入 name 集合内的条目（weapons/heart/skills 三类一致）；dry-run 输出 DELETE 清单供核对；原子写保留（新增 _reconcile_list/_reconcile_groups）
- [x] 2.6 脚本 docstring/usage 更新：移除 skills 冻结声明（bd dhh 解锁）、merge→reconcile 语义、0.x 数值契约说明

## 3. 配置同步入库（全量重导）

- [x] 3.1 修复后重跑 sync（dry-run 确认：10 件心法 exp_multiplier 1.0→0.0、20 行技能入库、万剑归宗走 UPDATE 且 id=spirit_001、DELETE 清单符合预期：weapons 121→9 / heart 22→18 / skills 6→20）
- [x] 3.2 正式跑 sync 落盘，validate_budget 闸门全 PASS（含技能 20 行 0.x 校验）
- [x] 3.3 核对 config 重导结果：weapons.json 9 件（无旧词条）、heart_methods.json 18 件（长春功在、exp_multiplier 0.0 正确）、skills.json 20 件（新技能契约四键、大招无 trigger_rate、route_multiplier、基础吐纳 0.2 / 雷击诀 1.0 / 天魔解体 1.8 与 CSV 一致）
- [x] 3.4 幂等验证：再跑一次 sync --dry-run 应无 diff

## 4. 路线倍率消费（core/skill_manager.py get_battle_loadout）

- [x] 4.1 功法触发技导出时按 `player.cultivation_type` 应用路线倍率：`trigger_rate = min(1.0, rate × mult)`（value 不变；mult 缺省 1.0）
- [x] 4.2 大招导出时应用：`effect_value × mult`（必放制 rate 恒 1）
- [x] 4.3 更新 get_battle_loadout docstring（路线倍率语义与计算位置）

## 5. 心法路线装备校验（handlers/equipment_handler.py）

- [x] 5.1 equip 流程 item_type=main_technique 分支后插入校验：`route = heart_def.get("route", "通用")`，非通用且 ≠ cultivation_type 时拒绝并提示（可换用通用心法），不卸当前心法
- [x] 5.2 换装/替换主修心法路径同样走该校验（唯一装备入口 handle_equip_item 覆盖）
- [x] 5.3 **设计遗漏修正**：heart_methods.csv route 列原全「通用」使路线校验空转——按挂载池归属修正 5 件（烈火功/太虚功→灵修；龟息功/玄影功/战神诀→体修），重跑 sync 落盘（route diff 5 处、validate_budget 0 FAIL、幂等 0 diff）；最终分布 通用13/灵修2/体修3

## 6. 测试

- [x] 6.1 sync 修复测试：exp_multiplier 0.0 保留入库（None→0.0 默认）
- [x] 6.2 技能同步测试：万剑归宗同名覆盖保留 spirit_001、timing 映射（attack→on_attack、crit→on_crit）、大招含 trigger_rate 拒绝、触发技缺键拒绝
- [x] 6.3 reconcile 测试：表外条目删除（含 legacy 不导入即删除）、dry-run DELETE 清单、幂等
- [x] 6.4 路线倍率 loadout 测试：灵修/体修/未声明三分支；stun（value=0）乘 rate；大招乘 value；倍率与升星复合
- [x] 6.5 心法 route 校验测试：route=灵修 心法（烈火功）对体修玩家拒绝、同路线放行、通用心法（长春功）任意路线放行（注：5.3 后 config 已有灵修 2/体修 3 真实非通用心法，不再需要夹具构造）
- [x] 6.6 **领悟池机制集成测试**：长春功池（基础吐纳/铁布衫）构建、系数生效、已学保留（重复参悟→升星）与 study_target 已学排除、突破成功学习、universal 5% 替换、无主修心法 3% 兜底（注：心法池**不过滤已学**是设计行为——重复抽到升星）
- [x] 6.7 **存量测试审计**：全量 pytest 360 通过（331+9+20），无依赖旧条目断言需要修正（spirit_001 语义已随重导更新且旧条目用例此前已清理）
- [x] 6.8 全量 pytest 通过

## 7. 回归与文档

- [x] 7.1 运行 sim_balance_regression.py 数值回退对比（武器基准持平，确认技能/重导未影响武器平衡判定）
- [x] 7.2 创建 bd issue 跟踪未来项：平衡完成后将最终配置固化进 data/default_configs.py（供未来使用者开箱即用）
- [x] 7.3 更新 design_docs/content-design/schema-and-engine-fit.md：技能同步落地状态（P 项勾选）、exp_multiplier 修复、reconcile 全量重导说明
- [x] 7.4 更新 design_docs/content-design/README.md（技能表已启用同步、重导语义）与 skills-ultimates.md §5/§6（天魔解体降值、legacy→draft）
- [ ] 7.5 ruff format + ruff check 通过；按 AGENTS.md 会话收尾规则 commit + push

## 8. OpenSpec 归档

- [x] 8.1 tasks 全部勾选后 `openspec validate --specs` 通过
- [x] 8.2 delta specs 同步进主 spec（content-sync-pipeline 技能同步/零值保留、skill-system 路线倍率/心法匹配/大招预算）
- [x] 8.3 `openspec archive implement-content-design -y` 归档
