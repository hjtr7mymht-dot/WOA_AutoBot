"""
领域模型 — 纯数据类，不依赖任何外部框架或硬件。

所有坐标使用归一化坐标 (0.0~1.0)，仅在 ADB 发送前转换为设备像素。
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, TypedDict


# ─── 坐标与几何 ──────────────────────────────────────────

@dataclass(frozen=True)
class NormalizedPoint:
    """归一化坐标点 (0.0~1.0)，原点为屏幕左上角。"""
    x: float
    y: float

    def to_device(self, width: int, height: int) -> Tuple[int, int]:
        """转为设备像素坐标。"""
        return (int(round(self.x * width)), int(round(self.y * height)))

    @classmethod
    def from_device(cls, px: int, py: int, width: int, height: int) -> "NormalizedPoint":
        """从设备像素坐标创建。"""
        return cls(px / width, py / height)


@dataclass(frozen=True)
class NormalizedRect:
    """归一化矩形区域。"""
    x: float
    y: float
    w: float
    h: float

    @property
    def center(self) -> NormalizedPoint:
        return NormalizedPoint(self.x + self.w / 2, self.y + self.h / 2)

    def to_device(self, width: int, height: int) -> Tuple[int, int, int, int]:
        return (
            int(round(self.x * width)),
            int(round(self.y * height)),
            int(round(self.w * width)),
            int(round(self.h * height)),
        )


# ─── 游戏实体 ────────────────────────────────────────────

class FlightType(enum.StrEnum):
    """航班类型。"""
    PASSENGER = "passenger"
    CARGO = "cargo"
    EVENT = "event"


class FlightStatus(enum.StrEnum):
    """航班状态。"""
    ARRIVAL = "arrival"      # 进港
    GROUND = "ground"        # 机场内
    DEPARTURE = "departure"  # 离港
    PENDING = "pending"      # 待处理


class StandStatus(enum.StrEnum):
    """停机位状态。"""
    VACANT = "vacant"
    OCCUPIED = "occupied"
    UNKNOWN = "unknown"


@dataclass
class Flight:
    """航班实体。"""
    flight_id: str = ""
    flight_type: FlightType = FlightType.PASSENGER
    status: FlightStatus = FlightStatus.PENDING
    stand_id: str = ""
    reward: int = 0
    remaining_time: float = 0.0


@dataclass
class Stand:
    """停机位实体。"""
    stand_id: str = ""
    status: StandStatus = StandStatus.UNKNOWN
    position: Optional[NormalizedPoint] = None


@dataclass
class Airport:
    """机场状态快照。"""
    stands: List[Stand] = field(default_factory=list)
    active_flights: List[Flight] = field(default_factory=list)
    tower_open: bool = False
    is_2d_view: bool = True


# ─── 筛选状态 ────────────────────────────────────────────

class FilterButtonState(TypedDict, total=False):
    """筛选按钮状态字典。"""
    arrival: Optional[bool]
    ground: Optional[bool]
    departure: Optional[bool]
    pending: Optional[bool]


class FilterMode(enum.StrEnum):
    """预定义筛选模式。"""
    MODE1_PENDING_ONLY = "mode1"       # 仅待处理
    MODE2_STAND_AND_PENDING = "mode2"  # 仅停机位 (机场内+待处理)


# 预定义模式的状态映射
FILTER_MODE_STATES: Dict[FilterMode, FilterButtonState] = {
    FilterMode.MODE1_PENDING_ONLY: {
        "arrival": False, "ground": False,
        "departure": False, "pending": True,
    },
    FilterMode.MODE2_STAND_AND_PENDING: {
        "arrival": False, "ground": True,
        "departure": False, "pending": True,
    },
}


# ─── 侧边栏类别 ──────────────────────────────────────────

class SidebarCategory(TypedDict):
    """侧边栏类别定义。"""
    key: str
    label: str
    icon_off: str          # 未选中图标文件名
    icon_on: str           # 选中图标文件名
    fallback_pos: Tuple[int, int]  # 归一化空间回退坐标
    verify_pos: Tuple[int, int]    # 像素验证坐标


# ─── 模板匹配结果 ────────────────────────────────────────

@dataclass
class MatchResult:
    """模板匹配结果。"""
    found: bool
    confidence: float = 0.0
    position: Optional[NormalizedPoint] = None
    template_name: str = ""
    scale: float = 1.0


# ─── ADB 设备信息 ────────────────────────────────────────

@dataclass
class DeviceInfo:
    """ADB 设备信息。"""
    serial: str
    model: str = ""
    resolution: Tuple[int, int] = (1600, 900)
    android_version: str = ""
    connection_type: str = "usb"  # usb | wifi | emulator
    is_connected: bool = False


class ScreenshotMethod(enum.StrEnum):
    """截图方式。"""
    ADB = "adb"
    NEMU_IPC = "nemu_ipc"
    UIAUTOMATOR2 = "uiautomator2"
    DROIDCAST = "droidcast"
