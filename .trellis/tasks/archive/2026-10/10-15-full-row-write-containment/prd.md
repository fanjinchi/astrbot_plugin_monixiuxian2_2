# 全列回写收口：忙碌行窄写 + 经济写点锁内重读 + 契约登记

## Goal

把「持快照跨 await 后整行回写」这一类丢失更新，在本轮止血范围内收口：忙碌行（`user_cd`）的三个全列写点改为窄写，消除唯一「不可自查、需管理员救」的永久锁死故障；碰灵石且无重读保护的写点改为写锁内重读；把契约写进 `AGENTS.md` 与 `.trellis/spec/`，避免后续模块继续复制危险写法。

## 依据

- bd `astrbot_plugin_monixiuxian2_2-546`「Player/UserCd 全列 UPDATE 造成跨 await 陈旧快照覆盖」——2026-10-14 诊断轮已补入普查数据与优先级建议。
- 上一轮 `f878891`（`fix(pve): 历练结算终态不再被二次覆写`）只做单点收口（终态守护 + 重放按 `hp_after` 对齐内存气血），写入端口径未动。
- 并发可达性（诊断轮查证）：`astrbot/core/event_bus.py:52` 对每个事件 `asyncio.create_task`，**不按 session 串行**；`astrbot/core/utils/session_lock.py` 的锁只包 `pipeline/process_stage/method/agent_sub_stages/internal.py:239` 的 LLM 请求，不覆盖插件命令管线。忙碌闸门只拦非白名单命令，而白名单中的可写命令（签到、存/取灵石、贷款/还款、修习目标、取消修习、战报条数、出关）在忙碌期照常执行。

## Requirements

### R1. 忙碌行窄写（P0，先做）

- `core/busy_state.py` 的 `stamp_extra` 只写 `extra_data`，不得回写 `type` / `create_time` / `scheduled_time`——现有实现按调用方快照整行回写，晚一步就会把别人已 `clear` 的忙碌**复活成原状态**；忙碌判定只看 `type`，复活后重启不自愈。
- `core/gm_manager.py` 的两处 force-settle（`cmd_force_adventure`、`cmd_force_rift`）只写 `scheduled_time`，与该入口既有语义（「仅上移 scheduled_time」）对齐。
- `db.ext.update_user_cd(user_cd)` 的**现有全列语义保持不变**：GM 两处调用与 `tests/test_adventure_settlement_state_machine.py::test_revived_busy_self_heals_on_replay` 都按现有语义写。
- 数据层新增**显式窄写入口**（调用方声明要写哪些列），业务模块不得自己拼 SQL。

### R2. 经济写点锁内重读（P1b）

候选清单（生产代码中「碰 `gold` 且 enclosing 函数内无 `get_player_by_id` 重读」的全部 12 处，2026-10-15 AST 普查）：

| # | 位置 | 场景 |
|---|---|---|
| 1 | `handlers/player_handler.py:626` | 签到 |
| 2 | `managers/adventure_manager.py:1292` | 历练基础奖励 |
| 3 | `managers/blessed_land_manager.py:102` | 购买福地 |
| 4 | `managers/blessed_land_manager.py:163` | 升级福地 |
| 5 | `managers/blessed_land_manager.py:214` | 收取福地产出 |
| 6 | `managers/spirit_farm_manager.py:94` | 开垦灵田 |
| 7 | `managers/spirit_farm_manager.py:205` | 收获灵田 |
| 8 | `managers/spirit_farm_manager.py:270` | 升级灵田 |
| 9 | `core/storage_ring_manager.py:324` | 升级储物戒 |
| 10 | `core/breakthrough_manager.py:652` | 突破还贷 |
| 11 | `core/pill_manager.py:493` | 瞬回丹（疑似无 health_service 的兜底分支） |
| 12 | `handlers/shop_handler.py:472` | 旧丹效果（同上，疑似兜底） |

- 每处按既有范式改造：**写锁内重读 → 再计算 → 再写回**（范式出处：`managers/bank_manager.py:118` 注释与 `handlers/shop_handler.py:218`）。
- 顺序约束：调用方若在进入事务前已经改过内存 `player`，重读后必须**重新应用**该改动，不得让改动凭空消失。
- 第 11、12 处若确认为「`health_service is None` 才走」的兜底分支，可跳过，但必须在任务记录里写明理由。

### R3. 契约登记（P2）

- `AGENTS.md` §3 增加一句原则：持快照跨 await 后不得整行回写；钱/血/忙碌的写点必须写锁内重读或列级写。
- `.trellis/spec/backend/database-guidelines.md` 增加细则：什么情况必须重读、窄写的接口形态、`_DOMAIN_OWNED_FIELDS` 的扩展方式。

## Non-goals（本轮明确不做）

- 不把 87 处 `update_player` 全量改为列级写（成本远大于收益）。
- 不做 `update_player` 的自动 diff / 列级 API（继续留在 bd `-546`）。
- 不改气血域写入路径（「战斗/丹药/商店气血写全部走 HealthService + 把 `current_hp` 登记进 `_DOMAIN_OWNED_FIELDS`」是另一个决策，本轮不动）。

## Acceptance Criteria

- [x] **AC1**：并发/交错场景下，`stamp_extra` 与 GM force-settle 不再复活已清空的忙碌（回归用例覆盖：陈旧行晚写不得恢复 `type`）。
- [x] **AC2**：收口后的经济写点，在并发 `asyncio.gather` 下不得丢失或重复灵石；至少覆盖「签到」与「历练基础奖励」两处真并发用例，其余处给出结构性断言（写锁内确实重读）。
- [x] **AC3**：全量 `pytest` 通过（1153 passed）；ruff 源码目录通过。
- [x] **AC4**：契约文字落盘（AGENTS.md + spec）。
- [x] **AC5**：按 `AGENTS.md` §7 同步 `metadata.yaml` 版本（v3.21.2）、`README.md` 更新日志；无新增/变更指令，`/修仙帮助` 无需改动。

## 执行记录（2026-10-15）

- R1：`db.ext.update_user_cd_fields`（白名单 + positional-only user_id）、`stamp_extra` 窄写、GM 两处窄写；`update_user_cd` 全列语义保持不变。新增 3 条用例（`tests/test_busy_state.py`）+ GM 断言改造。
- R2：11 处收口（签到、历练效果发放、福地×3、灵田×3、储物戒升级、突破自动还贷、瞬回丹）；`handlers/shop_handler._apply_legacy_pill_effects` **判定为误报**——它在 `handle_buy` 的事务内被调用，而该事务开头已重读玩家行（`handlers/shop_handler.py:218`），无需再改。
- R3：`AGENTS.md` §3 一句原则 + `.trellis/spec/backend/database-guidelines.md`「陈旧快照回写」一节（含常见错误条目）。
- 钉子突变验证：把三处修复分别还原后，对应新用例各 1 failed（`stamp_extra` 复活、签到双发、效果发放覆盖并发余额），证明是真钉子。
- 全量：`1153 passed`（原 1148，+5 条新用例）；ruff format + check 源码目录通过；顺带把 `ruff format` 造成的两处无关格式化改动（`tests/test_pve_persistence_foundation.py`、`tests/test_transaction_atomicity.py`）已还原，保持 diff 聚焦。
### 评审轮修复（第二轮，2026-10-15）

两轴独立评审（Standards / Spec，各自带真内存库探针）的发现与处理：

1. **P1 掉落被收尾整行写抹掉**（Spec 轴，本轮引入的回归）：`_grant_effects` 回拷清单漏 `storage_ring_items`（戒指内的物品，与"戒指名"是两列），重放自愈路径随后按入口快照整行回写 → 消息说"获得物品"、库里被抹掉。修：清单补列 + 注释写死不变式（清单须覆盖所有效果改动的 Player 列）；`spirit_farm_manager.harvest` 同步补列。新增端到端用例 `test_replay_reissued_drops_survive_the_self_heal_write`（真 `StorageRingManager` + 崩溃点 3 + 忙碌复活 + 掉落必中）。
2. **P1 并发服药 KeyError**（两轴；Standards 判 P1、Spec 判 P2，复核后按 P1）：`_use_instant_pill` 包装层锁内重读后未复核背包，落败方在本体 `inventory[pill_name] -= 1` 抛 KeyError。覆盖面经核实为**全部 26 条丹药**（`config/pills.json` 全部无 `effect_type`，只有 instant 分支可达）。修：锁内复核，缺失返回既有文案。
3. **P2 签到提前 return 在事务内 yield**（两轴）：BEGIN IMMEDIATE 被握到消息发送完成（探针实测另一任务被挡 250ms）。修：文案存局部变量、出事务再 yield。
4. **P2 文档漂移 7 处**（两轴，§8 视为 bug）：`core/busy_state.py` 类 docstring、`AGENTS.md` §2 例外、`.trellis/spec/backend/database-guidelines.md`、`design_docs/api-overview.md`×2、`README.md`、`managers/adventure_manager.py` 重放注释。
5. **P2 测试缺口**（Spec 轴）：AC2「其余处结构性断言」未落实 + 新包装层零覆盖。修：新增 `tests/test_stale_snapshot_write_containment.py`（洞天收取 / 灵田收获 / 瞬回丹并发各一条）。
6. **P2 格式化噪音**：还原 `tests/test_adventure_settlement_state_machine.py` 里 4 处与本次无关的 ruff 格式化 hunk（`build_env` 签名因新增参数保持折行）；该文件与另两个测试文件在改动前就存在 format 漂移（`ruff format --check` 会报这三处，属仓库现状）。

**未采纳**：外层快检与锁内复核的重复（「快路径 + 权威复核」的固有形状，与银行/商店范式一致）；`_grant_effects` 改为返回 `fresh` / 全字段 diff 同步（会动孩子 C 的气血对齐语义，风险大于收益）。

**门**：全量 **1157 passed**（+4 条新用例）；`ruff check` 源码目录干净；4 处突变验证（storage_ring_items 回拷、瞬回丹锁内复核、洞天重读、灵田重读）各自还原后 **1 failed**，均为真钉子；修复后另派一轮独立复看。


## Verification

```bash
cd /home/guigui/code/AstrBot && \
UV_CACHE_DIR=/tmp/uvcache RUFF_CACHE_DIR=/tmp/ruffcache \
uv run python -m pytest data/plugins/astrbot_plugin_monixiuxian2_2/tests/ -q
```

ruff 只跑源码目录（`managers/ tests/ core/ handlers/ data/ main.py`）；`.trellis/` 脚本有既存 lint 报错，与本任务无关。

## Notes

- 本任务与 bd `-546` 的关系：任务是**写入端止血**；-546 保留「全列 UPDATE 口径 / 列级 API / diff 方案」的长期议题。
- 真实 AstrBot 端到端管线回归由用户发起（项目约定）；本任务以 `pytest` 真并发用例 + ruff 为质量门。
