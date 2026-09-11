# Proposal: combat-report-structure

## Why

flavor-copy-assembly 及上一轮文案导入（b1ff0c8）把战斗域叙事场景换成文学变体池后，webtest 真机回归（2026-09-11）暴露两个战报结构性破损：

- **bd -r0a**：`battle_opening`/`battle_victory` 等战报框架场景原本是结构横幅（`☆━━━━ 战斗开始 ━━━━☆`），被整体替换成纯文学句后，战报彻底失去可读的起止标志——combat_manager 把这些场景直接当横幅用，没有代码侧结构行兜底。pvp-basic-duel/spar 用例因此真失败，回归信号丢失。
- **bd -hcn**：`remaining_hp` 在每次命中后无条件追加，旧文案是中性数据行所以无害；换成文学变体（全部濒死语义）后出现 83% 血量说"气血将尽"、0 血阵亡还说"掌心扣着后手"的自相矛盾，且 `{remaining_hp}` 裸插数字无格式不成句。

根因相同：**结构/机械信息的表达责任被交给了文学文案**。flavor-copy-assembly 已确立的原则（面板/换行归代码，文案只做风味）需要延伸到战报域。

## What

1. **战报横幅代码所有（-r0a）**：战斗开始/胜利/平局/胶着/同归于尽五条横幅改由 `combat_manager` 代码拼装结构行（恢复 `☆━━━━ … ━━━━☆` 形态）；`battle_opening`/`battle_victory`/`battle_draw`/`battle_draw_stalemate`/`battle_mutual_destruction` 五个叙事场景降级为横幅下的文学描述行（配置池缺失/为空时回退内嵌最小默认描述句，不报错）。
2. **remaining_hp 阈值分档（-hcn）**：命中后不再无条件追加剩余气血行——按防守方气血比例分档：`> mid` 不输出（降噪）、`low < ratio ≤ mid` 出残局文案、`ratio ≤ low` 出濒死文案。新增 `remaining_hp_mid`（残局）/`remaining_hp_low`（濒死）两个场景，旧 `remaining_hp` 场景退役；`{remaining_hp}` 由代码格式化为千分位字符串。
3. **内容管线**：残局档文案为新增内容，濒死档 4 条现有变体需改写修复裸数字——均先在 `copy_variants.csv` 成稿、用户确认后导入（AGENTS §15）。

## Capabilities

- `narrative-text-config`（MODIFIED 载体消费方式的增量契约：战报横幅代码所有、剩余气血行阈值分档）

## Non-goals

- 不改战斗数值/结算逻辑（伤害、格挡、触发技等零改动）。
- 不重写 battle_opening 等五个场景的现有文学变体（它们继续作为 flavor 池服役）；只为 remaining_hp 两档写新稿。
- 不处理 combat 域 route 标注（沿用 flavor-copy-assembly 4.3 结论：combat 场景调用点不传 route/level_index）。
- `-hcn`/`-r0a` 之外的战报文案打磨不在本变更。
