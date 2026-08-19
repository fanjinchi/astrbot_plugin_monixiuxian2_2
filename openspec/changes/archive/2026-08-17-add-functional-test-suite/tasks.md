## 1. 测试资产目录与流程文档

- [x] 1.1 新建 `functional_tests/` 目录骨架：`cases/<domain>/`、`results/`、`README.md`
- [x] 1.2 编写 `functional_tests/README.md`：目录规范、用例 JSON 编写约定、结果目录命名 `<YYYY-MM-DD>_<target>`、同步/运行/导出流程
- [x] 1.3 更新 `AGENTS.md`：新增“功能测试套件”章节（存放位置、同步命令、运行命令、结果归档、目录命名）
- [x] 1.4 更新 `design_docs/README.md` 资料清单，登记 `functional_tests/` 与 `platform-gap-report.md`

## 2. 测试套件控制脚本

- [x] 2.1 实现 `scripts/test_suite_ctl.py` HTTP 基础层（复用平台 REST，支持 `WEBTEST_URL`/`WEBTEST_TOKEN`，与平台 CLI 一致）
- [x] 2.2 实现 `sync-cases`：扫描 `functional_tests/cases/**/*.json`，校验用例合法性且名称全局唯一，拍平复制到平台 `data/plugin_data/astrbot_plugin_testplatform/cases/`
- [x] 2.3 实现 `run --tag`：调用平台用例运行接口并轮询终态；支持 `--repeat N` 对同一用例重复运行
- [x] 2.4 实现 `export --target`：拉取最近运行记录与轨迹，写入 `functional_tests/results/<YYYY-MM-DD>_<target>/summary.md`、`cases/`、`messages/`
- [x] 2.5 实现 `fixture --profile pvp`：面向固定测试 ID 直接写插件数据库——创建/重置玩家属性、储物戒、`player_skills`、清除战斗冷却与忙碌状态；仅允许白名单内的测试 ID，操作前提示/备份

## 3. 非战斗功能用例（第一批）

- [x] 3.1 编写 `player-lifecycle`：我要修仙→选择灵修→我的信息→闭关→重复闭关拦截→出关
- [x] 3.2 编写 `equipment-heart-weapon`：GM 给武器/心法→装备→我的装备→卸下
- [x] 3.3 编写 `gm-basics`：GM 设境界/属性/给装备/清CD
- [x] 3.4 编写 `bank-sect-smoke`：银行存取/宗门基础路径
- [x] 3.5 编写 `pve-smoke`：Boss/历练/秘境可触达性冒烟（按当前配置与开关裁剪）
- [x] 3.6 为每个用例添加功能域 tag，并放入 `functional_tests/cases/<domain>/`

## 4. PvP 基础与装配验证

- [x] 4.1 编写 `pvp-basic-duel`：固定群聊身份双玩家创建→GM 设属性→决斗→断言战斗开始/胜利/回合
- [x] 4.2 编写 `pvp-basic-spar`：覆盖切磋路径；预期记录 `handlers/combat_handlers.py` 疑似缺 `result` 赋值的 Bug，标记为待修复用例
- [x] 4.3 编写 `pvp-heart-passive`：装不同心法后决斗，断言战斗首行属性（伤害/气血/身法/迅捷）随被动变化
- [x] 4.4 编写 `pvp-weapon-trigger`：青云天剑/混元至宝鼎/弑龙帝枪等武器触发技，断言「触发【…】」日志

## 5. PvP 效果矩阵（14 族 + 大招）

- [x] 5.1 fixture 脚本补齐全部效果所需 `player_skills` 装配（回春诀、噬血剑意、蚀骨咒、燃血诀、破风剑意、铁棘功、凝神诀、灵蛇缠身、破军诀、涅槃诀等）
- [x] 5.2 编写 `pvp-effect-damage_bonus`：断言「触发【…】，攻势更盛！」
- [x] 5.3 编写 `pvp-effect-combo`：断言连击触发文本与伤害倍率效果
- [x] 5.4 编写 `pvp-effect-stun`：断言「被眩晕，下回合无法出手」
- [x] 5.5 编写 `pvp-effect-counter`：断言「反击…造成 N 点伤害」
- [x] 5.6 编写 `pvp-effect-damage_reduction`：断言「受到的伤害降低」
- [x] 5.7 编写 `pvp-effect-heal`：断言「恢复 N 气血」
- [x] 5.8 编写 `pvp-effect-vampire`：吸血模式，断言战斗过程回血（可结合战后气血/日志）
- [x] 5.9 编写 `pvp-effect-dot`：断言「受【…】侵蚀，损失 N 气血」
- [x] 5.10 编写 `pvp-effect-buff` / `pvp-effect-debuff`：断言对应属性增益/削弱影响的战斗日志
- [x] 5.11 编写 `pvp-effect-unavoidable`：与被高闪避对手对战时，断言必中/无法闪避表现
- [x] 5.12 编写 `pvp-effect-pierce`：对高护甲对手断言穿透/破甲输出文本
- [x] 5.13 编写 `pvp-effect-reflect`：断言反弹伤害文本
- [x] 5.14 编写 `pvp-effect-survive`：断言「获得【…】庇护」及致死留血
- [x] 5.15 编写 `pvp-effect-fatigue`：断言自我 debuff/攻击降低日志
- [x] 5.16 编写 `pvp-ultimate-*`：万剑归宗（伤害）、回天圣手（治疗）、九幽噬魂咒（DOT）、涅槃诀（免死），断言「施展大招【…】」与解锁门槛（min_action_index/血量阈值）
- [x] 5.17 为所有 PvP 效果用例配置 `--repeat` 聚合验证策略，结果中记录触发次数/证据强度

## 6. 运行、归档与报告

- [x] 6.1 同步首批用例到平台并执行可稳定运行的非战斗用例；结果导出到 `functional_tests/results/<日期>_core-smoke/`
- [x] 6.2 在专用测试实例上配置 `GM_ADMINS`/白名单，运行 PvP 基础与效果矩阵用例；结果导出到 `functional_tests/results/<日期>_pvp-effects/`
- [x] 6.3 统计通过/失败/不稳定用例，写 `summary.md`；把已知 Bug（如 `handle_spar` 缺失赋值、效果未触发等）创建 bd issue 并链接证据
- [x] 6.4 编写 `functional_tests/platform-gap-report.md`：Supported / Partially supported / Unsupported 三类清单，含每项限制原因与平台增强建议（RNG seed、直接授予功法、结构化 At、DB 断言、时间加速、结果导出 API 等）
- [x] 6.5 质量门禁：`uv run ruff format . && uv run ruff check .`、既有 pytest 全绿；提交并推送