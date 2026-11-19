# E2 28+4 内容审批材料（战斗与叙事已批准）

> 状态：**approved_and_synced**。2026-11-19 用户先选择 A，随后明确改选 B 并要求加入文案，批准完整 28+4 战斗与叙事内容以及 E2 规划、导入与激活。32 行已升为 `final / 定稿` 并完成正式 sync；3 个 guardian 保持 `draft / 占位`。正式产物 4/4 世界 Boss 为 `narrative_approved=true`，契约测试通过后可广播。

## 1. 审阅入口与事实源

- 数值与文案唯一事实源：`design_docs/content-design/enemies.csv`、`design_docs/content-design/world_bosses.csv`。
- [完整正式 diff](hostile-content-v1-to-v2.formal.diff)：当前 v1 到正式 v2 的逐字段 diff。
- [正式候选 JSON](enemies-v2.formal.json)：由正式 renderer 与 manifest 生成，世界 Boss `narrative_approved=true`。
- [正式 approval manifest](approval-manifest.json)：绑定获批 CSV hash、整行表头和 `["定稿"]` 叙事决策。
- [正式 sync 日志](formal-sync.log)：预算与叙事双闸门均为 0 FAIL。
- `enemy_groups.key=top` 已在正式 sync 前移除；`low/mid/high/legacy_guardian` 保留。

## 2. 范围与当前指纹

| 项目 | 数量 / SHA-256 |
|---|---|
| 正式 roster | 28；`c2cbb6c388bd8847056e3bbdb61328c71be7c7b1bbcf137a07c2ea690f359ff0` |
| 世界 Boss | 4；`f442caa46848928898eb72924932f86f751fc14b3a6310985ffc001ee061f60e` |
| 正式 v2 `config/enemies.json` | `f86e94acc1bad3d61b23bbb403e4218c5d53313df6ba0cbb5712acfacead2d21` |
| 正式候选 JSON | `ccae1ed7d676813290e7106b92bd577365f19acf29bab1e80720c1c6dbf38c5e` |
| 完整正式 diff | `c94330ef5db3b52e909d35a93e21f8800ca7e6fa5feae509db578f9a9998f717` |
| 正式 manifest | `173a6b2fc5738bef0900685ffbd81ab15f938dfa7480f40e5f9a8fa108a2789f` |

`enemies.csv` 另有 `guardian_low`/`guardian_mid`/`guardian_high` 3 行动态守护者；它们由专项组配置消费、renderer 明确不写入固定名册，因此不计入 28+4，也不进入本次正式批准 gate。

### 条目导航

完整字段请打开 diff 并按 id 搜索；下表只用于定位，不替代完整 diff。

| 域 | id | 名称 | 段 | 类型 | HP | 伤害 | status | narrative_status |
|---|---|---|---|---|---:|---:|---|---|
| 名册 | `mon_lq_zhu` | 獠牙野猪 | 练气 | normal | 77 | 3 | final | 定稿 |
| 名册 | `mon_lq_gui` | 石壳龟 | 练气 | normal | 96 | 3 | final | 定稿 |
| 名册 | `mon_lq_bao` | 山豹 | 练气 | normal | 61 | 4 | final | 定稿 |
| 名册 | `mon_lq_she` | 青竹蛇 | 练气 | normal | 69 | 3 | final | 定稿 |
| 名册 | `mon_lq_bao_e` | 狂暴的山豹 | 练气 | elite | 156 | 22 | final | 定稿 |
| 名册 | `mon_lq_gui_e` | 坚甲的石壳龟 | 练气 | elite | 183 | 17 | final | 定稿 |
| 名册 | `mon_lq_zhu_wang` | 老林猪王·古力 | 练气 | boss | 228 | 18 | final | 定稿 |
| 名册 | `mon_zj_niu` | 板角蛮牛 | 筑基 | normal | 129 | 16 | final | 定稿 |
| 名册 | `mon_zj_xiong` | 铁背熊 | 筑基 | normal | 161 | 13 | final | 定稿 |
| 名册 | `mon_zj_hu` | 赤瞳虎 | 筑基 | normal | 103 | 20 | final | 定稿 |
| 名册 | `mon_zj_lang` | 疾风狼 | 筑基 | normal | 116 | 15 | final | 定稿 |
| 名册 | `mon_zj_xiong_e` | 坚甲的铁背熊 | 筑基 | elite | 305 | 42 | final | 定稿 |
| 名册 | `mon_zj_hu_e` | 嗜血的赤瞳虎 | 筑基 | elite | 260 | 49 | final | 定稿 |
| 名册 | `mon_zj_lang_wang` | 苍月狼王 | 筑基 | boss | 410 | 34 | final | 定稿 |
| 名册 | `mon_jd_e` | 玄水鳄 | 金丹 | normal | 257 | 33 | final | 定稿 |
| 名册 | `mon_jd_yuan` | 玄甲鼋 | 金丹 | normal | 322 | 28 | final | 定稿 |
| 名册 | `mon_jd_ya` | 赤焰火鸦 | 金丹 | normal | 206 | 41 | final | 定稿 |
| 名册 | `mon_jd_yao` | 穿云鹞 | 金丹 | normal | 232 | 31 | final | 定稿 |
| 名册 | `mon_jd_ya_e` | 狂暴的赤焰火鸦 | 金丹 | elite | 518 | 98 | final | 定稿 |
| 名册 | `mon_jd_yuan_e` | 坚甲的玄甲鼋 | 金丹 | elite | 607 | 76 | final | 定稿 |
| 名册 | `mon_jd_jiao` | 玄水蛟·螭渊 | 金丹 | boss | 994 | 57 | final | 定稿 |
| 名册 | `mon_yy_hu` | 玉面狐 | 元婴 | normal | 352 | 57 | final | 定稿 |
| 名册 | `mon_yy_juren` | 石魄巨人 | 元婴 | normal | 440 | 48 | final | 定稿 |
| 名册 | `mon_yy_tanglang` | 血刀螳螂 | 元婴 | normal | 282 | 71 | final | 定稿 |
| 名册 | `mon_yy_sun` | 九霄雷隼 | 元婴 | normal | 317 | 54 | final | 定稿 |
| 名册 | `mon_yy_tanglang_e` | 嗜血的血刀螳螂 | 元婴 | elite | 705 | 144 | final | 定稿 |
| 名册 | `mon_yy_hu_e` | 狂暴的玉面狐 | 元婴 | elite | 881 | 127 | final | 定稿 |
| 名册 | `mon_yy_hujun` | 千面狐君 | 元婴 | boss | 1083 | 124 | final | 定稿 |
| 世界 Boss | `wb_lq_ba` | 裂峡罴王 | 练气 | — | 1000 | 18 | final | 定稿 |
| 世界 Boss | `wb_zj_tuo` | 泽底鼍龙 | 筑基 | — | 1800 | 34 | final | 定稿 |
| 世界 Boss | `wb_jd_zhu` | 焚山朱厌 | 金丹 | — | 4600 | 57 | final | 定稿 |
| 世界 Boss | `wb_yy_ba` | 吞象巴蛇 | 元婴 | — | 5000 | 105 | final | 定稿 |

## 3. 三种批准路径（最终选择 B）

| 选项 | 用户批准后 CSV | manifest `narrative_status` | 世界 Boss 产物与广播 |
|---|---|---|---|
| A. 只批准战斗数值 | 28+4 `status=final`；叙事保持 `占位` | `["占位"]` | 允许正式 sync/激活；`narrative_approved=false`，四类事件不广播 |
| **B. 同时批准战斗与叙事（已选）** | 28+4 `status=final`；获批行叙事升 `定稿` | `["定稿"]` | 五类文案完整且过 lint/Schema 后 `narrative_approved=true`，允许广播 |
| C. 显式叙事豁免 | 28+4 `status=final`；`豁免` 不写进 CSV，当前行仍为 `占位` | `["豁免"]` | 用户明确豁免后产物可为 true；E2 须先修正现有 `check_approval` 的 gate 语义并补测试 |

2026-11-19 用户明确批准完整 28+4 战斗与叙事内容以及 E2 规划、导入与激活，未排除任何 id。用户随后直接要求 AI 加入文案，覆盖了此前“用户自行修改批准字段”的操作分工；本次由 AI 按该明确指令落盘 `final / 定稿` 并生成正式 manifest。

## 4. 正式导入结果

- 28+4 行已为 `final / 定稿`；3 个 guardian 保持 `draft / 占位`。
- manifest 使用 `narrative_status=["定稿"]`，正式产物 4/4 世界 Boss 为 `narrative_approved=true`。
- 正式配置为 schema v2，28+4 ID 全部唯一，共享 Schema 校验无错误，`top` 组已删除。
- 正式 sync 的预算与叙事双闸门均为 0 FAIL；剩余警告均来自未纳入本次批准的 legacy 行或其他内容域。

## 5. 后续验收

- 通过真实 `EnemyCatalog` 加载、出生快照和 renderer 契约测试后，四类世界 Boss 事件方可广播。
- 普通 PVE 切流、旧 Boss 整删、新入口/poller 启用和完整回归继续按 E2 后续步骤执行。
