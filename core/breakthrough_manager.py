# core/breakthrough_manager.py

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from astrbot.api import logger

from ..config_manager import ConfigManager
from ..data import DataBase
from ..models import Player
from .breakthrough_fortune import format_fortune_message, roll_breakthrough_fortune

if TYPE_CHECKING:
    from ..core.skill_manager import SkillManager

from .pill_manager import PillManager
from .storage_ring_manager import StorageRingManager


class BreakthroughManager:
    """突破管理器 - 处理境界突破相关逻辑"""

    def __init__(
        self,
        db: DataBase,
        config_manager: ConfigManager,
        config: dict,
        skill_manager: SkillManager | None = None,
        storage_ring_manager: StorageRingManager | None = None,
        pill_manager: PillManager | None = None,
    ):
        self.db = db
        self.config_manager = config_manager
        self.config = config
        self.skill_manager = skill_manager
        self.storage_ring_manager = storage_ring_manager or StorageRingManager(
            db, config_manager
        )
        self.pill_manager = pill_manager or PillManager(db, config_manager)

    def check_breakthrough_requirements(self, player: Player) -> tuple[bool, str]:
        """检查玩家是否满足突破条件

        Args:
            player: 玩家对象

        Returns:
            (是否满足, 错误消息)
        """
        # 根据修炼类型获取对应的境界数据
        level_data = self.config_manager.get_level_data(player.cultivation_type)

        # 检查是否已经是最高境界
        if player.level_index >= len(level_data) - 1:
            return False, "你已经达到了最高境界，无法继续突破！"

        # 获取下一境界所需修为
        next_level_index = player.level_index + 1
        next_level_data = level_data[next_level_index]
        required_exp = next_level_data.get("exp_needed", 0)

        # 检查修为是否满足
        if player.experience < required_exp:
            current_level = level_data[player.level_index]["level_name"]
            next_level = next_level_data["level_name"]
            return False, (
                f"修为不足！\n"
                f"当前境界：{current_level}\n"
                f"当前修为：{player.experience}\n"
                f"突破至【{next_level}】需要修为：{required_exp}"
            )

        return True, ""

    def calculate_breakthrough_success_rate(
        self, player: Player, pill_name: str | None = None, temp_bonus: float = 0.0
    ) -> tuple[float, str]:
        """计算突破成功率

        Args:
            player: 玩家对象
            pill_name: 使用的破境丹名称（可选）

        Returns:
            (成功率, 说明信息)
        """
        # 根据修炼类型获取对应的境界数据
        level_data = self.config_manager.get_level_data(player.cultivation_type)

        # 获取基础成功率
        next_level_index = player.level_index + 1
        next_level_data = level_data[next_level_index]
        base_success_rate = next_level_data.get("success_rate", 0.5)

        info_lines = [f"基础成功率：{base_success_rate:.1%}"]

        final_rate = base_success_rate + temp_bonus
        max_rate = 1.0  # 默认最大100%

        if temp_bonus:
            info_lines.append(f"临时丹药加成：{temp_bonus:+.1%}")

        # 如果使用了破境丹
        if pill_name:
            pill_data = self.config_manager.pills_data.get(pill_name)
            if pill_data and pill_data.get("subtype") == "breakthrough":
                breakthrough_bonus = pill_data.get("breakthrough_bonus", 0)
                max_rate = pill_data.get("max_success_rate", 1.0)

                # 计算加成后的成功率
                final_rate = min(
                    base_success_rate + temp_bonus + breakthrough_bonus, max_rate
                )

                info_lines.append(f"破境丹加成：+{breakthrough_bonus:.1%}")
                info_lines.append(f"最大成功率限制：{max_rate:.1%}")
            else:
                logger.warning(f"无效的破境丹：{pill_name}")

        final_rate = max(0.0, min(final_rate, max_rate))

        # 连败保底加成在丹药 cap 之后叠加（不受 max_rate 限制，上限 100%）
        skill_cfg = self.config_manager.game_config.get("skill_system", {})
        pity_step = skill_cfg.get("breakthrough_pity_step", 0.05)
        pity_guarantee = skill_cfg.get("breakthrough_pity_guarantee", 19)

        if player.breakthrough_fail_streak >= pity_guarantee:
            final_rate = 1.0
            info_lines.append(
                f"连败保底：{player.breakthrough_fail_streak}次失败，天道酬勤，本次必成！"
            )
        elif player.breakthrough_fail_streak > 0:
            pity_bonus = player.breakthrough_fail_streak * pity_step
            final_rate = min(final_rate + pity_bonus, 1.0)
            info_lines.append(
                f"连败加成：+{pity_bonus:.1%}（连败{player.breakthrough_fail_streak}次）"
            )

        info_lines.append(f"最终成功率：{final_rate:.1%}")
        info = "\n".join(info_lines)

        return final_rate, info

    async def execute_breakthrough(
        self,
        player: Player,
        pill_name: str | None = None,
        temp_bonus: float = 0.0,
        death_rate_multiplier: float = 1.0,
    ) -> tuple[bool, str, bool]:
        """执行突破

        Args:
            player: 玩家对象
            pill_name: 使用的破境丹名称（可选）

        Returns:
            (是否成功, 消息, 是否死亡)
        """
        # 检查突破条件
        can_breakthrough, error_msg = self.check_breakthrough_requirements(player)
        if not can_breakthrough:
            return False, error_msg, False

        # 计算成功率
        success_rate, rate_info = self.calculate_breakthrough_success_rate(
            player, pill_name, temp_bonus
        )

        # 根据修炼类型获取对应的境界数据
        level_data = self.config_manager.get_level_data(player.cultivation_type)

        # 判定突破结果
        random_value = random.random()
        breakthrough_success = random_value < success_rate

        current_level_name = level_data[player.level_index]["level_name"]
        next_level_index = player.level_index + 1
        next_level_data = level_data[next_level_index]
        next_level_name = next_level_data["level_name"]

        if breakthrough_success:
            # 突破成功 - 清零连败计数（先保存原连败数用于彩蛋文案）
            prev_fail_streak = player.breakthrough_fail_streak
            player.breakthrough_fail_streak = 0

            # 提升境界并触发方案A成长
            player.level_index = next_level_index

            skill_cfg = self.config_manager.game_config.get("skill_system", {})
            hp_step = skill_cfg.get("hp_growth_step", 15)
            combat_points = skill_cfg.get("random_growth_step", 5)
            weights = skill_cfg.get(
                "growth_weights", {"damage": 0.6, "agility": 0.25, "speed": 0.15}
            )

            # HP 独立通道
            player.hp += hp_step
            hp_growth = hp_step

            # 战斗属性点逐点随机
            attrs = list(weights.keys())
            probs = [weights[a] for a in attrs]
            total_prob = sum(probs)
            combat_growth: dict[str, int] = dict.fromkeys(attrs, 0)
            for _ in range(combat_points):
                r = random.random() * total_prob
                cum = 0.0
                for attr, p in zip(attrs, probs):
                    cum += p
                    if r < cum:
                        combat_growth[attr] += 1
                        setattr(
                            player,
                            attr,
                            getattr(player, attr) + 1,
                        )
                        break

            await self.db.update_player(player)

            # 检查并处理突破贷款自动还款
            loan_msg = await self._handle_breakthrough_loan_repay(player)

            # 高连败彩蛋文案
            streak_bonus_msg = ""
            if prev_fail_streak >= 3:
                streak_bonus_msg = "\n💪 苦尽甘来，天道不负有心人！"

            # 领悟判定（成功 20%）
            learn_msgs = []
            if self.skill_manager:
                learned = (
                    await self.skill_manager.roll_breakthrough_success_comprehension(
                        player
                    )
                )
                if learned:
                    learn_msgs.append(
                        f"🎁 福至心灵，领悟功法【{learned.get('name', '未知')}】！"
                    )
                fallback = await self.skill_manager.roll_universal_pool_breakthrough(
                    player, success=True
                )
                if fallback:
                    learn_msgs.append(
                        f"🎁 破境感悟，领悟通用功法【{fallback.get('name', '未知')}】！"
                    )

            # 突破机缘轮盘（方案 A 成长与领悟判定之后）
            fortune_msg = await self._apply_breakthrough_fortune(
                player, next_level_index
            )
            if fortune_msg:
                learn_msgs.append(fortune_msg)

            success_msg = (
                f"✨ 突破成功！✨{streak_bonus_msg}\n"
                f"━━━━━━━━━━━━━━━\n"
                f"{rate_info}\n"
                f"━━━━━━━━━━━━━━━\n"
                f"恭喜你从【{current_level_name}】突破至【{next_level_name}】！\n"
                f"\n【属性增长】\n"
                f"气血 +{hp_growth}\n"
                f"伤害 +{combat_growth.get('damage', 0)}\n"
                f"身法 +{combat_growth.get('agility', 0)}\n"
                f"迅捷 +{combat_growth.get('speed', 0)}\n"
                f"\n【当前属性】\n"
                f"伤害：{player.damage}\n"
                f"身法：{player.agility}\n"
                f"迅捷：{player.speed}\n"
                f"气血：{player.hp}\n"
                f"护甲：{player.armor_value}"
            )
            if learn_msgs:
                success_msg += "\n\n" + "\n".join(learn_msgs)

            logger.info(
                f"玩家 {player.user_id} 突破成功："
                f"{current_level_name} -> {next_level_name}, "
                f"成长 气血+{hp_growth} "
                f"伤害+{combat_growth.get('damage', 0)} "
                f"身法+{combat_growth.get('agility', 0)} "
                f"迅捷+{combat_growth.get('speed', 0)}"
            )

            if loan_msg:
                success_msg += f"\n\n{loan_msg}"

            return True, success_msg, False

        else:
            # 突破失败 - 判断是否死亡
            death_probability_range = self.config.get("VALUES", {}).get(
                "BREAKTHROUGH_DEATH_PROBABILITY",
                [0.01, 0.1],  # 默认1%-10%死亡概率
            )

            # 随机一个死亡概率
            death_rate = random.uniform(
                death_probability_range[0], death_probability_range[1]
            )
            death_rate = max(0.0, min(1.0, death_rate * death_rate_multiplier))
            died = random.random() < death_rate

            if died:
                # 走火入魔 - 清零连败计数
                player.breakthrough_fail_streak = 0
                await self.db.update_player(player)

                # 检查是否有回生丹效果
                from .pill_manager import PillManager

                pill_manager = PillManager(self.db, self.config_manager)
                resurrected = await pill_manager.handle_resurrection(player)

                if resurrected:
                    # 回生丹触发，玩家复活
                    resurrection_msg = (
                        f"💀 突破失败，走火入魔！💀\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"{rate_info}\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"你在突破【{next_level_name}】时走火入魔...\n"
                        f"\n"
                        f"⚡ 回生丹效果触发！⚡\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"🌟 你涅槃重生了！\n"
                        f"⚠️ 但所有属性降低到之前的一半\n"
                        f"💊 回生丹效果已消耗\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"请继续修炼，重回巅峰！"
                    )

                    logger.info(f"玩家 {player.user_id} 突破失败触发回生丹，成功复活")

                    # 返回False（突破失败），消息，False（未真正死亡）
                    return False, resurrection_msg, False

                # 玩家死亡 - 级联删除所有关联数据
                await self.db.delete_player_cascade(player.user_id)

                death_msg = (
                    f"💀 突破失败，走火入魔！💀\n"
                    f"━━━━━━━━━━━━━━━\n"
                    f"{rate_info}\n"
                    f"━━━━━━━━━━━━━━━\n"
                    f"你在突破【{next_level_name}】时走火入魔，身死道消...\n"
                    f"所有修为和装备化为虚无\n"
                    f"若想重新修仙，请使用'我要修仙'命令重新开始"
                )

                logger.info(
                    f"玩家 {player.user_id} 突破失败并死亡：{current_level_name} -> {next_level_name}，死亡概率 {death_rate:.2%}"
                )

                return False, death_msg, True

            else:
                # 突破失败但未死亡 - 增加连败计数并扣除修为
                player.breakthrough_fail_streak += 1
                exp_penalty = int(player.experience * 0.1)  # 扣除10%修为
                player.experience = max(0, player.experience - exp_penalty)

                await self.db.update_player(player)

                # 计算连败保底提示
                skill_cfg = self.config_manager.game_config.get("skill_system", {})
                pity_step = skill_cfg.get("breakthrough_pity_step", 0.05)
                pity_guarantee = skill_cfg.get("breakthrough_pity_guarantee", 19)
                streak = player.breakthrough_fail_streak
                next_bonus = streak * pity_step
                remaining = max(0, pity_guarantee - streak)
                pity_msg = (
                    f"\n连败 {streak} 次，天道酬勤："
                    f"下次成功率 +{next_bonus:.0%}"
                    f"（再败 {remaining} 次必成）"
                )

                # 领悟判定（失败 10% 软保底）
                learn_msgs = []
                if self.skill_manager:
                    learned = (
                        await self.skill_manager.roll_breakthrough_fail_comprehension(
                            player
                        )
                    )
                    if learned:
                        learn_msgs.append(
                            f"🎁 破而后立，领悟功法【{learned.get('name', '未知')}】！"
                        )
                    fallback = (
                        await self.skill_manager.roll_universal_pool_breakthrough(
                            player, success=False
                        )
                    )
                    if fallback:
                        learn_msgs.append(
                            f"🎁 破境感悟，领悟通用功法【{fallback.get('name', '未知')}】！"
                        )

                fail_msg = (
                    f"❌ 突破失败 ❌\n"
                    f"━━━━━━━━━━━━━━━\n"
                    f"{rate_info}\n"
                    f"━━━━━━━━━━━━━━━\n"
                    f"突破【{next_level_name}】失败，但幸运地保住了性命\n"
                    f"修为受损，损失了 {exp_penalty} 点修为\n"
                    f"当前修为：{player.experience}"
                    f"{pity_msg}"
                )
                if learn_msgs:
                    fail_msg += "\n\n" + "\n".join(learn_msgs)

                logger.info(
                    f"玩家 {player.user_id} 突破失败："
                    f"{current_level_name} -> {next_level_name}，"
                    f"损失修为 {exp_penalty}，连败 {streak} 次"
                )

                return False, fail_msg, False

    async def _apply_breakthrough_fortune(
        self, player: Player, new_level_index: int
    ) -> str:
        """突破成功后掷一次机缘掉落轮盘并应用到玩家背包/储物戒。

        Args:
            player: 突破成功后的玩家对象（会被本方法直接修改并持久化）。
            new_level_index: 玩家突破后的新境界索引。

        Returns:
            用于追加到突破成功消息的中文文案；无掉落时返回空字符串。
        """
        result = roll_breakthrough_fortune(
            random.Random(),
            self.config_manager.game_config,
            new_level_index,
            list(self.config_manager.weapons_data.values()),
            list(self.config_manager.heart_methods_data.values()),
            list(self.config_manager.pills_data.values())
            + list(self.config_manager.utility_pills_data.values()),
        )
        if result is None:
            return ""

        if result["type"] in ("weapon", "heart_method"):
            item_name = result["items"][0]["name"]
            items = player.get_storage_ring_items()
            can_store = (
                item_name in items
                or self.storage_ring_manager.get_available_slots(player) > 0
            )
            if can_store:
                items[item_name] = items.get(item_name, 0) + 1
                player.set_storage_ring_items(items)
                await self.db.update_player(player)
            else:
                return f"🎁 机缘天降，获得【{item_name}】，但储物戒已满无法存入。"

        elif result["type"] == "pill":
            for item in result["items"]:
                await self.pill_manager.add_pill_to_inventory(
                    player, item["name"], item["count"]
                )

        return format_fortune_message(result)

    async def _handle_breakthrough_loan_repay(self, player: Player) -> str:
        """处理突破贷款自动还款

        Args:
            player: 玩家对象

        Returns:
            还款消息（如果有贷款的话）
        """
        try:
            # 检查是否有突破贷款
            loan = await self.db.ext.get_active_loan(player.user_id)
            if not loan or loan["loan_type"] != "breakthrough":
                return ""

            # 计算应还金额
            import time

            now = int(time.time())
            days_borrowed = max(1, (now - loan["borrowed_at"]) // 86400)
            interest = int(loan["principal"] * loan["interest_rate"] * days_borrowed)
            total_due = loan["principal"] + interest

            # 检查玩家是否有足够灵石
            if player.gold >= total_due:
                # 自动扣款
                player.gold -= total_due
                await self.db.update_player(player)

                # 关闭贷款
                await self.db.ext.close_loan(loan["id"])

                # 记录流水
                bank_data = await self.db.ext.get_bank_account(player.user_id)
                balance = bank_data["balance"] if bank_data else 0
                await self.db.ext.add_bank_transaction(
                    player.user_id,
                    "auto_repay",
                    -total_due,
                    balance,
                    f"突破成功自动还款：本金{loan['principal']:,}+利息{interest:,}",
                    now,
                )

                return (
                    f"💰 突破贷款自动还款成功！\n"
                    f"━━━━━━━━━━━━━━━\n"
                    f"已还本金：{loan['principal']:,} 灵石\n"
                    f"已还利息：{interest:,} 灵石\n"
                    f"当前持有：{player.gold:,} 灵石"
                )
            else:
                # 灵石不足，提醒玩家
                return (
                    f"⚠️ 你有未还清的突破贷款！\n"
                    f"应还金额：{total_due:,} 灵石\n"
                    f"当前持有：{player.gold:,} 灵石\n"
                    f"请尽快使用 /还款 命令还款"
                )
        except Exception as e:
            logger.warning(f"处理突破贷款自动还款异常: {e}")
            return ""
