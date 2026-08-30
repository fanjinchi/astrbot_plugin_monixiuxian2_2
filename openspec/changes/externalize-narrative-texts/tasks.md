# Tasks: externalize-narrative-texts

## 1. 载体与加载链路

- [x] 1.1 `data/default_configs.py` 新增 `DEFAULT_NARRATIVE_CONFIG`（突破/战斗/修炼/机缘/传承之地各节，文案从代码逐字搬运）；`config_manager.py` 用 `_load_config_with_default` 加载 `narrative_config.json` 并提供按场景取模板的访问器（支持三种场景形态：单模板/扁平池/境界段分桶池，统一归一为合并后 list；route 标注条目按玩家路线过滤；分桶合并取用的 helper 与 5.6 事件选桶共用同一实现）
- [x] 1.2 模板插值变量契约校验：每个场景声明变量集合，加载时校验模板引用 ⊆ 声明集合（分桶池与 route 标注条目同样逐条校验）；违例场景回退内嵌最小默认文案并报错（场景 key + 变量名），不崩溃；访问器缺省/场景缺失时静默回退同一套内嵌默认（兼容测试 fake config）
- [x] 1.3 灵根/体质评价大表（`core/cultivation_manager.py:203-263` ~48 条）外移至 `config/spirit_root_descriptions.json`，复用 `_load_items_data` 条目型模式

## 2. 突破与机缘域

- [x] 2.1 `core/breakthrough_manager.py` 成功（`:311-326`）/失败回生丹（`:373-385`）/身死道消（`:397-403`）/保命（`:462-469`）/连败保底（`:434-436`）/领悟功法 flavor（`:293`/`:300`/`:449`/`:458`）替换为配置渲染；连败奖励句（`:281`）作为 flavor 文案一并外移。成功率说明文本（`:138-191` 的 `rate_info` 各行）**不外移**——数值说明类文本保持简洁直白、留在代码原位（world-bible §1.3 注，design D6）
- [x] 2.2 `core/breakthrough_fortune.py` 机缘三句（`:194`/`:207`/`:219`）外移至 fortune 节
- [x] 2.3 逐字核对：该域 config 文本 == 原代码文本（`rate_info` 各行留在代码原位、不参与核对）；跑 `tests/test_breakthrough_manager.py` / `test_breakthrough_fortune.py`

## 3. 战斗域

- [x] 3.1 `managers/combat_manager.py` `_resolve_attack` 全部叙事句式（`:885-1056`：眩晕/闪避/格挡/暴击/大招/伤害结算/反弹/吸血）+ 免死句式（`_try_survive` `:1058-1074`）外移，初版池长 1
- [x] 3.2 战斗框架收束语（`:202-265` 开头/胜利/平局/同归于尽）与技能触发/buff 句式（`:598`/`:774`/`:818`/`:875-882`）外移
- [x] 3.3 逐字核对：该域 config 文本 == 原代码文本；跑 `tests/test_combat_engine.py` / `test_combat_handlers.py`，涉及文案断言的用例改为匹配配置文本（functional_tests 的 PvP 用例断言了原文案，池长 1 + 逐字搬运下应保持绿）

## 4. 修炼结算域

- [x] 4.1 `handlers/player_handler.py` 闭关开始（`:304-308`）/出关结算骨架（`:462-476`）/闭关悟道（`:391`）/传承值结算 flavor（`:431-440`）外移
- [x] 4.2 角色创建叙事（`:61-129`）与弃道重修（`:625`）外移——仅外移叙事欢迎/告别词与 flavor 评价；路线机制说明行（讲轮回/重修数值规则的行）属数值说明类，留在代码原位（design D6）
- [x] 4.3 逐字核对：该域 config 文本 == 原代码文本；跑该域既有测试 + `functional_tests` 对应用例

## 5. 秘境、传承之地与历练事件

- [x] 5.1 `rift_config.json` 每秘境加 `description` + 结算叙事位（**config-only，不落 DB 列、无 migration**，design D3）；`rift_manager` 读取链路扩展；秘境列表 UI 展示 description
- [x] 5.2 `rift_manager.py:324-328` 探索事件变体池外移进 rift 配置（字段结构沿用现硬编码）
- [x] 5.3 传承之地文案收敛：`adventure_manager.py:397-407` / `rift_manager.py:400-405`（偶遇制）与 `sect_manager.py:1697`/`:1748-1752`（领取制，含宗门专属机制行）收敛为 narrative_config 单一模板簇（偶遇/领取两个场景模板）。【实施注记：实际按胜/负分支拆为 4 场景（encounter_win/encounter_lose/claim_win/claim_lose）——载体池语义是随机轮换而非结果选择，单模板无法服务胜负两文；两处偶遇文案仅差"一处/上古"两字，收敛取"上古传承之地"】
- [x] 5.4 逐字核对：本域 config 文本 == 原代码文本；跑 `tests/` 中 rift/adventure/sect 相关用例
- [x] 5.5 `adventure_config.json` 事件条目 schema 扩展：可选 `tags`（题材标签位，默认空）+ `desc_variants`（按境界段分桶的文案池，桶键 通用/练气/筑基/金丹/元婴）；现有 `desc` 逐字保留为兜底（design D7）
- [x] 5.6 `adventure_manager` 事件文案取数点改为按玩家境界段选桶（当前段+通用桶合并随机，空桶回落 `desc`）；境界段边界映射集中一处（Lv1-9/10-19/20-29/30-39，对齐 season-1 幕表）；存量无新字段条目正常加载
- [x] 5.7 逐字核对兜底文案 == 原 `desc`；跑 adventure 相关测试 + `functional_tests` 对应域

## 6. fallback 收敛与死代码

- [x] 6.1 三 manager 内嵌 DEFAULT 副本默认值先迁移进 `data/default_configs.py`（该文件当前无这三个域默认值），再改 manager 引用单源并删除内嵌副本（顺序不可颠倒，design D4）
- [x] 6.2 删除 `utils/config_loader.py`（死代码）并清理 `utils/__init__.py` 的 `ConfigLoader` re-export，确认无引用
- [x] 6.3 bible §1.6 文案载体清单更新（物理位置列改为 config 路径）；design_docs/README 登记

## 7. 收尾

- [x] 7.1 `openspec validate externalize-narrative-texts --strict` 通过
- [x] 7.2 全量 `uv run python -m pytest tests/ -q` 通过；`ruff format/check`
- [x] 7.3 版本 checklist（AGENTS.md §7）：`metadata.yaml` version、`README.md` 更新日志、`README.md` 配置文件表补 `narrative_config.json` / rift 新字段、修仙帮助文本（如涉及指令变化）
- [x] 7.4 关闭 bd `yux`、`og9`；更新 bd `tyt`（工程侧落地，内容侧保留待 design_docs 管线）；`functional_tests` 相关域回归由用户手动发起（2026-08-30 新规：真实环境功能测试不由 AI 主动执行，见 AGENTS.md 网页端测试平台节）
