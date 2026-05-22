# -*- coding: utf-8 -*-
"""
跨平台工具模块 (重构自 platform_utils.py)
- Windows: 文件锁 msvcrt.locking
- Linux/macOS: 文件锁 fcntl.flock
"""

import os
import sys
import subprocess as sp
import time

# ─── 条件导入 ───────────────────────────────────────────
if sys.platform == "win32":
    import msvcrt

    def lock_file(fh, exclusive=True):
        msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK if exclusive else msvcrt.LK_NBLCK, 1)

    def unlock_file(fh):
        try:
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        except Exception:
            pass

    def try_lock_file(fh):
        try:
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except (OSError, IOError):
            return False

else:
    import fcntl

    def lock_file(fh, exclusive=True):
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)

    def unlock_file(fh):
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass

    def try_lock_file(fh):
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except (OSError, IOError):
            return False


# ─── 平台常量 ────────────────────────────────────────────
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")
IS_POSIX = os.name == "posix"

ADB_EXE_NAME = "adb.exe" if IS_WINDOWS else "adb"


# ─── 应用数据目录 ────────────────────────────────────────
def get_app_data_dir():
    """返回应用数据目录（打包后使用系统标准路径，开发模式使用当前目录）"""
    if getattr(sys, "frozen", False):
        if IS_MAC:
            base = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "WOA_AutoBot")
        elif IS_WINDOWS:
            base = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "WOA_AutoBot")
        else:
            base = os.path.join(os.path.expanduser("~"), ".woa_autobot")
    else:
        # 开发模式用当前脚本所在目录
        try:
            base = os.path.dirname(os.path.abspath(__file__))
        except NameError:
            base = os.getcwd()
        # 向上找到项目根目录（core 包的父目录）
        base = os.path.dirname(base)
    os.makedirs(base, exist_ok=True)
    return base


# ─── 子进程安全包装 ──────────────────────────────────────
def safe_subprocess_run(args, **kwargs):
    """跨平台安全的 subprocess.run 包装，自动处理 creationflags。"""
    if IS_WINDOWS and "creationflags" not in kwargs:
        kwargs["creationflags"] = CREATE_NO_WINDOW
    return sp.run(args, **kwargs)


def safe_popen_wait(proc, timeout=None):
    """安全等待子进程，处理超时（带超时 => terminate + wait）"""
    if timeout is None:
        return proc.wait()
    try:
        return proc.wait(timeout=timeout)
    except sp.TimeoutExpired:
        proc.terminate()
        try:
            return proc.wait(timeout=2)
        except sp.TimeoutExpired:
            proc.kill()
            return proc.wait()
