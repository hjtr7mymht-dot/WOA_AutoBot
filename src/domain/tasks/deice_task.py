"""
除冰任务 — 从 main_adb.py 迁移的除冰/维修逻辑。

使用 @dataclass 定义识别区域，不硬编码坐标。
通过依赖注入接收 ADBController 和 MultiScaleTemplateMatcher。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from src.domain.models import MatchResult, NormalizedPoint, NormalizedRect
from src.domain.tasks.base_task import BaseTask, TaskContext, TaskResult

logger = logging.getLogger(__name__)


# ─── 除冰任务相关区域定义 ─────────────────────────────────

@dataclass(frozen=True)
class DeiceRegions:
    """除冰任务中涉及的模板和坐标区域（归一化空间 1600×900）。"""
    # 除冰按钮模板
    ice_button_template: str = "start_ice.png"
    # 维修按钮模板
    repair_button_template: str = "start_repair.png"
    # 通用启动按钮
    general_button_template: str = "start_general.png"
    # 底部操作区 ROI (用于查找按钮)
    bottom_action_roi: NormalizedRect = field(default_factory=lambda:
        NormalizedRect(20 / 1600, 750 / 900, 340 / 1600, 130 / 900))
    # 除冰/维修完成确认
    done_ice_template: str = "ground_support_done.png"
    done_repair_template: str = "go_repair.png"
    # 关闭按钮
    close_x: NormalizedPoint = field(default_factory=lambda:
        NormalizedPoint(1153 / 1600, 181 / 900))


# ─── 除冰任务 ────────────────────────────────────────────

class DeiceTask(BaseTask):
    """除冰/维修任务。

    检测屏幕上是否有待除冰或待维修的飞机，
    找到后点击对应按钮并等待完成。
    """

    priority = 10
    name = "deice"

    def __init__(self, regions: Optional[DeiceRegions] = None):
        self.regions = regions or DeiceRegions()

    def can_execute(self, context: TaskContext) -> bool:
        """检查是否有待除冰/维修的任务。"""
        # 检查 pending_ice 或 pending_repair 模板
        # TODO: 集成原版 pending_ice.png / pending_repair.png 检测
        return True  # 骨架 — 需要实际模板匹配

    def execute(self, context: TaskContext) -> TaskResult:
        """执行除冰任务。"""
        # TODO: 完整迁移原版除冰逻辑
        # 1. 检测 pending_ice.png
        # 2. 点击任务，等待 start_ice.png
        # 3. 点击 start_ice.png
        # 4. 等待 ground_support_done.png
        return TaskResult(
            success=False,
            action_taken="deice_skip",
            detail="除冰任务骨架 — 待实现具体模板匹配",
        )
