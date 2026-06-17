"""
应用配置 — Pydantic Settings 管理所有运行参数。

替换原项目的 config.json 硬编码读取 + 全局变量散布。
使用依赖注入：Orchestrator 在 __init__ 时接收 AppConfig 实例。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.domain.models import ScreenshotMethod


class AppSettings(BaseSettings):
    """WOA AutoBot 全局应用设置。

    所有字段可通过环境变量 WOA_<FIELD> 覆盖（如 WOA_ADB_PATH）。
    """

    model_config = SettingsConfigDict(
        env_prefix="WOA_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── ADB / 设备 ──
    adb_path: str = Field(
        default="adb",
        description="ADB 可执行文件路径。Windows 可用系统 PATH 中的 adb.exe。",
    )
    device_serial: str = Field(
        default="",
        description="目标设备序列号。为空时自动发现。",
    )
    screenshot_method: ScreenshotMethod = Field(
        default=ScreenshotMethod.ADB,
        description="截图方式: adb | nemu_ipc | droidcast",
    )

    # ── 路径 ──
    assets_dir: str = Field(
        default="assets",
        description="资源目录路径。",
    )
    icon_dir: str = Field(
        default="icon",
        description="模板图标目录路径。",
    )
    config_save_path: str = Field(
        default="config.json",
        description="用户配置保存路径。",
    )

    # ── 游戏视图 ──
    enable_2d_mode: bool = Field(
        default=True,
        description="使用 2D 视角（False=3D 视角）。",
    )
    ref_width: int = Field(default=1600, description="归一化参考宽度。")
    ref_height: int = Field(default=900, description="归一化参考高度。")

    # ── 筛选策略 ──
    enable_filter_stand_only_when_tower_open: bool = Field(
        default=True,
        description="塔台全开时仅处理停机位。",
    )
    enable_no_takeoff_mode: bool = Field(
        default=False,
        description="不起飞模式（仅降落+停机坪）。",
    )
    enable_category_processing: bool = Field(
        default=False,
        description="启用右侧类别栏切换处理。",
    )
    category_selection: Dict[str, bool] = Field(
        default_factory=lambda: {
            "favorites": False,
            "fleet": False,
            "players": False,
            "event": False,
            "passenger": False,
            "cargo": False,
        },
        description="类别栏选中状态。",
    )

    # ── GUI ──
    gui_theme: str = Field(default="dark", description="GUI 主题: dark | light | system")
    gui_color_theme: str = Field(default="blue", description="CustomTkinter 颜色主题。")
    gui_window_geometry: str = Field(default="900x700", description="窗口初始尺寸 WxH。")

    # ── 性能与调优 ──
    template_min_confidence: float = Field(
        default=0.42, ge=0.20, le=0.95,
        description="模板匹配默认最低置信度。",
    )
    screenshot_interval_ms: int = Field(
        default=500, ge=100, le=5000,
        description="截图最小间隔 (毫秒)。",
    )
    category_cycle_interval: float = Field(
        default=15.0,
        description="类别轮换间隔 (秒)。",
    )
    max_filter_rounds: int = Field(
        default=8, ge=3, le=20,
        description="筛选状态修正最大轮数。",
    )
    blind_click_max_attempts: int = Field(
        default=3, ge=1, le=5,
        description="盲点最大尝试次数。",
    )

    # ── 开发者选项 ──
    debug_screenshots: bool = Field(
        default=False,
        description="保存调试截图到 woa_debug/ 目录。",
    )
    debug_log_level: str = Field(
        default="INFO",
        description="日志级别: DEBUG | INFO | WARNING | ERROR",
    )

    # ── 分辨率后的路径 ──

    def resolve_adb_path(self) -> str:
        """解析 ADB 路径（含打包后的资源路径）。"""
        if self.adb_path and self.adb_path != "adb":
            if os.path.isfile(self.adb_path):
                return self.adb_path
        # 尝试打包后的 bundled 路径
        if getattr(sys, 'frozen', False):
            base = Path(sys._MEIPASS) if hasattr(sys, '_MEIPASS') else Path(sys.executable).parent
            exe_name = "adb.exe" if os.name == "nt" else "adb"
            bundled = base / "adb_tools" / exe_name
            if bundled.is_file():
                return str(bundled)
        return self.adb_path

    def resolve_icon_dir(self) -> str:
        """解析图标目录路径。"""
        if os.path.isabs(self.icon_dir):
            return self.icon_dir
        if getattr(sys, 'frozen', False):
            base = Path(sys._MEIPASS) if hasattr(sys, '_MEIPASS') else Path(sys.executable).parent
            return str(base / self.icon_dir)
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", self.icon_dir)
