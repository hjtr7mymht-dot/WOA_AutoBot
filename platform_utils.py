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


def get_app_data_dir():
    """返回应用数据目录（打包后使用系统标准路径，开发模式使用当前目录）"""
    import sys as _sys
    if getattr(_sys, 'frozen', False):
        if IS_MAC:
            base = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "WOA_AutoBot")
        elif IS_WINDOWS:
            base = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "WOA_AutoBot")
        else:
            base = os.path.join(os.path.expanduser("~"), ".woa_autobot")
    else:
        base = os.path.dirname(os.path.abspath(__import__('sys').argv[0] or __file__)) if '__file__' in dir() else os.getcwd()
    os.makedirs(base, exist_ok=True)
    return base


def get_adb_bundled_path(base_dir=None):
    """获取打包/开发环境中内置 adb 的完整路径"""
    if base_dir is None:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, "adb_tools", ADB_EXE_NAME)


def safe_subprocess_run(args, **kwargs):
    """跨平台安全的 subprocess.run 包装，自动处理 creationflags。
    在 PyInstaller 冻结环境中避免 communicate()/select() GIL 崩溃。"""
    import subprocess as sp
    import sys as _sys
    import threading as _threading
    import time as _time
    if IS_WINDOWS and "creationflags" not in kwargs:
        kwargs["creationflags"] = CREATE_NO_WINDOW

    frozen = bool(getattr(_sys, 'frozen', False))
    # 冻结环境 + macOS：避免 communicate()/select() GIL 崩溃
    if frozen and not IS_WINDOWS and kwargs.get('stdout') == sp.PIPE:
        timeout_val = kwargs.pop('timeout', None)
        proc = sp.Popen(args, **kwargs)
        # 在线程中读取 stdout/stderr，避免 select() GIL 崩溃
        _out, _err = [], []
        _out_lock = _threading.Lock()
        _err_lock = _threading.Lock()

        def _read_stdout():
            try:
                while True:
                    chunk = os.read(proc.stdout.fileno(), 65536)
                    if not chunk:
                        break
                    with _out_lock:
                        _out.append(chunk)
            except Exception:
                pass

        def _read_stderr():
            try:
                while True:
                    chunk = os.read(proc.stderr.fileno(), 65536)
                    if not chunk:
                        break
                    with _err_lock:
                        _err.append(chunk)
            except Exception:
                pass

        t_out = _threading.Thread(target=_read_stdout, daemon=True)
        t_err = _threading.Thread(target=_read_stderr, daemon=True)
        t_out.start()
        t_err.start()

        try:
            deadline = _time.time() + timeout_val if timeout_val else None
            while proc.poll() is None:
                if deadline and _time.time() >= deadline:
                    proc.kill()
                    raise sp.TimeoutExpired(args, timeout_val)
                _time.sleep(0.02)
            t_out.join(timeout=1.0)
            t_err.join(timeout=1.0)
        except sp.TimeoutExpired:
            proc.kill()
            raise
        with _out_lock:
            stdout = b''.join(_out)
        with _err_lock:
            stderr = b''.join(_err)
        return sp.CompletedProcess(args, proc.returncode, stdout=stdout, stderr=stderr)

    return sp.run(args, **kwargs)


def safe_popen_wait(proc, timeout=None):
    """在冻结环境中安全地等待子进程结束，避免 Popen.wait() 的 GIL 崩溃。
    使用轮询方式检查进程状态。"""
    import time
    import subprocess as sp
    frozen = bool(getattr(__import__('sys'), 'frozen', False))
    if frozen and not IS_WINDOWS:
        deadline = time.time() + timeout if timeout else None
        while proc.poll() is None:
            if deadline and time.time() >= deadline:
                raise sp.TimeoutExpired(proc.args, timeout)
            time.sleep(0.02)
        return proc.returncode
    else:
        return proc.wait(timeout=timeout)
