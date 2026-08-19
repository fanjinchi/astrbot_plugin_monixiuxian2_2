# models.py - 新增模型定义

import json
from dataclasses import dataclass
from enum import IntEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


class UserStatus(IntEnum):
    """用户状态枚举"""

    IDLE = 0  # 空闲
    CULTIVATING = 1  # 闭关中
    ADVENTURING = 2  # 历练中
    EXPLORING = 3  # 探索秘境中
    SECT_TASK = 4  # 宗门任务中

    @classmethod
    def get_name(cls, status: int) -> str:
        """获取状态名称"""
        names = {
            cls.IDLE: "空闲",
            cls.CULTIVATING: "闭关中",
            cls.ADVENTURING: "历练中",
            cls.EXPLORING: "探索秘境中",
            cls.SECT_TASK: "宗门任务中",
        }
        return names.get(status, "忙碌中")


@dataclass
class Sect:
    """宗门数据模型"""

    sect_id: int  # 宗门ID（主键）
    sect_name: str  # 宗门名称
    sect_owner: str  # 宗主用户ID
    sect_scale: int = 0  # 建设度
    sect_used_stone: int = 0  # 可用灵石
    sect_fairyland: int = 0  # 洞天福地等级
    sect_materials: int = 0  # 资材
    mainbuff: str = "0"  # 主修功法buff ID列表（JSON字符串）
    secbuff: str = "0"  # 辅修功法buff ID列表（JSON字符串）
    elixir_room_level: int = 0  # 丹房等级
    is_system: int = 0  # 是否系统默认宗门（0=玩家自建，1=系统势力）
    faction_id: str | None = None  # 关联 sect_factions.json 的宗门定义ID（仅系统宗门）
    status: str = "normal"  # 宗门状态（normal/damaged/rebuilding，二期毁灭重建消费）
    destruction_tier: str | None = None  # 毁灭档位（二期消费）

    def get_mainbuff_list(self) -> list[int]:
        """获取主修功法ID列表"""
        try:
            if self.mainbuff == "0" or not self.mainbuff:
                return []
            return (
                json.loads(self.mainbuff)
                if isinstance(self.mainbuff, str)
                else [self.mainbuff]
            )
        except Exception:
            return []

    def set_mainbuff_list(self, buff_list: list[int]):
        """设置主修功法ID列表"""
        self.mainbuff = json.dumps(buff_list, ensure_ascii=False) if buff_list else "0"

    def get_secbuff_list(self) -> list[int]:
        """获取辅修功法ID列表"""
        try:
            if self.secbuff == "0" or not self.secbuff:
                return []
            return (
                json.loads(self.secbuff)
                if isinstance(self.secbuff, str)
                else [self.secbuff]
            )
        except Exception:
            return []

    def set_secbuff_list(self, buff_list: list[int]):
        """设置辅修功法ID列表"""
        self.secbuff = json.dumps(buff_list, ensure_ascii=False) if buff_list else "0"


@dataclass
class BuffInfo:
    """Buff信息数据模型（用户装备的功法、法器等）"""

    id: int  # 主键
    user_id: str  # 用户ID
    main_buff: int = 0  # 主修功法ID
    sec_buff: int = 0  # 辅修功法ID
    faqi_buff: int = 0  # 法器buff ID
    fabao_weapon: int = 0  # 法宝武器ID
    armor_buff: int = 0  # 防具buff ID
    atk_buff: int = 0  # 永久攻击buff
    blessed_spot: int = 0  # 洞天福地等级
    sub_buff: int = 0  # 副buff


@dataclass
class Boss:
    """Boss数据模型"""

    boss_id: int  # Boss ID（主键）
    boss_name: str  # Boss名称
    boss_level: str  # Boss境界
    hp: int  # 血量
    max_hp: int  # 最大血量
    atk: int  # 攻击力
    defense: int = 0  # 防御力
    stone_reward: int = 0  # 灵石奖励
    create_time: int = 0  # 生成时间
    status: int = 1  # 状态（0已击败，1存活）


@dataclass
class Rift:
    """秘境数据模型"""

    rift_id: int  # 秘境ID（主键）
    rift_name: str  # 秘境名称
    rift_level: int  # 秘境等级
    required_level: int  # 需求境界
    rewards: str = "{}"  # 奖励配置（JSON字符串）

    def get_rewards(self) -> dict:
        """获取奖励字典"""
        try:
            return json.loads(self.rewards)
        except Exception:
            return {}

    def set_rewards(self, rewards_dict: dict):
        """设置奖励字典"""
        self.rewards = json.dumps(rewards_dict, ensure_ascii=False)


@dataclass
class ImpartInfo:
    """Impart (inheritance) info data model."""

    id: int  # Primary key
    user_id: str  # User ID
    impart_value: int = 0  # Accumulated impart value from PK wins
    claimed_tiers: str = "[]"  # JSON list of claimed tier numbers

    def get_claimed_tiers(self) -> list[int]:
        """Return the list of claimed tier numbers."""
        try:
            return json.loads(self.claimed_tiers)
        except json.JSONDecodeError:
            return []

    def set_claimed_tiers(self, tiers: list[int]):
        """Store the list of claimed tier numbers as a JSON string."""
        self.claimed_tiers = json.dumps(tiers, ensure_ascii=False)


@dataclass
class UserCd:
    """用户CD信息数据模型"""

    user_id: str  # 用户ID（主键）
    type: int = UserStatus.IDLE  # CD类型，参见 UserStatus 枚举
    create_time: int = 0  # 创建时间
    scheduled_time: int = 0  # 计划完成时间
    extra_data: str = "{}"  # 额外数据（JSON字符串，如秘境ID等）

    def get_extra_data(self) -> dict:
        """获取额外数据字典"""
        try:
            return json.loads(self.extra_data)
        except Exception:
            return {}

    def set_extra_data(self, data: dict):
        """设置额外数据"""
        self.extra_data = json.dumps(data, ensure_ascii=False)
