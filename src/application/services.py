"""
BotOrchestrator — 应用层核心编排器。

职责：
- 协调 ADB 设备、CV 识别、任务执行的中央调度器
- 管理筛选模式 (mode1/mode2/mode3) 的检测与切换
- 管理视角模式 (2D/3D) 的检测与切换
- 管理右侧类别栏的轮换处理
- 通过 queue.Queue 向 GUI 发送日志/状态信号

所有 ADB 阻塞调用通过 asyncio.run_in_executor 在线程池中执行。
"""

from __future__ import annotations

import asyncio
import logging
import queue
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import numpy as np

from src.domain.models import (
    Airport,
    FilterButtonState,
    FilterMode,
    FILTER_MODE_STATES,
    FlightStatus,
    MatchResult,
    NormalizedPoint,
    NormalizedRect,
    SidebarCategory,
)
from src.domain.tasks.base_task import BaseTask, TaskContext, TaskResult
from src.infrastructure.adb.controller import ADBController, ADBConnectionError, ADBDisconnectedError, ScreenshotError, FatalError
from src.infrastructure.cv.matcher import (
    MultiScaleTemplateMatcher,
    ResolutionAdapter,
    RingSampler,
    get_confidence_threshold,
)
from src.application.config import AppSettings

logger = logging.getLogger(__name__)


# ─── GUI 信号 ─────────────────────────────────────────────

@dataclass
class BotSignal:
    """从后台线程发送到 GUI 的信号。"""
    type: str                     # "log" | "status" | "error" | "stats" | "heartbeat"
    message: str = ""
    level: str = "INFO"           # DEBUG | INFO | WARNING | ERROR
    error_code: str = ""          # 错误码：ADB_001, CV_001, BOT_001 等
    data: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.data is None:
            self.data = {}


# ─── 筛选按钮定义 ────────────────────────────────────────

@dataclass
class FilterButton:
    """单个筛选按钮的元数据。"""
    key: str
    label: str
    click_pos: NormalizedPoint      # 归一化点击坐标
    tpl_on: str                     # 选中模板文件名
    tpl_off: str                    # 未选中模板文件名


# ─── Orchestrator ────────────────────────────────────────

class BotOrchestrator:
    """WOA AutoBot 核心编排器。

    使用方式：
        settings = AppSettings()
        orchestrator = BotOrchestrator(settings, signal_queue)
        await orchestrator.start()
    """

    # 筛选按钮定义 (归一化坐标 1600×900)
    FILTER_BUTTONS: List[FilterButton] = [
        FilterButton("arrival",   "进港",   NormalizedPoint(1534 / 1600, 119 / 900),
                    "filter_arrival_on.png",   "filter_arrival_off.png"),
        FilterButton("ground",    "机场内", NormalizedPoint(1534 / 1600, 191 / 900),
                    "filter_ground_on.png",    "filter_ground_off.png"),
        FilterButton("departure", "离港",   NormalizedPoint(1537 / 1600, 265 / 900),
                    "filter_departure_on.png", "filter_departure_off.png"),
        FilterButton("pending",   "待处理", NormalizedPoint(1537 / 1600, 479 / 900),
                    "filter_pending_on.png",   "filter_pending_off.png"),
    ]

    # 按钮处理优先级
    BUTTON_PRIORITY = {"pending": 0, "ground": 1, "arrival": 2, "departure": 3}

    def __init__(
        self,
        settings: AppSettings,
        signal_queue: queue.Queue,
    ):
        self.settings = settings
        self.signal_queue = signal_queue

        # 基础设施（延迟初始化）
        self._adb: Optional[ADBController] = None
        self._matcher: Optional[MultiScaleTemplateMatcher] = None
        self._resolution: Optional[ResolutionAdapter] = None

        # 运行状态
        self._running = False
        self._paused = False

        # 机场状态缓存
        self._airport = Airport()
        self._tower_active_slots: List[bool] = [False] * 7
        self._tower_all_open_count = 0
        self._tower_disabled = False

        # 筛选状态缓存
        self._filter_mode: Optional[FilterMode] = None
        self._btn_calibration: Dict[str, Dict[str, float]] = {}  # 亮度校准缓存

        # 坐标校准
        self._pos_offset_x = 0.0
        self._pos_offset_y = 0.0
        self._pos_calibrated = False

        # 侧边栏
        self._category_index = -1
        self._next_category_switch = 0.0

        # 统计
        self._stat_approach = 0
        self._stat_depart = 0
        # 任务统计（成功率、平均耗时）
        self._task_stats: Dict[str, Dict[str, Any]] = {}
        # 连续失败计数（用于自动暂停）
        self._consecutive_failures = 0
        self._max_consecutive_failures = 5
        # 指数退避参数
        self._retry_count = 0
        self._max_retry_delay = 60.0  # 最大退避延迟 (秒)

    # ── 统计查询 ──

    @property
    def stats(self) -> Dict[str, Any]:
        """返回运行统计（供 GUI 查询）。"""
        return {
            "approach": self._stat_approach,
            "depart": self._stat_depart,
            "consecutive_failures": self._consecutive_failures,
            "retry_count": self._retry_count,
            "task_stats": dict(self._task_stats),
            "adb_connected": self._adb.is_connected if self._adb else False,
            "cache_size": self._matcher.cache_size if self._matcher else 0,
            "bench_avg_ms": self._matcher.get_last_benchmark_avg() if self._matcher else 0.0,
        }

    def _record_task(self, task_name: str, success: bool, elapsed_ms: float) -> None:
        """记录任务执行统计。"""
        if task_name not in self._task_stats:
            self._task_stats[task_name] = {"success": 0, "fail": 0, "total_ms": 0.0, "count": 0}
        s = self._task_stats[task_name]
        if success:
            s["success"] += 1
            self._consecutive_failures = 0
        else:
            s["fail"] += 1
            self._consecutive_failures += 1
        s["total_ms"] += elapsed_ms
        s["count"] += 1

    # ── 生命周期 ──

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self) -> None:
        """启动 Bot 主循环（含 try-except-finally 资源保护）。"""
        self._running = True
        self._emit("status", "Bot 启动中...")
        self._emit("log", "[CV] 初始化模板匹配器...")

        # ── 初始化硬件 ──
        try:
            await self._init_device()
        except ADBConnectionError as e:
            self._emit("error", f"设备连接失败: {e}")
            self._running = False
            return

        # ── 初始化 CV ──
        icon_dir = self.settings.resolve_icon_dir()
        self._matcher = MultiScaleTemplateMatcher(icon_dir)
        self._resolution = ResolutionAdapter(
            self.settings.ref_width, self.settings.ref_height
        )
        self._emit("log", "[CV] 模板匹配器就绪")

        # ── 初始化任务队列 ──
        from src.domain.tasks.deice_task import DeiceTask
        from src.domain.tasks.filter_task import FilterTask
        self._tasks: List[BaseTask] = [
            FilterTask(),
            DeiceTask(),
        ]
        self._emit("status", "Bot 运行中")

        # ── 主循环（含指数退避 + 自动暂停）──
        try:
            while self._running:
                try:
                    await self._tick()
                    self._retry_count = 0  # 成功后重置退避
                except asyncio.CancelledError:
                    self._emit("log", "Bot 任务被取消")
                    break
                except ADBDisconnectedError as e:
                    self._emit("error", f"ADB 已断开: {e}", "ADB_002")
                    self._emit("log", "尝试重连 ADB...")
                    try:
                        await self._init_device()
                        self._emit("log", "ADB 重连成功 ✅")
                        self._retry_count = 0
                    except ADBConnectionError:
                        self._emit("error", "ADB 重连失败，Bot 停止", "ADB_999")
                        break
                except ScreenshotError as e:
                    self._retry_count += 1
                    delay = min(2.0 ** self._retry_count, self._max_retry_delay)
                    self._emit("log", f"截图失败 (重试 {self._retry_count}，{delay:.0f}s 后重试)")
                    await asyncio.sleep(delay)
                except FatalError as e:
                    self._emit("error", f"致命错误: {e}", "ADB_999")
                    break
                except Exception as e:
                    logger.exception("主循环异常")
                    self._retry_count += 1
                    delay = min(2.0 ** self._retry_count, self._max_retry_delay)
                    self._emit("error", f"循环异常 (重试{self._retry_count}): {e}")
                    await asyncio.sleep(delay)

                # 连续失败自动暂停
                if self._consecutive_failures >= self._max_consecutive_failures:
                    self._emit("error",
                        f"连续 {self._consecutive_failures} 次任务失败，自动暂停",
                        "BOT_001")
                    self._paused = True
                    self._emit("status", "⏸️ 已自动暂停（连续任务失败）")
        finally:
            await self._cleanup()
            self._emit("status", "Bot 已停止")

    def stop(self) -> None:
        """停止 Bot（线程安全）。"""
        self._running = False
        self._emit("status", "Bot 停止中...")

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    # ── 主循环 ──

    async def _tick(self) -> None:
        """单次主循环迭代。按优先级执行：筛选检查 → 除冰 → 起飞 → 进港。"""
        if self._paused:
            await asyncio.sleep(0.5)
            return

        # 1. 获取截图（asyncio.wait_for 超时保护）
        try:
            screen = await asyncio.wait_for(self._capture_screen(), timeout=8.0)
        except asyncio.TimeoutError:
            self._emit("error", "截图超时 (8s)，跳过本轮")
            return

        if screen is None:
            await asyncio.sleep(1.0)
            return

        # 2. 确保在主界面
        if not await self._ensure_main_interface(screen):
            await asyncio.sleep(2.0)
            return

        # 3. 确保视角模式
        await self._ensure_view_mode(screen)

        # 4. 确保筛选菜单展开 + 修正筛选状态
        screen = await self._ensure_filter_menu_open()
        if screen is not None:
            await self._ensure_filter_state(screen)

        # 5. 按优先级执行任务
        context = TaskContext(
            airport=self._airport,
            screenshot=screen,
            device_width=self._resolution.device_resolution[0],
            device_height=self._resolution.device_resolution[1],
        )

        for task in sorted(self._tasks, key=lambda t: t.priority):
            if not self._running:
                break
            try:
                if task.can_execute(context):
                    self._emit("log", f"[Task] 执行: {task.name}")
                    result = task.execute(context)
                    if result.success:
                        self._emit("log", f"[Task] ✓ {task.name}: {result.detail}")
                    await asyncio.sleep(result.next_task_delay)
            except Exception as e:
                self._emit("error", f"[Task] {task.name} 异常: {e}")

        # 6. 发送统计
        self._emit("stats", data={
            "approach": self._stat_approach,
            "depart": self._stat_depart,
        })

        await asyncio.sleep(0.3)

    # ── 硬件初始化 ──

    async def _init_device(self) -> None:
        """异步初始化 ADB 设备连接。"""
        loop = asyncio.get_event_loop()

        # ADB 连接在线程池执行
        adb_path = self.settings.resolve_adb_path()
        serial = self.settings.device_serial

        self._adb = ADBController(serial, adb_path)

        def _connect():
            return self._adb.connect()

        device_info = await loop.run_in_executor(None, _connect)
        self._resolution.update_device_resolution(*device_info.resolution)
        self._emit("log", f"设备已连接: {device_info.model} "
                  f"{device_info.resolution[0]}×{device_info.resolution[1]}")

    # ── 截图 ──

    async def _capture_screen(self) -> Optional[np.ndarray]:
        """异步获取截图（ADB 调用在线程池）。"""
        loop = asyncio.get_event_loop()
        screen = await loop.run_in_executor(None, self._adb.get_screenshot)
        if screen is not None and self._resolution:
            screen = self._resolution.normalize_screenshot(screen)
        return screen

    # ── 主界面检测 ──

    async def _ensure_main_interface(self, screen: np.ndarray) -> bool:
        """确保当前在主界面（非弹窗/非领奖界面）。"""
        result = self._matcher.match(
            screen, "main_interface.png",
            min_confidence=0.75,
        )
        return result.found

    # ── 视角模式 ──

    async def _ensure_view_mode(self, screen: np.ndarray) -> None:
        """确保 2D/3D 视角模式正确。"""
        vx, vy = 1162, 44  # 2D 按钮 (归一化空间)
        v3x, v3y = 1204, 44  # 3D 按钮

        margin = 32
        roi = (vx - margin, vy - margin, margin * 2, margin * 2)

        # 多尺度模板匹配
        is_2d = self._matcher.match_button_state(
            screen, "2D_on.png", "2D_off.png", roi=roi,
            min_confidence=0.35,
        )

        if is_2d is None:
            # 模板匹配失败 → 双环采样亮度回退
            is_2d = self._matcher.detect_by_brightness(screen, vx, vy)
            if is_2d is None:
                return

        want_2d = self.settings.enable_2d_mode
        if is_2d == want_2d:
            return

        # 需要切换
        if want_2d:
            self._emit("log", "🖥️ [视角] 切换至 2D...")
            await self._tap_device(vx, vy)
        else:
            self._emit("log", "🖥️ [视角] 切换至 3D...")
            await self._tap_device(v3x, v3y)

    # ── 筛选菜单 ──

    async def _ensure_filter_menu_open(self) -> Optional[np.ndarray]:
        """确保筛选菜单已展开。"""
        mx, my = 1537, 37
        for _ in range(6):
            screen = await self._capture_screen()
            if screen is None:
                return None

            # 三重检测
            is_open = self._matcher.detect_by_brightness(screen, mx, my)
            if is_open is not None and is_open:
                return screen
            if is_open is None:
                # 模板兜底
                result = self._matcher.match(
                    screen, "filter_menu_open.png",
                    roi=(mx - 16, my - 16, 32, 32),
                    min_confidence=0.7,
                )
                if result.found:
                    return screen

            await self._tap_device(mx, my)
            await asyncio.sleep(0.3)

        return await self._capture_screen()

    # ── 筛选状态 ──

    async def _ensure_filter_state(self, screen: np.ndarray) -> None:
        """检测并修正筛选状态。"""
        # 检测当前状态
        current_state = self._detect_filter_state(screen)

        # 确定目标模式
        tower_all_open = all(self._tower_active_slots)
        no_takeoff = self.settings.enable_no_takeoff_mode

        if no_takeoff:
            target = FilterMode.MODE2_STAND_AND_PENDING
        elif tower_all_open and self.settings.enable_filter_stand_only_when_tower_open:
            target = FilterMode.MODE2_STAND_AND_PENDING
        elif not any(self._tower_active_slots) and not self._tower_disabled:
            target = FilterMode.MODE1_PENDING_ONLY
            self._tower_disabled = True
        else:
            # 保持当前或默认
            target = self._filter_mode or FilterMode.MODE1_PENDING_ONLY

        target_state = FILTER_MODE_STATES[target]

        # 检查是否匹配
        if self._filter_state_matches(current_state, target_state):
            self._filter_mode = target
            return

        # 不匹配 → 修正
        self._emit("log", f"📋 [筛选] 修正至模式: {target.value}")
        await self._apply_filter_state(target_state)
        self._filter_mode = target

    def _detect_filter_state(self, screen: np.ndarray) -> FilterButtonState:
        """检测所有筛选按钮状态。"""
        state: FilterButtonState = {}
        for btn in self.FILTER_BUTTONS:
            px, py = int(btn.click_pos.x * 1600), int(btn.click_pos.y * 900)
            margin = 32 if btn.key == "pending" else 24
            roi = (px - margin, py - margin, margin * 2, margin * 2)
            result = self._matcher.match_button_state(
                screen, btn.tpl_on, btn.tpl_off, roi=roi,
            )
            if result is None:
                result = self._matcher.detect_by_brightness(screen, px, py)
            state[btn.key] = result
        return state

    def _filter_state_matches(
        self, state: FilterButtonState, expected: FilterButtonState
    ) -> bool:
        """检查当前状态是否匹配期望。"""
        has_known = False
        unknown_required = False
        for key, want in expected.items():
            current = state.get(key)
            if current is None:
                if key == "pending" or want is not None:
                    unknown_required = True
                continue
            has_known = True
            if current != want:
                return False
        if unknown_required:
            return False
        return has_known

    async def _apply_filter_state(
        self, expected: FilterButtonState, max_rounds: int = 8
    ) -> None:
        """循环修正筛选状态。"""
        for _round in range(max_rounds):
            screen = await self._capture_screen()
            if screen is None:
                return

            all_ok = True
            sorted_btns = sorted(
                self.FILTER_BUTTONS,
                key=lambda b: self.BUTTON_PRIORITY.get(b.key, 99),
            )

            for btn in sorted_btns:
                want = expected.get(btn.key)
                if want is None:
                    continue

                px, py = int(btn.click_pos.x * 1600), int(btn.click_pos.y * 900)
                margin = 32 if btn.key == "pending" else 24
                roi = (px - margin, py - margin, margin * 2, margin * 2)
                current = self._matcher.match_button_state(
                    screen, btn.tpl_on, btn.tpl_off, roi=roi,
                )

                if current is None:
                    # 盲点重试
                    for blind_i in range(self.settings.blind_click_max_attempts):
                        self._emit("log", f"📋 [筛选] ⚠️ {btn.label} 盲点 {blind_i+1}/{self.settings.blind_click_max_attempts}")
                        await self._tap_device(px, py)
                        await asyncio.sleep(0.3)
                        screen2 = await self._capture_screen()
                        if screen2 is None:
                            break
                        current2 = self._matcher.match_button_state(
                            screen2, btn.tpl_on, btn.tpl_off, roi=roi,
                        )
                        if current2 is not None:
                            if current2 != want:
                                await self._tap_device(px, py)
                                await asyncio.sleep(0.2)
                            break
                    else:
                        all_ok = False
                    continue

                if current != want:
                    await self._tap_device(px, py)
                    await asyncio.sleep(0.2)
                    all_ok = False
                    screen = await self._capture_screen()
                    if screen is None:
                        return

            if all_ok:
                return

    # ── 设备交互 ──

    async def _tap_device(self, x: int, y: int) -> None:
        """异步设备点击（归一化空间坐标）。"""
        point = NormalizedPoint(x / 1600, y / 900)
        loop = asyncio.get_event_loop()
        w, h = self._resolution.device_resolution
        await loop.run_in_executor(None, self._adb.tap, point, w, h)

    # ── 清理 ──

    async def _cleanup(self) -> None:
        if self._adb:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._adb.disconnect)

    # ── 信号发送 ──

    def _emit(self, type_: str, message: str = "", level: str = "INFO",
              error_code: str = "", data: Dict[str, Any] = None) -> None:
        """向 GUI 发送信号（非阻塞）。"""
        try:
            self.signal_queue.put_nowait(BotSignal(
                type=type_, message=message, level=level,
                error_code=error_code, data=data or {},
            ))
        except queue.Full:
            pass
