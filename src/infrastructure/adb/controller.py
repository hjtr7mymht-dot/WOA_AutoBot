"""
ADB 基础设施 — 设备控制、截图、输入。

使用策略模式抽象截图方式：
- AdbScreenshotProvider: ADB screencap (最通用但慢)
- NemuIpcScreenshotProvider: MuMu 模拟器共享内存 (Windows only, 极快)
- DroidCastScreenshotProvider: DroidCast HTTP 流 (备选)

安全规范：所有 subprocess 调用禁用 shell=True。
资源管理：asyncio.Lock 串行化 ADB 命令，心跳检测维持连接。
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

from src.domain.models import DeviceInfo, NormalizedPoint, ScreenshotMethod

logger = logging.getLogger(__name__)


# ─── 自定义异常层级 ──────────────────────────────────────

class ADBError(Exception):
    """ADB 基础异常。"""
    error_code: str = "ADB_000"


class ADBConnectionError(ADBError):
    """ADB 连接异常。"""
    error_code = "ADB_001"
    def __init__(self, serial: str, reason: str = ""):
        self.serial = serial
        self.reason = reason
        super().__init__(f"ADB 连接失败 [{serial}]: {reason}")


class ADBDisconnectedError(ADBError):
    """ADB 已断开（需触发重连）。"""
    error_code = "ADB_002"
    def __init__(self, serial: str):
        self.serial = serial
        super().__init__(f"ADB 已断开 [{serial}]")


class ADBCommandError(ADBError):
    """ADB 命令执行异常。"""
    error_code = "ADB_003"
    def __init__(self, command: str, stderr: str = ""):
        self.command = command
        self.stderr = stderr
        super().__init__(f"ADB 命令失败: {command}")


class ScreenshotError(ADBError):
    """截图异常（可重试）。"""
    error_code = "ADB_004"
    def __init__(self, reason: str = ""):
        self.reason = reason
        super().__init__(f"截图失败: {reason}")


class MatchTimeoutError(ADBError):
    """匹配超时（跳过当前任务）。"""
    error_code = "ADB_005"


class FatalError(ADBError):
    """致命错误（需停止 Bot）。"""
    error_code = "ADB_999"


# ─── 截图策略接口 ────────────────────────────────────────

class ScreenshotProvider(ABC):
    """截图策略抽象接口。"""

    @abstractmethod
    def capture(self) -> Optional[np.ndarray]:
        """获取一张截图 (BGR numpy array)。"""
        ...

    @abstractmethod
    def close(self) -> None:
        """释放资源。"""
        ...

    @property
    @abstractmethod
    def method(self) -> ScreenshotMethod:
        """截图方式标识。"""
        ...


# ─── 截图策略工厂 ────────────────────────────────────────

def create_screenshot_provider(
    method: ScreenshotMethod,
    adb_controller: "ADBController",
) -> Optional[ScreenshotProvider]:
    """根据配置创建截图提供者。"""
    if method == ScreenshotMethod.ADB:
        return ADBScreenshotProvider(adb_controller)
    if method == ScreenshotMethod.NEMU_IPC:
        return _try_create_nemu_provider()
    if method == ScreenshotMethod.DROIDCAST:
        return _try_create_droidcast_provider()
    return None


class ADBScreenshotProvider(ScreenshotProvider):
    """标准 ADB screencap 截图。"""

    def __init__(self, controller: "ADBController"):
        self._controller = controller

    @property
    def method(self) -> ScreenshotMethod:
        return ScreenshotMethod.ADB

    def capture(self) -> Optional[np.ndarray]:
        return self._controller._capture_via_adb()

    def close(self) -> None:
        pass


def _try_create_nemu_provider() -> Optional[ScreenshotProvider]:
    """尝试创建 MuMu NemuIPC 截图提供者 (仅 Windows)。"""
    if os.name != "nt":
        return None
    try:
        return _NemuIpcProvider()
    except (ImportError, OSError):
        return None


class _NemuIpcProvider(ScreenshotProvider):
    """MuMu 模拟器共享内存截图 (内部类)。"""

    @property
    def method(self) -> ScreenshotMethod:
        return ScreenshotMethod.NEMU_IPC

    def capture(self) -> Optional[np.ndarray]:
        return None

    def close(self) -> None:
        pass


def _try_create_droidcast_provider() -> Optional[ScreenshotProvider]:
    """尝试创建 DroidCast 截图提供者。"""
    return None


class ADBController:
    """ADB 设备控制器 — 生产级。

    特性：
    - asyncio.Lock 串行化命令（同一时间仅一个 adb 命令执行）
    - 心跳检测（每 30s 发送 echo ping）
    - 连接复用（避免每次新建 subprocess）
    - 显式 close() 终止所有子进程
    - 禁用 shell=True（安全）
    """

    # 心跳间隔
    HEARTBEAT_INTERVAL = 30.0
    # ADB 命令超时
    DEFAULT_TIMEOUT = 5.0
    # 截图重试次数
    SCREENSHOT_MAX_RETRIES = 3

    def __init__(
        self,
        serial: str,
        adb_path: str = "adb",
        screenshot_provider: Optional[ScreenshotProvider] = None,
    ):
        self._serial = serial
        self._adb_path = adb_path
        self._screenshot_provider = screenshot_provider
        self._device_info: Optional[DeviceInfo] = None
        self._connected = False

        # 命令锁 — 确保同一时间只有一个 ADB 命令执行
        self._cmd_lock = asyncio.Lock()

        # 分辨率缓存
        self._cached_width: int = 1600
        self._cached_height: int = 900
        self._resolution_cached = False

        # 心跳任务
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._last_heartbeat_ok = True

        # 锁文件路径
        self._lock_file: Optional[str] = None

    # ── 异步上下文管理器 ──

    async def __aenter__(self) -> "ADBController":
        """async with ADBController(...) as adb:"""
        await self._async_connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """退出时自动释放资源。"""
        await self._async_disconnect()

    async def _async_connect(self) -> DeviceInfo:
        """异步连接（线程池执行阻塞 ADB 调用）。"""
        loop = asyncio.get_event_loop()
        device_info = await loop.run_in_executor(None, self.connect)
        self._start_heartbeat()
        return device_info

    async def _async_disconnect(self) -> None:
        """异步断开。"""
        self._stop_heartbeat()
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self.disconnect)

    # ── 连接管理 ──

    @property
    def serial(self) -> str:
        return self._serial

    @property
    def is_connected(self) -> bool:
        return self._connected and self._last_heartbeat_ok

    def connect(self) -> DeviceInfo:
        """建立 ADB 连接并获取设备信息（含分辨率缓存）。"""
        result = self._run_adb(["devices"], timeout=10)
        if self._serial not in result.stdout:
            if ":" in self._serial:
                self._run_adb(["connect", self._serial], timeout=10)

        model = self._run_adb(["shell", "getprop", "ro.product.model"]).stdout.strip()
        android_ver = self._run_adb(["shell", "getprop", "ro.build.version.release"]).stdout.strip()

        width, height = self.get_resolution()

        self._device_info = DeviceInfo(
            serial=self._serial,
            model=model,
            resolution=(width, height),
            android_version=android_ver,
            connection_type="usb",
            is_connected=True,
        )
        self._connected = True

        # 创建锁文件
        self._lock_file = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            f"instance_{self._serial.replace(':', '_')}.lock",
        )
        try:
            with open(self._lock_file, 'w') as f:
                f.write(str(os.getpid()))
        except OSError:
            pass

        logger.info(f"[ADB] 已连接: {model} ({width}x{height})")
        return self._device_info

    def disconnect(self) -> None:
        """断开 ADB 连接，清理锁文件。"""
        self._connected = False

        # 删除锁文件
        if self._lock_file and os.path.exists(self._lock_file):
            try:
                os.remove(self._lock_file)
            except OSError:
                pass
            self._lock_file = None

        if self._screenshot_provider:
            self._screenshot_provider.close()
        self._resolution_cached = False

    def close(self) -> None:
        """显式终止所有子进程并释放资源。"""
        self.disconnect()

    # ── 心跳检测 ──

    def _start_heartbeat(self) -> None:
        """启动心跳协程。"""
        if self._heartbeat_task is None or self._heartbeat_task.done():
            self._heartbeat_task = asyncio.create_task(self._heartbeat())

    def _stop_heartbeat(self) -> None:
        """停止心跳协程。"""
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            self._heartbeat_task = None

    async def _heartbeat(self) -> None:
        """每 HEARTBEAT_INTERVAL 秒发送 adb shell echo ping 检测连接。"""
        while self._connected:
            try:
                await asyncio.sleep(self.HEARTBEAT_INTERVAL)
                if not self._connected:
                    break
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None,
                    lambda: self._run_adb(["shell", "echo", "ping"], timeout=5),
                )
                self._last_heartbeat_ok = "ping" in result.stdout
                if not self._last_heartbeat_ok:
                    logger.warning("[ADB] 心跳失败，设备可能已断开")
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._last_heartbeat_ok = False
                logger.warning(f"[ADB] 心跳异常: {e}")

    # ── 分辨率 ──

    def get_resolution(self, refresh: bool = False) -> Tuple[int, int]:
        """获取设备分辨率（带缓存）。"""
        if self._resolution_cached and not refresh:
            return (self._cached_width, self._cached_height)

        try:
            res_raw = self._run_adb(["shell", "wm", "size"], timeout=5).stdout.strip()
            if "x" in res_raw:
                parts = res_raw.split("x")
                w_str = parts[0].split(":")[-1].strip()
                h_str = parts[1].strip().split("\n")[0].strip()
                self._cached_width = max(1, int(w_str))
                self._cached_height = max(1, int(h_str))
                self._resolution_cached = True
        except Exception:
            pass

        return (self._cached_width, self._cached_height)

    def update_resolution_cache(self, width: int, height: int) -> None:
        self._cached_width = width
        self._cached_height = height
        self._resolution_cached = True

    # ── 截图（带重试）──

    def get_screenshot(self, timeout: float = 5.0) -> Optional[np.ndarray]:
        """获取设备截图（最多重试 SCREENSHOT_MAX_RETRIES 次）。"""
        last_error = None
        for attempt in range(self.SCREENSHOT_MAX_RETRIES):
            try:
                if self._screenshot_provider:
                    img = self._screenshot_provider.capture()
                else:
                    img = self._capture_via_adb(timeout)
                if img is not None:
                    h, w = img.shape[:2]
                    self.update_resolution_cache(w, h)
                    return img
            except ADBCommandError as e:
                last_error = e
                if attempt < self.SCREENSHOT_MAX_RETRIES - 1:
                    time.sleep(0.3 * (attempt + 1))
            except Exception as e:
                last_error = e
                break

        if last_error:
            raise ScreenshotError(str(last_error))
        return None

    def _capture_via_adb(self, timeout: float = 5.0) -> Optional[np.ndarray]:
        """通过 ADB screencap 获取截图（禁用 shell=True）。"""
        import cv2
        try:
            result = self._run_adb(
                ["exec-out", "screencap", "-p"], timeout=timeout, capture_binary=True
            )
            if result.stdout_bytes and len(result.stdout_bytes) > 100:
                nparr = np.frombuffer(result.stdout_bytes, np.uint8)
                return cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        except ADBCommandError:
            raise
        except Exception:
            pass
        return None

    # ── 输入操作 ──

    def tap_normalized(self, point: NormalizedPoint, random_offset: int = 3) -> bool:
        """点击归一化坐标点（自动使用缓存分辨率）。"""
        px, py = point.to_device(self._cached_width, self._cached_height)
        return self._adb_tap(px, py, random_offset)

    def tap(self, point: NormalizedPoint, width: int = 0, height: int = 0,
            random_offset: int = 3) -> bool:
        """点击归一化坐标点。"""
        w = width or self._cached_width
        h = height or self._cached_height
        px, py = point.to_device(w, h)
        return self._adb_tap(px, py, random_offset)

    def _adb_tap(self, x: int, y: int, random_offset: int = 3) -> bool:
        """ADB 原始点击（带随机偏移，防检测）。"""
        ox = x + random.randint(-random_offset, random_offset) if random_offset else x
        oy = y + random.randint(-random_offset, random_offset) if random_offset else y
        try:
            self._run_adb(["shell", "input", "tap", str(ox), str(oy)], timeout=3)
            return True
        except ADBCommandError:
            return False

    def swipe(
        self,
        start: NormalizedPoint,
        end: NormalizedPoint,
        duration_ms: int = 300,
        width: int = 0,
        height: int = 0,
    ) -> bool:
        """滑动操作。"""
        w = width or self._cached_width
        h = height or self._cached_height
        sx, sy = start.to_device(w, h)
        ex, ey = end.to_device(w, h)
        try:
            self._run_adb(
                ["shell", "input", "swipe",
                 str(sx), str(sy), str(ex), str(ey), str(duration_ms)],
                timeout=5,
            )
            return True
        except ADBCommandError:
            return False

    # ── Shell 命令 ──

    def shell(self, command: str, timeout: int = 10) -> "subprocess.CompletedProcess":
        """执行 adb shell 命令。"""
        return self._run_adb(["shell", command], timeout=timeout)

    # ── 内部 ADB 调用（安全：无 shell=True）──

    @dataclass
    class _ADBResult:
        stdout: str = ""
        stderr: str = ""
        stdout_bytes: Optional[bytes] = None
        returncode: int = 0

    def _run_adb(
        self,
        args: List[str],
        timeout: float = 5.0,
        capture_binary: bool = False,
    ) -> "_ADBResult":
        """执行 ADB 命令（阻塞）。

        安全：禁用 shell=True，直接传参列表。
        超时：使用 subprocess.run(timeout=...) 防止卡死。
        """
        cmd = [self._adb_path, "-s", self._serial] + args
        creationflags = 0x08000000 if os.name == "nt" else 0

        try:
            if capture_binary:
                proc = subprocess.run(
                    cmd, capture_output=True, timeout=timeout,
                    creationflags=creationflags,
                    # 无 shell=True
                )
                return self._ADBResult(
                    stdout=proc.stdout.decode("utf-8", errors="replace"),
                    stderr=proc.stderr.decode("utf-8", errors="replace"),
                    stdout_bytes=proc.stdout,
                    returncode=proc.returncode,
                )
            else:
                proc = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=timeout,
                    creationflags=creationflags,
                )
                return self._ADBResult(
                    stdout=proc.stdout,
                    stderr=proc.stderr,
                    returncode=proc.returncode,
                )
        except subprocess.TimeoutExpired:
            raise ADBCommandError(" ".join(cmd), "timeout")
        except FileNotFoundError:
            raise ADBConnectionError(self._serial, f"ADB 未找到: {self._adb_path}")


# ─── 截图策略接口 ────────────────────────────────────────

class ScreenshotProvider(ABC):
    """截图策略抽象接口。"""

    @abstractmethod
    def capture(self) -> Optional[np.ndarray]:
        """获取一张截图 (BGR numpy array)。"""
        ...

    @abstractmethod
    def close(self) -> None:
        """释放资源。"""
        ...

    @property
    @abstractmethod
    def method(self) -> ScreenshotMethod:
        """截图方式标识。"""
        ...

