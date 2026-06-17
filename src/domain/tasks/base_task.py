"""
任务抽象基类 — 策略模式的核心。

所有具体任务（除冰、起飞、维修等）均继承 BaseTask。
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from src.domain.models import Airport, Flight, MatchResult


@dataclass
class TaskContext:
    """任务执行上下文 — 由 Orchestrator 注入。"""
    airport: Airport
    screenshot: Any = None           # numpy ndarray
    device_width: int = 1600
    device_height: int = 900
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskResult:
    """任务执行结果。"""
    success: bool
    action_taken: str = ""
    detail: str = ""
    next_task_delay: float = 0.5       # 建议下次检查间隔 (秒)
    context: Optional[TaskContext] = None


class BaseTask(ABC):
    """任务抽象基类。

    子类只需实现：
    - can_execute(context) → bool
    - execute(context) → TaskResult
    """

    # 任务优先级（越小越优先）
    priority: int = 100

    # 任务名称（用于日志）
    name: str = "base_task"

    @abstractmethod
    def can_execute(self, context: TaskContext) -> bool:
        """判断当前上下文是否满足任务执行条件。"""
        ...

    @abstractmethod
    def execute(self, context: TaskContext) -> TaskResult:
        """执行任务并返回结果。"""
        ...

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} priority={self.priority}>"


class DeiceTask(BaseTask):
    """除冰任务。"""

    priority = 10
    name = "deice"

    def can_execute(self, context: TaskContext) -> bool:
        # TODO: 实现除冰检测逻辑
        return False

    def execute(self, context: TaskContext) -> TaskResult:
        # TODO: 实现除冰执行逻辑
        return TaskResult(success=False, action_taken="deice_skip")


class TakeoffTask(BaseTask):
    """起飞任务。"""

    priority = 20
    name = "takeoff"

    def can_execute(self, context: TaskContext) -> bool:
        # TODO: 实现起飞检测逻辑
        return False

    def execute(self, context: TaskContext) -> TaskResult:
        # TODO: 实现起飞执行逻辑
        return TaskResult(success=False, action_taken="takeoff_skip")


class ApproachTask(BaseTask):
    """进港/分配停机位任务。"""

    priority = 15
    name = "approach"

    def can_execute(self, context: TaskContext) -> bool:
        # TODO: 实现进港检测逻辑
        return False

    def execute(self, context: TaskContext) -> TaskResult:
        # TODO: 实现进港执行逻辑
        return TaskResult(success=False, action_taken="approach_skip")
