# handlers/player_handler.py
import random
import time
from datetime import datetime

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent

from ..config_manager import ConfigManager
from ..core import CultivationManager, PillManager, SkillManager
from ..data import DataBase
from ..models import Player
from ..models_extended import UserStatus
from .utils import player_required

CMD_START_XIUXIAN = "我要修仙"
CMD_PLAYER_INFO = "我的信息"
CMD_START_CULTIVATION = "闭关"
CMD_END_CULTIVATION = "出关"
CMD_CHECK_IN = "签到"
REBIRTH_COOLDOWN = 7 * 24 * 3600

__all__ = ["PlayerHandler"]


class PlayerHandler:
    """玩家基础信息处理器 - 支持灵修/体修选择"""

    def __init__(
        self,
        db: DataBase,
        config: AstrBotConfig,
        config_manager: ConfigManager,
        skill_manager: SkillManager | None = None,
        sect_mgr=None,
    ):
        self.db = db
        self.config = config
        self.config_manager = config_manager
        self.skill_manager = skill_manager
        self.sect_mgr = sect_mgr
        self.cultivation_manager = CultivationManager(
            config, config_manager, skill_manager
        )
        self.pill_manager = PillManager(self.db, self.config_manager)

    async def handle_start_xiuxian(
        self, event: AstrMessageEvent, cultivation_type: str = ""
    ):
        """处理创建角色

        Args:
            cultivation_type: 修炼类型，"灵修"或"体修"，为空则显示选择提示
        """
        user_id = event.get_sender_id()

        # 检查是否已创建角色
        if await self.db.get_player_by_id(user_id):
            yield event.plain_result("道友，你已踏入仙途，无需重复此举。")
            return

        # 如果没有提供职业选择，显示选择提示
        if not cultivation_type or cultivation_type.strip() == "":
            help_msg = (
                "🌟 欢迎踏入修仙之路！\n"
                "━━━━━━━━━━━━━━━\n"
                "请选择你的修炼方式：\n\n"
                "【灵修】以灵气为主，法术攻击\n"
                "• 寿命：100\n"
                "• 灵气：100-1000\n"
                "• 法伤：5-100\n"
                "• 物伤：5\n"
                "• 法防：0\n"
                "• 物防：5\n"
                "• 精神力：100-500\n\n"
                "【体修】以气血为主，肉身强横\n"
                "• 寿命：50-100\n"
                "• 气血：100-500\n"
                "• 法伤：0\n"
                "• 物伤：100-500\n"
                "• 法防：50-200\n"
                "• 物防：100-500\n"
                "• 精神力：100-500\n"
                "━━━━━━━━━━━━━━━\n"
                "⚠️ 修仙风险警告 ⚠️\n"
                "• 突破失败有概率走火入魔身死道消\n"
                "• 生命值归零也会导致死亡\n"
                "• 死亡后所有数据清除，需重新入仙途\n"
                "━━━━━━━━━━━━━━━\n"
                f"💡 使用方法：\n"
                f"  {CMD_START_XIUXIAN} 灵修\n"
                f"  {CMD_START_XIUXIAN} 体修"
            )
            yield event.plain_result(help_msg)
            return

        # 验证职业类型
        cultivation_type = cultivation_type.strip()
        if cultivation_type not in ["灵修", "体修"]:
            yield event.plain_result("职业选择错误！请选择「灵修」或「体修」。")
            return

        # 生成新玩家
        new_player = self.cultivation_manager.generate_new_player_stats(
            user_id, cultivation_type
        )
        await self.db.create_player(new_player)

        # 获取灵根描述
        root_name = new_player.spiritual_root.replace("灵根", "")
        root_description = self.cultivation_manager._get_root_description(root_name)

        reply_msg = (
            f"🎉 恭喜道友 {event.get_sender_name()} 踏上仙途！\n"
            f"━━━━━━━━━━━━━━━\n"
            f"修炼方式：【{new_player.cultivation_type}】\n"
            f"灵根：【{new_player.spiritual_root}】\n"
            f"评价：{root_description}\n"
            f"启动资金：{new_player.gold} 灵石\n"
            f"━━━━━━━━━━━━━━━\n"
            f"⚠️ 修仙有风险，突破需谨慎！\n"
            f"突破失败或生命值归零会导致\n"
            f"身死道消，所有数据清除！\n"
            f"━━━━━━━━━━━━━━━\n"
            f"💡 发送「{CMD_PLAYER_INFO}」查看状态"
        )
        yield event.plain_result(reply_msg)

    @player_required
    async def handle_player_info(self, player: Player, event: AstrMessageEvent):
        """处理查看玩家信息 - 展示四主属性与新战力。"""
        display_name = event.get_sender_name()
        required_exp = player.get_required_exp(self.config_manager)

        # 更新丹药效果并计算最终属性倍率
        await self.pill_manager.update_temporary_effects(player)
        pill_multipliers = self.pill_manager.calculate_pill_attribute_effects(player)

        # 获取装备加成后的属性
        from ..core import EquipmentManager

        equipment_manager = EquipmentManager(self.db, self.config_manager)
        equipped_items = equipment_manager.get_equipped_items(
            player, self.config_manager.items_data, self.config_manager.weapons_data
        )
        total_attrs = player.get_total_attributes(equipped_items, pill_multipliers)

        # 新战力公式：四主属性 + 护甲//2
        combat_power = (
            int(total_attrs["damage"])
            + int(total_attrs["agility"])
            + int(total_attrs["speed"])
            + int(total_attrs["hp"])
            + int(total_attrs.get("armor_value", 0)) // 2
        )

        # 获取宗门信息
        sect_name = "无宗门"
        position_name = "散修"
        if player.sect_id and player.sect_id != 0:
            sect = await self.db.ext.get_sect_by_id(player.sect_id)
            if sect:
                sect_name = sect.sect_name
                if sect.sect_owner == player.user_id:
                    position_name = "宗主"
                elif player.sect_position == 1:
                    position_name = "长老"
                elif player.sect_position == 2:
                    position_name = "亲传弟子"
                elif player.sect_position == 3:
                    position_name = "内门弟子"
                else:
                    position_name = "外门弟子"

        # 获取装备信息
        weapon_name = player.weapon if player.weapon else "无"
        armor_name = player.armor if player.armor else "无"
        technique_name = player.main_technique if player.main_technique else "无"

        # 永久突破加成（level_up_rate，整数百分点），仅在大于 0 时显示
        breakthrough_line = (
            f"  突破加成：+{player.level_up_rate}%\n"
            if player.level_up_rate > 0
            else ""
        )

        # 获取修习目标
        study_target_name = "无"
        if self.skill_manager:
            study_info = self.skill_manager.get_study_target_info(player)
            if study_info.get("has_target"):
                study_target_name = study_info.get("name", "未知")

        # 获取战报合并条数偏好
        merge_count = self.config_manager.game_config.get("skill_system", {}).get(
            "battle_report_merge_count", 10
        )
        if player.battle_report_merge_count > 0:
            merge_count = max(1, min(50, player.battle_report_merge_count))

        # 获取已领悟功法数量
        learned_count = len(await self.db.ext.get_learned_skills(player.user_id))

        # 构建信息显示
        dao_hao = player.user_name if player.user_name else display_name

        reply_msg = (
            f"📋 道友 {dao_hao} 的信息\n"
            f"━━━━━━━━━━━━━━━\n"
            f"\n"
            f"【基本信息】\n"
            f"  道号：{dao_hao}\n"
            f"  境界：{player.get_level(self.config_manager)}\n"
            f"  修为：{int(player.experience):,}/{int(required_exp):,}\n"
            f"  灵石：{player.gold:,}\n"
            f"  战力：{combat_power:,}\n"
            f"  灵根：{player.spiritual_root}\n"
            f"{breakthrough_line}"
            f"\n"
            f"【四主属性】\n"
            f"  伤害：{total_attrs['damage']}\n"
            f"  身法：{total_attrs['agility']}\n"
            f"  迅捷：{total_attrs['speed']}\n"
            f"  气血：{total_attrs['hp']}\n"
            f"  护甲：{total_attrs.get('armor_value', 0)}\n"
            f"\n"
            f"【装备信息】\n"
            f"  主修功法：{technique_name}\n"
            f"  法器：{weapon_name}\n"
            f"  防具：{armor_name}\n"
            f"\n"
            f"【功法修习】\n"
            f"  已领悟功法：{learned_count}\n"
            f"  修习目标：{study_target_name}\n"
            f"  战报合并条数：{merge_count}\n"
            f"\n"
            f"【宗门信息】\n"
            f"  所在宗门：{sect_name}\n"
            f"  宗门职位：{position_name}\n"
        )

        # 获取贷款信息
        loan = await self.db.ext.get_active_loan(player.user_id)
        if loan:
            now = int(time.time())
            remaining_seconds = loan["due_at"] - now
            remaining_days = remaining_seconds // 86400
            remaining_hours = (remaining_seconds % 86400) // 3600

            days_borrowed = max(1, (now - loan["borrowed_at"]) // 86400)
            interest = int(loan["principal"] * loan["interest_rate"] * days_borrowed)
            total_due = loan["principal"] + interest

            loan_type_name = (
                "突破贷款" if loan["loan_type"] == "breakthrough" else "普通贷款"
            )

            if remaining_seconds <= 0:
                time_str = "⚠️ 已逾期！"
            elif remaining_days <= 0:
                time_str = f"🔴 {remaining_hours}小时"
            elif remaining_days <= 1:
                time_str = f"🟠 {remaining_days}天{remaining_hours}小时"
            else:
                time_str = f"🟡 {remaining_days}天"

            reply_msg += (
                f"\n"
                f"【贷款信息】💰\n"
                f"  类型：{loan_type_name}\n"
                f"  应还：{total_due:,} 灵石\n"
                f"  剩余：{time_str}\n"
                f"  💀 逾期将被追杀致死！\n"
            )

        reply_msg += "━━━━━━━━━━━━━━━"

        yield event.plain_result(reply_msg)

    @player_required
    async def handle_start_cultivation(self, player: Player, event: AstrMessageEvent):
        """处理闭关指令"""
        # 检查是否已经在闭关
        if player.state == "修炼中":
            yield event.plain_result("道友已在闭关中，请勿重复进入。")
            return

        # 检查是否在其他活动中（历练、秘境探索等）
        user_cd = await self.db.ext.get_user_cd(player.user_id)
        if user_cd and user_cd.type != UserStatus.IDLE:
            current_status = UserStatus.get_name(user_cd.type)
            yield event.plain_result(f"❌ 道友当前正{current_status}，无法闭关修炼！")
            return

        # 记录闭关开始时间
        player.state = "修炼中"
        player.cultivation_start_time = int(time.time())
        await self.db.update_player(player)
        await self.db.ext.set_user_busy(player.user_id, UserStatus.CULTIVATING, 0)

        yield event.plain_result(
            "🧘 道友已进入闭关状态\n"
            "━━━━━━━━━━━━━━━\n"
            "闭关期间，你将与世隔绝，潜心修炼。\n"
            f"💡 发送「{CMD_END_CULTIVATION}」结束闭关\n"
            "⏱️ 每分钟将获得修为，受灵根资质影响。"
        )

    @player_required
    async def handle_end_cultivation(self, player: Player, event: AstrMessageEvent):
        """处理出关指令"""
        # 检查是否在闭关中
        if player.state != "修炼中":
            yield event.plain_result("道友当前并未闭关，无需出关。")
            return

        # 检查是否有闭关开始时间
        if player.cultivation_start_time == 0:
            yield event.plain_result("数据异常：未记录闭关开始时间。")
            return

        # 计算闭关时长（分钟）
        end_time = int(time.time())
        duration_seconds = end_time - player.cultivation_start_time
        duration_minutes = duration_seconds // 60

        if duration_minutes < 1:
            yield event.plain_result(
                "道友闭关时间不足1分钟，未获得修为。请继续闭关修炼。"
            )
            return

        # 闭关时长上限根据境界调整（基础24小时，每提升一个大境界增加6小时）
        # level_index 为 1-based：1-10 练气，11-20 筑基，依此类推
        base_minutes = 1440  # 24小时
        realm_bonus = ((player.level_index - 1) // 10) * 360  # 每个大境界增加6小时
        MAX_CULTIVATION_MINUTES = base_minutes + realm_bonus
        effective_minutes = min(duration_minutes, MAX_CULTIVATION_MINUTES)
        exceeded_time = duration_minutes > MAX_CULTIVATION_MINUTES

        # 更新丹药效果，确保持续结算
        await self.pill_manager.update_temporary_effects(player)
        pill_multipliers = self.pill_manager.calculate_pill_attribute_effects(player)

        # 获取主修心法的修为加成
        technique_bonus = 0.0
        if player.main_technique:
            from ..core import EquipmentManager

            equipment_manager = EquipmentManager(self.db, self.config_manager)
            equipped_items = equipment_manager.get_equipped_items(
                player, self.config_manager.items_data, self.config_manager.weapons_data
            )
            # 找到主修心法
            for item in equipped_items:
                if item.item_type == "main_technique":
                    technique_bonus = item.exp_multiplier
                    break

        # 计算获得的修为（使用有效时长）
        gained_exp = self.cultivation_manager.calculate_cultivation_exp(
            player, effective_minutes, technique_bonus, pill_multipliers
        )

        # 宗门洞天加成：全员闭关修为 × (1 + exp_bonus_per_level × 洞天等级)
        fairyland_line = ""
        if self.sect_mgr and player.sect_id:
            (
                fairyland_bonus,
                fairyland_level,
            ) = await self.sect_mgr.get_fairyland_exp_bonus(player)
            if fairyland_bonus > 0:
                gained_exp = int(gained_exp * (1 + fairyland_bonus))
                fairyland_line = f"🏯 宗门洞天（{fairyland_level}级）加持：修为 +{fairyland_bonus:.0%}\n"

        player.experience += gained_exp

        # 闭关悟道判定：每满 2 小时一次，每次 15%（需装备心法，仅配套池+修习目标）
        effective_hours = effective_minutes // 60
        learn_msgs = []
        if self.cultivation_manager.skill_manager and effective_hours > 0:
            learned_list = (
                await self.cultivation_manager.apply_cultivation_comprehension(
                    player, effective_hours
                )
            )
            for learned in learned_list:
                learn_msgs.append(
                    f"🎁 闭关悟道，领悟功法【{learned.get('name', '未知')}】！"
                )

        # 更新玩家状态
        player.state = "空闲"
        player.cultivation_start_time = 0
        await self.db.update_player(player)
        await self.db.ext.set_user_free(player.user_id)

        # 计算闭关时长显示
        hours = duration_minutes // 60
        minutes = duration_minutes % 60
        time_str = ""
        if hours > 0:
            time_str += f"{hours}小时"
        if minutes > 0:
            time_str += f"{minutes}分钟"

        # 超时提示
        exceed_msg = ""
        if exceeded_time:
            effective_hours = MAX_CULTIVATION_MINUTES // 60
            exceed_msg = (
                f"\n⚠️ 闭关超过{effective_hours}小时，仅计算前{effective_hours}小时修为"
            )

        reply_msg = (
            "🌟 道友出关成功！\n"
            "━━━━━━━━━━━━━━━\n"
            f"⏱️ 闭关时长：{time_str}\n"
            f"{fairyland_line}"
            f"📈 获得修为：{gained_exp:,}{exceed_msg}\n"
            f"💫 当前修为：{player.experience:,}\n"
            "━━━━━━━━━━━━━━━\n"
            "道友已回归红尘，可继续修行。"
        )
        if learn_msgs:
            reply_msg += "\n\n" + "\n".join(learn_msgs)
        yield event.plain_result(reply_msg)

    @player_required
    async def handle_check_in(self, player: Player, event: AstrMessageEvent):
        """处理签到指令"""
        # 获取今天的日期（格式：YYYY-MM-DD）
        today = datetime.now().strftime("%Y-%m-%d")

        # 跨日重置：宗门丹药领取标记与宗门任务计数（以日期变更为锚，
        # 由每日首位签到的玩家触发一次全局重置）。原子推进日期：
        # INSERT ... ON CONFLICT ... WHERE value != 今日，仅 rowcount > 0
        # 的调用方执行重置，避免并发签到双重重置；日期推进与重置在同一
        # 事务内统一提交——重置失败则日期不推进，下次签到自动重试；
        # 任何失败不得影响签到主流程。
        try:
            now_ts = int(time.time())
            await self.db.conn.execute("BEGIN IMMEDIATE")
            try:
                cursor = await self.db.conn.execute(
                    """
                    INSERT INTO system_config (key, value, updated_at)
                    VALUES ('sect_daily_reset_date', ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        value = excluded.value, updated_at = excluded.updated_at
                    WHERE system_config.value != excluded.value
                    """,
                    (today, now_ts),
                )
                if cursor.rowcount > 0:
                    await self.db.ext.reset_sect_elixir_get(commit=False)
                    await self.db.ext.reset_sect_tasks(commit=False)
                await self.db.conn.commit()
            except Exception:
                await self.db.conn.rollback()
                raise
        except Exception as e:
            logger.warning("【修仙插件】宗门每日重置失败（不影响签到）: %s", e)

        # 检查是否已经签到过
        if player.last_check_in_date == today:
            yield event.plain_result("📅 道友今日已经签到过了\n请明日再来。")
            return

        # 获取签到奖励范围配置
        check_in_gold_min = self.config["VALUES"].get("CHECK_IN_GOLD_MIN", 50)
        check_in_gold_max = self.config["VALUES"].get("CHECK_IN_GOLD_MAX", 500)

        # 确保最小值不大于最大值
        if check_in_gold_min > check_in_gold_max:
            check_in_gold_min, check_in_gold_max = check_in_gold_max, check_in_gold_min

        # 生成随机奖励
        check_in_gold = random.randint(check_in_gold_min, check_in_gold_max)

        # 宗门职阶俸禄：按 benefits.daily_stones 加发
        sect_salary = 0
        position_name = ""
        if self.sect_mgr and player.sect_id:
            benefits = self.sect_mgr.get_position_benefits(player.sect_position)
            sect_salary = benefits["daily_stones"]
            position_name = self.sect_mgr.get_position_name(player.sect_position)

        # 更新玩家数据
        player.gold += check_in_gold + sect_salary
        player.last_check_in_date = today
        await self.db.update_player(player)

        salary_line = (
            f"🏛️ 宗门俸禄（{position_name}）：+{sect_salary} 灵石\n"
            if sect_salary > 0
            else ""
        )
        reply_msg = (
            "✅ 签到成功！\n"
            "━━━━━━━━━━━━━━━\n"
            f"💰 获得灵石：{check_in_gold}\n"
            f"{salary_line}"
            f"💎 当前灵石：{player.gold}\n"
            "━━━━━━━━━━━━━━━\n"
            "明日再来，莫要忘记哦~"
        )
        yield event.plain_result(reply_msg)

    @player_required
    async def handle_rebirth(
        self, player: Player, event: AstrMessageEvent, confirm_text: str = ""
    ):
        """弃道重修（7天冷却）"""
        user_cd = await self.db.ext.get_user_cd(player.user_id)
        if user_cd and user_cd.type != UserStatus.IDLE:
            status_name = UserStatus.get_name(user_cd.type)
            yield event.plain_result(f"❌ 你当前正在「{status_name}」，无法弃道重修。")
            return

        if player.state != "空闲":
            yield event.plain_result(
                "❌ 只有处于空闲状态时才能弃道重修。请先结束闭关/历练等活动。"
            )
            return

        loan = await self.db.ext.get_active_loan(player.user_id)
        if loan:
            yield event.plain_result("❌ 你仍有未结清的灵石贷款，无法重修。请先还款。")
            return

        key = f"rebirth_last_{player.user_id}"
        last_ts = await self.db.ext.get_system_config(key)
        now = int(time.time())
        if last_ts:
            diff = now - int(last_ts)
            if diff < REBIRTH_COOLDOWN:
                remaining = REBIRTH_COOLDOWN - diff
                days = remaining // 86400
                hours = (remaining % 86400) // 3600
                minutes = (remaining % 3600) // 60
                yield event.plain_result(
                    "⌛ 弃道重修冷却中\n"
                    "━━━━━━━━━━━━━━━\n"
                    f"距离下次重修还需：{days}天{hours}小时{minutes}分钟"
                )
                return

        if confirm_text.strip() != "确认":
            yield event.plain_result(
                "⚠️ 弃道重修将删除当前角色的所有数据，并无法撤回！\n"
                "限制：每7天只能重修一次，且必须在空闲状态、无贷款时使用。\n"
                "━━━━━━━━━━━━━━━\n"
                "若你已做好准备，请发送：\n"
                "弃道重修 确认"
            )
            return

        # 弃道重修视同离宗：回收宗门之宝归还宗门（sect_bound 功法随角色删除）
        reclaimed = []
        if self.sect_mgr and player.sect_id != 0:
            reclaimed = await self.sect_mgr.reclaim_sect_treasures(
                player.user_id, player.sect_id
            )

        await self.db.delete_player_cascade(player.user_id)
        await self.db.ext.set_system_config(key, str(now))

        reclaim_msg = ""
        if reclaimed:
            reclaim_msg = f"\n宗门之宝【{'、'.join(reclaimed)}】已归还宗门。"

        yield event.plain_result(
            "💀 你选择了弃道重修，旧生一切化为尘埃。\n"
            "━━━━━━━━━━━━━━━\n"
            "可立即使用「我要修仙」重新踏上仙途。\n"
            "（7天内不可再次重修）"
            f"{reclaim_msg}"
        )
