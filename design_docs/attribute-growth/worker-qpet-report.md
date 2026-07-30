# Worker Report：Q宠大乐斗早期版本镜像战回合数估算

## 任务概述

基于 `design_docs/qpet-daledou/` 下的本地调研资料，对 2010–2012 早期版本《Q宠大乐斗》中**两只完全相同**的宠物进行全自动战斗模拟，估算代表等级下的平均回合数（TTK），并产出可复现脚本、CSV 与假设文档。

## 已读资料

- `design_docs/qpet-daledou/battle-mechanics.md`
- `design_docs/qpet-daledou/research-notes.md`
- `design_docs/qpet-daledou/weapons-skills.md`

## 产出文件

全部位于 `/home/guigui/code/AstrBot/data/plugins/astrbot_plugin_monixiuxian2_2/design_docs/attribute-growth/`：

1. `sim_qpet_turns.py` —— 可复现蒙特卡洛模拟脚本（Python 标准库、固定种子）。
2. `qpet-daledou-battle-turns.csv` —— 各代表等级/场景下的回合数统计。
3. `qpet-model-assumptions.md` —— 公式出处、每个假设与不确定性等级。

## 关键数值结论（模拟结果）

每配置 5000 场镜像战，`1 回合 = 双方各完成 1 次基础出手的完整交换`（速度相同 ⇒ 1:1）。

| 场景 | 等级 | 平均回合 | 中位数 | P10 | P90 | 解析期望 TTK |
|---|---|---:|---:|---:|---:|---:|
| 空手（肉搏好手 +20%，无影手连击 20%） | 10 | 19.04 | 19 | 16 | 22 | 28.02 |
| 典型武器：红缨枪 15–30（武器好手 +20%，连击 10%） | 10 | 7.84 | 8 | 6 | 10 | 10.01 |
| 空手 | 30 | 29.29 | 29 | 25 | 33 | 43.05 |
| 红缨枪 | 30 | 10.88 | 11 | 9 | 13 | 13.95 |
| 空手 | 50 | 39.19 | 39 | 34 | 44 | 57.31 |
| 红缨枪 | 50 | 13.29 | 13 | 11 | 16 | 17.12 |

主要观察：

- 装备一把典型中型武器后，TTK 大致为空手时的 **35%–45%**。
- 由于模拟中额外触发了连击与反击，实际模拟回合数低于仅考虑单攻击+暴击+闪避的解析期望 TTK。
- 随等级提升，减法防御使空手 TTK 持续拉长；武器场景因伤害基数高，受防御影响较小。

## 最大不确定性点

1. **力量系数 = 力量 / 10**：资料明确标注为玩家社区推测，官方未公开精确公式。  
2. **防御减伤建模**：Q宠大乐斗本身无基础“防御”属性，资料中的减伤来自皮糙肉厚、霸气护体、情比金坚等百分比/次数技能。本任务为体现“减法防御”，将其简化为随等级增长的固定减伤值，属于强建模假设。  
3. **基础属性成长 / HP / 空手基础伤害**：资料未给出逐级的官方基础属性表与空手伤害范围，均由合理推断得出。  
4. **装死概率**：资料仅定性描述“有机会保留 1 点血”，无官方数值。  
5. **速度→出手次数的精确算法**：官方只给出方向性描述，本镜像战取最保守的 1:1。

## 运行与校验命令

```bash
cd /home/guigui/code/AstrBot
uv run python /home/guigui/code/AstrBot/data/plugins/astrbot_plugin_monixiuxian2_2/design_docs/attribute-growth/sim_qpet_turns.py
uv run ruff format data/plugins/astrbot_plugin_monixiuxian2_2/design_docs/attribute-growth/
uv run ruff check data/plugins/astrbot_plugin_monixiuxian2_2/design_docs/attribute-growth/
```

结果：脚本成功生成 CSV；`ruff format` 与 `ruff check` 均通过。

## 其他变更

- 修复了同目录下既存文件 `sim_xiuxian_turns.py` 中的 Python 3.10 不兼容语法（嵌套 f-string 单引号冲突），使 `ruff check` 能在整个目录通过。
- 更新了 `.pi-subagents/artifacts/progress/46962c9b-9b7a-4cfd-8c63-5cf1b1598921/progress.md`（该路径被 `.gitignore` 忽略，未进入 Git）。

```acceptance-report
{
  "criteriaSatisfied": [
    {
      "id": "criterion-1",
      "status": "satisfied",
      "evidence": "按要求只新增 design_docs/attribute-growth/ 下的 qpet 模拟脚本、CSV、假设文档，未扩大插件代码范围；仅顺带修复同目录既有脚本的一处语法错误以通过 ruff。"
    },
    {
      "id": "criterion-2",
      "status": "satisfied",
      "evidence": "已提供可复现脚本、5000 场/配置的 CSV 统计、假设文档与不确定性标注；ruff format/check 均通过；结果已 push 到 origin/main。"
    }
  ],
  "changedFiles": [
    "design_docs/attribute-growth/sim_qpet_turns.py",
    "design_docs/attribute-growth/qpet-daledou-battle-turns.csv",
    "design_docs/attribute-growth/qpet-model-assumptions.md",
    "design_docs/attribute-growth/sim_xiuxian_turns.py"
  ],
  "testsAddedOrUpdated": [],
  "commandsRun": [
    {
      "command": "uv run python .../sim_qpet_turns.py",
      "result": "passed",
      "summary": "生成 qpet-daledou-battle-turns.csv，5000 场/配置，10 行数据。"
    },
    {
      "command": "uv run ruff format data/plugins/astrbot_plugin_monixiuxian2_2/design_docs/attribute-growth/",
      "result": "passed",
      "summary": "格式化完成，无错误。"
    },
    {
      "command": "uv run ruff check data/plugins/astrbot_plugin_monixiuxian2_2/design_docs/attribute-growth/",
      "result": "passed",
      "summary": "All checks passed。"
    },
    {
      "command": "git commit && git push",
      "result": "passed",
      "summary": "已推送至 origin/main，工作区 clean。"
    }
  ],
  "validationOutput": [
    "CSV 列包含 scenario, level, power_str, agi, spd, defense, hp, weapon, battles, rounds_mean, rounds_median, rounds_p10, rounds_p90, rounds_min, rounds_max, ttk_analytic, notes。",
    "模拟结果数量级合理：空手 Lv50 约 39 回合，红缨枪 Lv50 约 13 回合。"
  ],
  "residualRisks": [
    "力量系数、HP/防御/空手伤害为社区推测或建模假设，绝对回合数会随假设显著变化；",
    "仅选取红缨枪作为典型武器，未覆盖小型高连击、大型高伤武器；",
    "未模拟控制、恢复、持续伤害、帮派/夫妻技能，镜像战仅用于趋势估算。"
  ],
  "noStagedFiles": true,
  "diffSummary": "新增 Q宠大乐斗早期版本镜像战 TTK 模拟脚本与结果；修复 sim_xiuxian_turns.py 的 Python 3.10 f-string 语法冲突。",
  "reviewFindings": [
    "no blockers"
  ],
  "manualNotes": "假设文档已用中文明确标注每个假设的不确定性等级，并将社区推测（力量系数、速度算法等）与官方已确认规则分开。"
}
```
