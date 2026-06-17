"""
筛选栏任务 — 使用 Enum 替代魔法字符串。

从 main_adb.py 迁移的筛选模式切换和类别栏处理逻辑。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from src.domain.models import (
    FilterButtonState,
    FilterMode,
    FILTER_MODE_STATES,
    NormalizedPoint,
    SidebarCategory,
)
from src.domain.tasks.base_task import BaseTask, TaskContext, TaskResult

logger = logging.getLogger(__name__)


# ─── 飞机类别枚举 ────────────────────────────────────────

class AircraftCategory(Enum):
    """飞机类别 — 替代原版魔法字符串。"""
    FAVORITES = "favorites"
    FLEET = "fleet"
    PLAYERS = "players"
    EVENT = "event"
    PASSENGER = "passenger"
    CARGO = "cargo"

    @property
    def label(self) -> str:
        labels = {
            self.FAVORITES: "❤️ 喜爱/合约",
            self.FLEET: "⚠️ 机队",
            self.PLAYERS: "🟢 其他玩家",
            self.EVENT: "🔵 活动飞机",
            self.PASSENGER: "✈️ 客机",
            self.CARGO: "📦 货机",
        }
        return labels.get(self, self.value)


# ─── 筛选按钮定义 ────────────────────────────────────────

@dataclass
class FilterButtonDef:
    """筛选按钮元数据。"""
    key: str
    label: str
    category: Optional[AircraftCategory] = None
    click_pos: NormalizedPoint = field(default_factory=lambda: NormalizedPoint(0, 0))
    tpl_on: str = ""
    tpl_off: str = ""


# 预定义筛选按钮 (归一化坐标 1600×900)
FILTER_BUTTON_DEFS: List[FilterButtonDef] = [
    FilterButtonDef("arrival", "进港",
                    click_pos=NormalizedPoint(1534 / 1600, 119 / 900),
                    tpl_on="filter_arrival_on.png", tpl_off="filter_arrival_off.png"),
    FilterButtonDef("ground", "机场内",
                    click_pos=NormalizedPoint(1534 / 1600, 191 / 900),
                    tpl_on="filter_ground_on.png", tpl_off="filter_ground_off.png"),
    FilterButtonDef("departure", "离港",
                    click_pos=NormalizedPoint(1537 / 1600, 265 / 900),
                    tpl_on="filter_departure_on.png", tpl_off="filter_departure_off.png"),
    FilterButtonDef("pending", "待处理",
                    click_pos=NormalizedPoint(1537 / 1600, 479 / 900),
                    tpl_on="filter_pending_on.png", tpl_off="filter_pending_off.png"),
]

# 按钮处理优先级
BUTTON_PRIORITY: Dict[str, int] = {"pending": 0, "ground": 1, "arrival": 2, "departure": 3}


# ─── 筛选任务 ────────────────────────────────────────────

class FilterTask(BaseTask):
    """筛选栏管理任务。

    职责：
    - 确保筛选按钮状态与目标模式一致
    - 管理类别栏切换
    - 不起飞模式策略判断
    """

    priority = 5  # 最高优先级 — 在所有其他任务之前执行
    name = "filter"

    def __init__(self):
        self._target_mode: FilterMode = FilterMode.MODE1_PENDING_ONLY
        self._category_enabled: Dict[AircraftCategory, bool] = {
            c: False for c in AircraftCategory
        }

    def set_target_mode(self, mode: FilterMode) -> None:
        """设置目标筛选模式。"""
        self._target_mode = mode
        logger.info(f"[FilterTask] 目标模式: {mode.value}")

    def enable_category(self, category: AircraftCategory, enabled: bool = True) -> None:
        """启用/禁用某个类别栏。"""
        self._category_enabled[category] = enabled

    def can_execute(self, context: TaskContext) -> bool:
        """筛选任务始终可执行（需在主界面）。"""
        return True

    def execute(self, context: TaskContext) -> TaskResult:
        """执行筛选修正。"""
        target_state = FILTER_MODE_STATES.get(self._target_mode, {})

        # TODO: 集成 Orchestrator 的 _ensure_filter_state 逻辑
        # 通过 matcher.match_button_state 检测各按钮状态
        # 与 target_state 比较，不匹配则循环修正

        return TaskResult(
            success=True,
            action_taken="filter_check",
            detail=f"目标模式: {self._target_mode.value}",
            next_task_delay=15.0,
        )

    # ── 类别栏辅助方法 ──

    @staticmethod
    def get_category_click_position(category: AircraftCategory) -> Optional[NormalizedPoint]:
        """根据类别获取点击坐标（归一化空间回退坐标）。"""
        positions = {
            AircraftCategory.FAVORITES: NormalizedPoint(1537 / 1600, 400 / 900),
            AircraftCategory.FLEET:     NormalizedPoint(1537 / 1600, 546 / 900),
            AircraftCategory.PLAYERS:   NormalizedPoint(1537 / 1600, 619 / 900),
            AircraftCategory.EVENT:     NormalizedPoint(1537 / 1600, 689 / 900),
            AircraftCategory.PASSENGER: NormalizedPoint(1537 / 1600, 759 / 900),
            AircraftCategory.CARGO:     NormalizedPoint(1537 / 1600, 829 / 900),
        }
        return positions.get(category)
