# core/breakthrough_manager.py

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from astrbot.api import logger

from ..config_manager import ConfigManager
from ..data import DataBase
from ..models import Player

if TYPE_CHECKING:
    from ..core.skill_manager import SkillManager


class BreakthroughManager:
    """突破管理器 - 处理境界突破相关逻辑"""

    def __init__(
        self,
        db: DataBase,
        config_manager: ConfigManager,
        config: dict,
        skill_manager: SkillManager | None = None,
    ):
        self.db = db
        self.config_manager = config_manager
        self.config = config
        self.skill_manager = skill_manager

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
            # 突破成功 - 提升境界并触发随机成长
            player.level_index = next_level_index

            growth_attr = random.choice(["damage", "agility", "speed", "hp"])
            growth_step = self.config_manager.game_config.get("skill_system", {}).get(
                "random_growth_step", 5
            )
            growth_amount = growth_step
            old_attr_value = getattr(player, growth_attr)
            setattr(player, growth_attr, old_attr_value + growth_amount)

            await self.db.update_player(player)

            # 检查并处理突破贷款自动还款
            loan_msg = await self._handle_breakthrough_loan_repay(player)

            attr_name_map = {
                "damage": "伤害",
                "agility": "身法",
                "speed": "迅捷",
                "hp": "气血",
            }
            growth_attr_name = attr_name_map.get(growth_attr, growth_attr)

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

            success_msg = (
                f"✨ 突破成功！✨\n"
                f"━━━━━━━━━━━━━━━\n"
                f"{rate_info}\n"
                f"━━━━━━━━━━━━━━━\n"
                f"恭喜你从【{current_level_name}】突破至【{next_level_name}】！\n"
                f"\n【属性增长】\n"
                f"{growth_attr_name} +{growth_amount}\n"
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
                f"成长 {growth_attr_name}+{growth_amount}"
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
                # 突破失败但未死亡 - 扣除部分修为
                exp_penalty = int(player.experience * 0.1)  # 扣除10%修为
                player.experience = max(0, player.experience - exp_penalty)

                await self.db.update_player(player)

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
                    f"当前修为：{player.experience}\n"
                    f"请继续修炼，再接再厉！"
                )
                if learn_msgs:
                    fail_msg += "\n\n" + "\n".join(learn_msgs)

                logger.info(
                    f"玩家 {player.user_id} 突破失败："
                    f"{current_level_name} -> {next_level_name}，"
                    f"损失修为 {exp_penalty}"
                )

                return False, fail_msg, False

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
