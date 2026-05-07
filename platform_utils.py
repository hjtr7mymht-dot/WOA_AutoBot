# -*- coding: utf-8 -*-
"""
跨平台工具模块
- Windows: 使用 msvcrt.locking
- Linux/macOS: 使用 fcntl.flock
"""

import os
import sys

if sys.platform == "win32":
    import msvcrt

    def lock_file(fh, exclusive=True):
        """锁定文件句柄 (Windows)"""
        msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK if exclusive else msvcrt.LK_NBLCK, 1)

    def unlock_file(fh):
        """解锁文件句柄 (Windows)"""
        try:
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        except Exception:
            pass

    def try_lock_file(fh):
        """非阻塞尝试锁定 (Windows)"""
        try:
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except (OSError, IOError):
            return False

else:
    import fcntl

    def lock_file(fh, exclusive=True):
        """锁定文件句柄 (Unix)"""
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)

    def unlock_file(fh):
        """解锁文件句柄 (Unix)"""
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass

    def try_lock_file(fh):
        """非阻塞尝试锁定 (Unix)"""
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except (OSError, IOError):
            return False


# 便捷常量
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")
IS_POSIX = os.name == "posix"

# 跨平台 ADB 可执行文件名
ADB_EXE_NAME = "adb.exe" if IS_WINDOWS else "adb"


def get_adb_bundled_path(base_dir=None):
    """获取打包/开发环境中内置 adb 的完整路径"""
    if base_dir is None:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, "adb_tools", ADB_EXE_NAME)


def safe_subprocess_run(args, **kwargs):
    """跨平台安全的 subprocess.run 包装，自动处理 creationflags"""
    import subprocess as sp
    if IS_WINDOWS and "creationflags" not in kwargs:
        kwargs["creationflags"] = CREATE_NO_WINDOW
    return sp.run(args, **kwargs)
