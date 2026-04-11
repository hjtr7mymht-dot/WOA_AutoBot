import sys
import os
import threading
import queue
import json
import datetime
import collections
import traceback
import importlib.util
import tkinter as tk
import ctypes
import subprocess
import msvcrt
import time
import webbrowser
import urllib.error
import urllib.request
import adb_controller as adb_mod
from tkinter import filedialog, messagebox
from tkinter.scrolledtext import ScrolledText
from tkinter.constants import BOTH, END, LEFT, RIGHT, TOP, X, Y

# === 引入现代 UI 库 ===
import ttkbootstrap as ttkb  # type: ignore[import-untyped]
from ttkbootstrap.constants import *  # type: ignore[import-untyped]  # noqa: F401, F403
from ttkbootstrap.widgets import ToolTip  # type: ignore[import-untyped]

# === 引入 PIL 以修复图标显示 ===
from PIL import Image, ImageTk

# 引入后端逻辑
from adb_controller import set_custom_adb_path, AdbController, CURRENT_ADB_PATH, close_all_and_kill_server, get_woa_debug_dir, ensure_local_platform_tools
try:
    from emulator_discovery import get_mumu_install_from_registry, get_mumu_adb_paths
except ImportError:
    get_mumu_install_from_registry = None
    get_mumu_adb_paths = None

# MuMu 常用 ADB 端口（部分机型如 MuMu12+Vulkan 需用 MuMu 自带 adb 才能正常点击）
_MUMU_PORTS = {16384, 16385, 16416, 16448, 7555, 5555}


# 资源路径获取（兼容 PyInstaller 与 Nuitka）
def get_resource_path(relative_path):
    if getattr(sys, 'frozen', False):
        if hasattr(sys, '_MEIPASS'):
            base = sys._MEIPASS
        else:
            base = os.path.dirname(sys.executable)
        return os.path.join(base, relative_path)
    base_path = os.path.dirname(os.path.abspath(__file__))
    p1 = os.path.join(base_path, relative_path)
    if os.path.exists(p1):
        return p1
    if hasattr(sys, 'executable'):
        exe_path = os.path.dirname(sys.executable)
        p2 = os.path.join(exe_path, relative_path)
        if os.path.exists(p2):
            return p2
    p3 = os.path.join(os.getcwd(), relative_path)
    if os.path.exists(p3):
        return p3
    return p1



_ICON_DIR = "icon"

MAX_INSTANCES = 3

# === 多实例支持 ===
def _acquire_instance():
    """自动获取可用的实例槽位 (1~MAX_INSTANCES)，通过文件锁防止冲突。"""
    for i in range(1, MAX_INSTANCES + 1):
        lock_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"instance_{i}.lock")
        try:
            fh = open(lock_path, "w")
            fh.write(str(i))
            fh.flush()
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            return i, fh
        except (OSError, IOError):
            try:
                fh.close()
            except Exception:
                pass
    return None, None


INSTANCE_ID, _INSTANCE_LOCK_FH = _acquire_instance()
if INSTANCE_ID is None:
    ctypes.windll.user32.MessageBoxW(0, f"已达到最大实例数 ({MAX_INSTANCES})，无法再开启新窗口。", "WOA AutoBot", 0x30)
    sys.exit(1)

# 按实例隔离配置和统计文件
CONFIG_FILE = "config.json" if INSTANCE_ID == 1 else f"config_{INSTANCE_ID}.json"
STATS_FILE = "woa_stats.csv"

LOCAL_VERSION = "1.1.2"
OFFICIAL_REPO_URL = "https://github.com/hjtr7mymht-dot/WOA_AutoBot"
OFFICIAL_REPO_NAME = "hjtr7mymht-dot/WOA_AutoBot"
ONLINE_VERSION_PATH = "version.json"
ONLINE_GUARD_RECHECK_SEC = 90
REQUIRED_GUARD_MODULES = (
    "adb_controller",
    "main_adb",
    "simple_ocr",
    "emulator_discovery",
)
FEATURE_GUARD_TOKEN = "WOA_DONATE_GUARD_V1"
OFFICIAL_REPO_URL_EXPECTED = "https://github.com/hjtr7mymht-dot/WOA_AutoBot"
OFFICIAL_REPO_NAME_EXPECTED = "hjtr7mymht-dot/WOA_AutoBot"
ONLINE_VERSION_PATH_EXPECTED = "version.json"

DONATE_IMAGE_CANDIDATES = {
    "微信支付": (
        os.path.join("assets", "donate", "wechat_pay.png"),
        os.path.join("assets", "donate", "wechat_pay.jpg"),
        os.path.join("assets", "donate", "wechat_pay.jpeg"),
        os.path.join("assets", "donate", "wechat_pay.webp"),
        os.path.join("assets", "donate", "wechat.png"),
    ),
    "支付宝": (
        os.path.join("assets", "donate", "alipay_pay.png"),
        os.path.join("assets", "donate", "alipay_pay.jpg"),
        os.path.join("assets", "donate", "alipay_pay.jpeg"),
        os.path.join("assets", "donate", "alipay_pay.webp"),
        os.path.join("assets", "donate", "alipay.png"),
    ),
}


def _version_tuple(version):
    parts = []
    for part in str(version or "").strip().lstrip("vV").split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        parts.append(int(digits or 0))
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts[:4])


def _compare_version(left, right):
    lt = _version_tuple(left)
    rt = _version_tuple(right)
    if lt > rt:
        return 1
    if lt < rt:
        return -1
    return 0

def _write_crash_report(exc_type, exc_value, exc_traceback):
    """写入崩溃报告文件，返回文件路径。任何阶段出错都不抛异常。"""
    crash_log_path = None
    try:
        from adb_controller import get_woa_debug_dir
        debug_dir = get_woa_debug_dir()
        os.makedirs(debug_dir, exist_ok=True)
        crash_log_path = os.path.join(debug_dir, f"crash_report_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
    except Exception:
        try:
            crash_log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"crash_report_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
        except Exception:
            crash_log_path = f"crash_report_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

    last_logs = ""
    try:
        if hasattr(sys.stdout, "log_buffer"):
            last_logs = "\n".join(list(sys.stdout.log_buffer))
        elif hasattr(sys.stdout, "stream") and hasattr(sys.stdout.stream, "log_buffer"):
            last_logs = "\n".join(list(sys.stdout.stream.log_buffer))
    except Exception:
        pass

    try:
        with open(crash_log_path, "w", encoding="utf-8") as f:
            f.write("=== WOA AutoBot CRASH REPORT ===\n")
            f.write(f"Time: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Thread: {threading.current_thread().name}\n\n")
            f.write("--- EXCEPTION STACK TRACE ---\n")
            traceback.print_exception(exc_type, exc_value, exc_traceback, file=f)
            f.write("\n--- LAST PRESERVED LOGS ---\n")
            f.write(last_logs if last_logs else "(No logs preserved in buffer)")
            f.write("\n\n=== END REPORT ===\n")
    except Exception:
        crash_log_path = None
    return crash_log_path


def handle_exception(exc_type, exc_value, exc_traceback):
    """全局未捕获异常处理，生成崩溃日志"""
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    crash_log_path = _write_crash_report(exc_type, exc_value, exc_traceback)

    try:
        if crash_log_path:
            print(f"\n🛑 [严重错误] 脚本发生异常退出，详细日志已保存至: {crash_log_path}")
        traceback.print_exception(exc_type, exc_value, exc_traceback)
    except Exception:
        pass

    is_main = (threading.current_thread() is threading.main_thread())
    if is_main:
        try:
            messagebox.showerror("程序崩溃", f"脚本发生严重错误，已保存详细日志到: {crash_log_path}")
        except Exception:
            pass


def _thread_excepthook(args):
    """Python 3.8+ 子线程未捕获异常兜底"""
    if args.exc_type is SystemExit:
        return
    handle_exception(args.exc_type, args.exc_value, args.exc_traceback)


sys.excepthook = handle_exception
threading.excepthook = _thread_excepthook

try:
    import faulthandler as _fh
    _crash_fd = None
    try:
        from adb_controller import get_woa_debug_dir as _get_dbg
        _dbg_dir = _get_dbg()
        os.makedirs(_dbg_dir, exist_ok=True)
        _crash_fd = open(os.path.join(_dbg_dir, "crash_segfault.log"), "a", encoding="utf-8")
    except Exception:
        pass
    _fh.enable(file=_crash_fd if _crash_fd else sys.stderr, all_threads=True)
except Exception:
    pass


# === 增强型日志重定向器 ===
class MultiTextRedirector(object):
    def __init__(self, widgets=None, tag="stdout"):
        if widgets is None:
            widgets = []
        self.widgets = widgets
        self.tag = tag
        self.log_buffer = collections.deque(maxlen=200)
        self.closing = False
        self._queue = queue.Queue()

    def add_widget(self, widget):
        if widget not in self.widgets:
            self.widgets.append(widget)
            self._setup_tags(widget)

    def _setup_tags(self, widget):
        widget.tag_config("time", foreground="#999999", font=("Consolas", 8))
        widget.tag_config("normal", foreground="#333333")
        widget.tag_config("success", foreground="#75b798")
        widget.tag_config("error", foreground="#ea868f")
        widget.tag_config("highlight", foreground="#fd7e14")
        widget.tag_config("method", foreground="#c9a227")
        widget.tag_config("update", foreground="#e63946", font=("Microsoft YaHei UI", 10, "bold"))
        widget.tag_config("stats", foreground="#2196F3", font=("Microsoft YaHei UI", 9, "bold"))

    def write(self, str_val):
        if self.closing:
            return
        if "-> 执行动作:" in str_val: return
        if str_val == "\n":
            self._insert_to_all("\n", "normal")
            return

        now_str = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-4]
        time_prefix = f"[{now_str}] "

        tag = "normal"
        if "[统计]" in str_val:
            tag = "stats"
        elif "[版本更新]" in str_val:
            tag = "update"
        elif any(x in str_val for x in ["⚠️", "警告", "注意", "跳过", "超时"]):
            tag = "highlight"
        elif any(x in str_val for x in ["✅", "成功", "恢复", "通过"]):
            tag = "success"
        elif any(x in str_val for x in ["🛑", "❌", "错误", "失败", "严重", "卡死"]):
            tag = "highlight"
        elif any(x in str_val for x in ["[模式]", "触控方案", "截图方案", "触控:", "截图:"]):
            tag = "method"

        self.log_buffer.append(f"{time_prefix}{str_val}")
        self._insert_to_all(time_prefix, "time", str_val, tag)

    def _insert_to_all(self, txt1, tag1, txt2=None, tag2=None):
        if self.closing:
            return
        self._queue.put((txt1, tag1, txt2, tag2))

    def _flush_queue(self):
        """在主线程中调用，将队列中的日志写入 tkinter 控件"""
        count = 0
        batch = []
        while not self._queue.empty() and count < 50:
            try:
                batch.append(self._queue.get_nowait())
            except queue.Empty:
                break
            count += 1
        if not batch:
            return
        for w in self.widgets:
            try:
                if not w.winfo_exists():
                    continue
                w.configure(state="normal")
                for txt1, tag1, txt2, tag2 in batch:
                    w.insert("end", txt1, (tag1,))
                    if txt2:
                        w.insert("end", txt2, (tag2,))
                    try:
                        if int(w.index('end-1c').split('.')[0]) > 1000:
                            w.delete("1.0", "2.0")
                    except Exception:
                        pass
                w.see("end")
                w.configure(state="disabled")
            except (tk.TclError, RuntimeError):
                pass
            except Exception:
                pass

    def flush(self):
        pass


class TeeToFile:
    """调试模式下将日志同时输出到控件和文件"""
    def __init__(self, stream, filepath):
        self.stream = stream
        self.filepath = filepath
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        self._file = open(filepath, "w", encoding="utf-8")
        self._file.write(f"=== WOA AutoBot 调试日志 {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n\n")

    def write(self, s):
        self.stream.write(s)
        try:
            ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-4]
            self._file.write(f"[{ts}] {s}")
            self._file.flush()
        except Exception:
            pass

    def flush(self):
        self.stream.flush()
        try:
            self._file.flush()
        except Exception:
            pass

    def close(self):
        try:
            self._file.close()
        except Exception:
            pass


class Application(ttkb.Window):
    def __init__(self):
        try:
            myappid = 'woabot.launcher.v1.1.0'
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except:
            pass

        super().__init__(themename="sandstone")

        self.style.colors.success = "#4f6f52"
        self.style.colors.danger = "#b85c38"
        self.style.colors.primary = "#355c7d"
        self.style.colors.info = "#6c8ead"

        self.title(f"WOA AutoBot {LOCAL_VERSION}" + (f" [实例 {INSTANCE_ID}]" if INSTANCE_ID > 1 else ""))
        self.geometry("1080x1200")
        self.minsize(120, 120)
        self.last_geometry = "1080x1200"
        self.is_mini_mode = False
        self._strict_online_guard = bool(getattr(sys, 'frozen', False))

        self._config_file_exists = os.path.exists(CONFIG_FILE)
        self.config = self.load_config()
        self.var_bonus_staff = tk.BooleanVar(value=self.config.get("bonus_staff", False))
        self.var_vehicle_buy = tk.BooleanVar(value=self.config.get("vehicle_buy", False))
        self.var_speed_mode = tk.BooleanVar(value=self.config.get("speed_mode", False))
        self.var_skip_staff = tk.BooleanVar(value=self.config.get("skip_staff", False))
        self.var_delay_bribe = tk.BooleanVar(value=self.config.get("delay_bribe", False))
        self.var_delay_count = tk.StringVar(value=str(self.config.get("auto_delay_count", 0)))
        self.var_random_task = tk.BooleanVar(value=self.config.get("random_task_order", True))
        self.var_no_takeoff_mode = tk.BooleanVar(value=self.config.get("no_takeoff_mode", False))
        legacy_logout_interval = self.config.get("standalone_logout_interval")
        if legacy_logout_interval is None:
            legacy_logout_interval = self.config.get("no_takeoff_logout_min", self.config.get("no_takeoff_logout_max", 30))
        self.var_no_takeoff_logout_enabled = tk.BooleanVar(
            value=self.config.get("no_takeoff_logout_enabled", False))
        self.var_no_takeoff_switch_interval = tk.StringVar(value=str(self.config.get("no_takeoff_switch_interval", 15)))
        self.var_no_takeoff_auto_logout_interval = tk.StringVar(value=str(self.config.get("no_takeoff_auto_logout_interval", 30)))
        self.var_standalone_logout_interval = tk.StringVar(value=str(legacy_logout_interval or 30))
        self.var_cancel_stand_filter = tk.BooleanVar(value=self.config.get("cancel_stand_filter", True))
        self.var_tower_open_stand_only = tk.BooleanVar(value=self.config.get("tower_open_stand_only", False))
        self.var_anti_stuck_enabled = tk.BooleanVar(value=self.config.get("anti_stuck_enabled", True))
        self.var_anti_stuck_threshold = tk.StringVar(value=str(self.config.get("anti_stuck_threshold", 6)))
        self.var_notify_enabled = tk.BooleanVar(value=bool(self.config.get("mobile_notify_enabled", False)))
        self.var_notify_provider = tk.StringVar(value=str(self.config.get("mobile_notify_provider", "wecom")))
        self.var_notify_webhook = tk.StringVar(value=str(self.config.get("mobile_notify_webhook", "")))
        self.var_notify_keyword = tk.StringVar(value=str(self.config.get("mobile_notify_keyword", "")))
        self.var_stats_report_enabled = tk.BooleanVar(value=bool(self.config.get("mobile_stats_report_enabled", False)))
        self.var_stats_report_hours = tk.StringVar(value=str(self.config.get("mobile_stats_report_hours", 6)))
        self.var_public_adb_targets = tk.StringVar(value=str(self.config.get("public_adb_targets", "")))
        for legacy_key in (
            "auto_exit_time", "auto_exit_enabled", "auto_exit_rest_time", "auto_exit_rest_enabled",
            "auto_exit_loop_count", "auto_exit_loop_infinite", "restart_game_icon_file",
            "filter_switch_min", "filter_switch_max",
        ):
            self.config.pop(legacy_key, None)
        self.var_mini_top = tk.BooleanVar(value=False)
        self.var_runtime_status = tk.StringVar(value="待命")
        self.var_device_status = tk.StringVar(value="等待扫描设备")
        self.var_system_status = tk.StringVar(value="环境检查中")
        self.var_online_status = tk.StringVar(value="未验证")
        self.var_online_detail = tk.StringVar(value="官方仓库校验未执行")
        self._online_validation_running = False
        self._online_validation_ok = False
        self._online_validation_last_ok_ts = 0.0
        self._online_last_error = "尚未执行在线验证"
        self._online_guard_lockdown = False
        self._online_verified_once = bool(self.config.get("online_verified_once", False))
        self._missing_guard_modules = []
        self._guard_integrity_ok = True
        self._startup_update_checked = False
        self._startup_update_popup_shown = False

        if self.config.get("adb_path"):
            set_custom_adb_path(self.config["adb_path"])

        self.bot = None
        self.log_queue = queue.Queue()
        self.queue_check_interval = 100
        self._notify_lock = threading.Lock()
        self._notify_last_ts = 0.0
        self._notify_last_signature = ""
        self._stats_report_anchor_ts = 0.0

        self.redirector = MultiTextRedirector()
        self._log_tee = None
        if os.environ.get("WOA_DEBUG", "").strip().lower() in ("1", "true", "yes"):
            try:
                debug_dir = get_woa_debug_dir()
                log_path = os.path.join(debug_dir, f"log_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
                self._log_tee = TeeToFile(self.redirector, log_path)
                sys.stdout = self._log_tee
            except Exception:
                sys.stdout = self.redirector
        else:
            sys.stdout = self.redirector

        self._prepare_first_run_environment(
            force=(not self._config_file_exists) or (not self.config.get("initial_device_paths_detected", False)),
            reason="首次启动",
        )

        self.container_main = ttkb.Frame(self)
        self.container_mini = ttkb.Frame(self)

        self.setup_main_ui()
        self.setup_mini_ui()

        self.container_main.pack(fill=BOTH, expand=True)
        self.after(self.queue_check_interval, self.process_log_queue)
        self.after(60000, self._periodic_stats_report_tick)

        def _emit_notice():
            m1 = "此脚本为开源免费项目，如您是从任何渠道，例如淘宝、闲鱼、拼多多购买的，请立即退款并举报！"
            m2 = "获取更新和反馈问题请加入QQ群1067076460。"
            print(m1)
            print(m2)
            orig = getattr(sys, "__stdout__", None)
            if orig and getattr(sys, "stdout", None) is not orig:
                try:
                    orig.write(m1 + "\n")
                    orig.write(m2 + "\n")
                    orig.flush()
                except Exception:
                    pass
        self.after(100, _emit_notice)

        self.after(500, self.setup_window_icon)
        self.after(1200, self._bootstrap_online_guard)
        self.after(2200, self._startup_online_update_check)
        self.after(4500, self._online_guard_tick)
        self.bind("<Map>", self._on_window_map)
        self._icon_loaded = False

        self.protocol("WM_DELETE_WINDOW", self._on_closing)

    def _on_closing(self):
        """关闭窗口时停止脚本并清理资源，避免进程残留"""
        if getattr(self, "_is_closing", False):
            return
        self._is_closing = True

        self.redirector.closing = True

        bot = self.bot
        if bot:
            bot.running = False
            worker = getattr(bot, '_worker_thread', None)
            if worker and worker.is_alive():
                worker.join(timeout=2.0)
            try:
                adb_ref = getattr(bot, 'adb', None)
                if adb_ref:
                    adb_ref.close()
            except Exception:
                pass
        self.bot = None

        # 检查是否还有其他实例在运行
        other_alive = False
        for i in range(1, MAX_INSTANCES + 1):
            if i == INSTANCE_ID:
                continue
            lock_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"instance_{i}.lock")
            try:
                fh = open(lock_path, "w")
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                fh.close()
            except (OSError, IOError):
                other_alive = True
                break
            except Exception:
                pass

        if not other_alive:
            try:
                close_all_and_kill_server()
            except Exception:
                pass
        # 释放实例锁文件
        try:
            if _INSTANCE_LOCK_FH:
                _INSTANCE_LOCK_FH.close()
                lock_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"instance_{INSTANCE_ID}.lock")
                if os.path.exists(lock_path):
                    os.remove(lock_path)
        except Exception:
            pass
        try:
            if getattr(self, "_log_tee", None):
                self._log_tee.close()
            sys.stdout = sys.__stdout__
        except Exception:
            pass
        try:
            self.destroy()
        except Exception:
            pass
        try:
            self.quit()
        except Exception:
            pass

    def _on_window_map(self, event):
        if not self._icon_loaded and event.widget == self:
            self.setup_window_icon()
            self._icon_loaded = True

    def setup_window_icon(self):
        try:
            icon_rel = os.path.join(_ICON_DIR, "app.ico")
            icon_path = get_resource_path(icon_rel)
            if not os.path.exists(icon_path): return
            try:
                self.iconbitmap(default=icon_path)
            except:
                pass
            try:
                with open(icon_path, "rb") as f:
                    img = Image.open(f)
                    img.load()
                if hasattr(Image, 'Resampling'):
                    resample = Image.Resampling.LANCZOS
                else:
                    resample = Image.LANCZOS
                img16 = ImageTk.PhotoImage(img.resize((16, 16), resample))
                img32 = ImageTk.PhotoImage(img.resize((32, 32), resample))
                img48 = ImageTk.PhotoImage(img.resize((48, 48), resample))
                img64 = ImageTk.PhotoImage(img.resize((64, 64), resample))
                self.wm_iconphoto(True, img64, img48, img32, img16)
                self._icon_refs = [img16, img32, img48, img64]
            except:
                pass
        except:
            pass

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except:
                return {}
        return {}

    def save_config(self):
        self.config["bonus_staff"] = self.var_bonus_staff.get()
        self.config["vehicle_buy"] = self.var_vehicle_buy.get()
        self.config["speed_mode"] = self.var_speed_mode.get()
        self.config["skip_staff"] = self.var_skip_staff.get()
        self.config["delay_bribe"] = self.var_delay_bribe.get()
        self.config["random_task_order"] = self.var_random_task.get()
        self.config["tower_open_stand_only"] = self.var_tower_open_stand_only.get()
        self.config["anti_stuck_enabled"] = self.var_anti_stuck_enabled.get()
        self.config["no_takeoff_logout_enabled"] = self.var_no_takeoff_logout_enabled.get()
        try:
            self.config["no_takeoff_switch_interval"] = max(3.0, min(300.0, float(self.var_no_takeoff_switch_interval.get())))
        except Exception:
            self.config["no_takeoff_switch_interval"] = 15.0
        try:
            self.config["no_takeoff_auto_logout_interval"] = max(1.0, min(120.0, float(self.var_no_takeoff_auto_logout_interval.get())))
        except Exception:
            self.config["no_takeoff_auto_logout_interval"] = 30.0
        try:
            self.config["standalone_logout_interval"] = max(1.0, min(120.0, float(self.var_standalone_logout_interval.get())))
        except Exception:
            self.config["standalone_logout_interval"] = 30.0
        self.config["online_verified_once"] = bool(getattr(self, "_online_verified_once", False))
        self.config["initial_device_paths_detected"] = bool(self.config.get("initial_device_paths_detected", False))
        try:
            self.config["auto_delay_count"] = int(self.var_delay_count.get())
        except:
            self.config["auto_delay_count"] = 0
        try:
            anti_stuck_threshold = int(self.var_anti_stuck_threshold.get())
            anti_stuck_threshold = max(3, min(20, anti_stuck_threshold))
        except Exception:
            anti_stuck_threshold = 6
        self.var_anti_stuck_threshold.set(str(anti_stuck_threshold))
        self.config["anti_stuck_threshold"] = anti_stuck_threshold
        self.config["mobile_notify_enabled"] = bool(self.var_notify_enabled.get())
        provider = str(self.var_notify_provider.get() or "wecom").strip().lower()
        if provider not in ("wecom", "dingtalk"):
            provider = "wecom"
        self.var_notify_provider.set(provider)
        self.config["mobile_notify_provider"] = provider
        self.config["mobile_notify_webhook"] = str(self.var_notify_webhook.get() or "").strip()
        self.config["mobile_notify_keyword"] = str(self.var_notify_keyword.get() or "").strip()
        self.config["mobile_stats_report_enabled"] = bool(self.var_stats_report_enabled.get())
        self.config["mobile_stats_report_hours"] = self._normalize_stats_report_hours(self.var_stats_report_hours.get())
        self.var_stats_report_hours.set(str(self.config["mobile_stats_report_hours"]))
        self.config["public_adb_targets"] = str(self.var_public_adb_targets.get() or "").strip()
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=4)
        except Exception as e:
            print(f"配置保存失败: {e}")

    def _parse_public_adb_targets(self, raw_text=None):
        raw = str(self.var_public_adb_targets.get() if raw_text is None else raw_text or "")
        items = []
        for line in raw.replace(";", "\n").replace("，", "\n").splitlines():
            target = line.strip()
            if not target:
                continue
            if target.lower().startswith("adb://"):
                target = target[6:]
            if ":" not in target:
                continue
            if target not in items:
                items.append(target)
        return items

    def _connect_public_adb_targets(self, targets=None, debug=False):
        targets = self._parse_public_adb_targets() if targets is None else list(targets)
        if not targets:
            return [], []

        adb_exe = adb_mod.CURRENT_ADB_PATH if adb_mod.CURRENT_ADB_PATH else "adb"
        if adb_exe != "adb" and not os.path.isfile(adb_exe):
            adb_exe = "adb"

        connected = []
        failed = []
        creation_flags = 0x08000000
        for target in targets:
            try:
                result = subprocess.run(
                    [adb_exe, "connect", target],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=10,
                    creationflags=creation_flags,
                )
                out = (result.stdout or b"").decode("utf-8", errors="ignore")
                err = (result.stderr or b"").decode("utf-8", errors="ignore")
                merged = f"{out}\n{err}".lower()
                if any(flag in merged for flag in ("connected to", "already connected to")):
                    connected.append(target)
                else:
                    failed.append((target, (out or err or "连接未成功").strip()))
                if debug:
                    print(f">>> [公网ADB] {target}: {(out or err).strip() or '无返回'}")
            except Exception as exc:
                failed.append((target, str(exc)))
                if debug:
                    print(f">>> [公网ADB] {target}: 连接异常 {exc}")
        return connected, failed

    def _scan_devices_with_public_targets(self, debug=False):
        public_targets = self._parse_public_adb_targets()
        if public_targets:
            connected, failed = self._connect_public_adb_targets(public_targets, debug=debug)
            if connected:
                print(f">>> [公网ADB] 已连接 {len(connected)} 台公网设备")
            for target, reason in failed[:5]:
                print(f">>> [公网ADB] 连接失败 {target}: {reason}")
        return AdbController.scan_devices(debug=debug)

    def _build_mobile_notify_payload(self, provider, content):
        # 企业微信与钉钉机器人都支持 text 消息，统一构造，减少小白配置复杂度。
        _ = provider
        return {
            "msgtype": "text",
            "text": {
                "content": content,
            },
        }

    def _send_mobile_notify(self, title, detail, force=False):
        enabled = bool(self.var_notify_enabled.get())
        if not enabled and not force:
            return

        provider = str(self.var_notify_provider.get() or "wecom").strip().lower()
        if provider not in ("wecom", "dingtalk"):
            provider = "wecom"
        webhook = str(self.var_notify_webhook.get() or "").strip()
        if not webhook:
            return

        now = time.time()
        signature = f"{title}|{str(detail)[:120]}"
        with self._notify_lock:
            if not force:
                # 25 秒内只推送一次，且 90 秒内同签名不重复推送，避免刷屏。
                if now - self._notify_last_ts < 25:
                    return
                if signature == self._notify_last_signature and now - self._notify_last_ts < 90:
                    return
            self._notify_last_ts = now
            self._notify_last_signature = signature

        keyword = str(self.var_notify_keyword.get() or "").strip()
        provider_name = "企业微信" if provider == "wecom" else "钉钉"
        device = ""
        try:
            device = (self.combo_devices.get() or "").strip()
        except Exception:
            device = ""
        if not device:
            device = "未选择"

        content = (
            f"[WOA AutoBot] {title}\n"
            f"时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"设备: {device}\n"
            f"详情: {detail}"
        )
        if keyword:
            content = f"{keyword}\n{content}"

        payload = self._build_mobile_notify_payload(provider, content)

        def _worker():
            try:
                data = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(
                    webhook,
                    data=data,
                    headers={"Content-Type": "application/json; charset=utf-8"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=6) as resp:
                    _ = resp.read()
                print(f">>> [手机提醒] 已发送到{provider_name}")
            except Exception as exc:
                print(f">>> [手机提醒] 发送失败: {exc}")

        threading.Thread(target=_worker, daemon=True).start()

    def _check_error_and_notify(self, msg):
        text = str(msg or "").strip()
        if not text:
            return
        if "🛑 [严重错误]" in text or "脚本异常退出" in text:
            self._send_mobile_notify("脚本严重错误", text, force=True)
            return
        if "❌ 运行出错:" in text:
            self._send_mobile_notify("脚本运行报错", text)
            return
        if "检测到持续报错" in text:
            self._send_mobile_notify("脚本已自动停止", text, force=True)
            return
        # 覆盖防卡死硬停、异常触发自动停机等停机路径。
        if "[防卡死]" in text and "脚本已停止" in text:
            self._send_mobile_notify("脚本已自动停止", text, force=True)
            return
        if "自动停止" in text and ("防卡死" in text or "报错" in text or "异常" in text):
            self._send_mobile_notify("脚本已自动停止", text, force=True)

    def _normalize_stats_report_hours(self, value):
        try:
            iv = int(str(value).strip())
        except Exception:
            iv = 6
        if iv not in (3, 6, 12, 24):
            iv = 6
        return iv

    def _get_runtime_stats_snapshot(self):
        bot = self.bot
        if bot and getattr(bot, "running", False):
            a = int(getattr(bot, "_stat_session_approach", getattr(bot, "_stat_approach", 0)) or 0)
            d = int(getattr(bot, "_stat_session_depart", getattr(bot, "_stat_depart", 0)) or 0)
            sc = int(getattr(bot, "_stat_session_stand_count", getattr(bot, "_stat_stand_count", 0)) or 0)
            ss = int(getattr(bot, "_stat_session_stand_staff", getattr(bot, "_stat_stand_staff", 0)) or 0)
            run_start = getattr(bot, "_run_start_time", None)
            dur_text = "未知"
            if run_start:
                dur_s = max(0, int(time.time() - float(run_start)))
                hh, rem = divmod(dur_s, 3600)
                mm, sec = divmod(rem, 60)
                dur_text = f"{hh}小时{mm}分{sec}秒" if hh > 0 else f"{mm}分{sec}秒"
            return {
                "runtime": dur_text,
                "approach": a,
                "depart": d,
                "stand_count": sc,
                "stand_staff": ss,
                "source": "session",
            }

        import csv
        _base = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
        csv_path = os.path.join(_base, STATS_FILE)
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        if os.path.isfile(csv_path):
            try:
                with open(csv_path, "r", encoding="utf-8-sig") as f:
                    reader = csv.reader(f)
                    for i, row in enumerate(reader):
                        if i == 0 and row and row[0].strip().lower() == "date":
                            continue
                        if len(row) >= 5 and row[0] == today:
                            return {
                                "runtime": "当前未运行",
                                "approach": int(row[1]),
                                "depart": int(row[2]),
                                "stand_count": int(row[3]),
                                "stand_staff": int(row[4]),
                                "source": "csv",
                            }
            except Exception:
                pass

        return {
            "runtime": "当前未运行",
            "approach": 0,
            "depart": 0,
            "stand_count": 0,
            "stand_staff": 0,
            "source": "empty",
        }

    def _send_stats_report(self, manual=False):
        hours = self._normalize_stats_report_hours(self.var_stats_report_hours.get())
        self.var_stats_report_hours.set(str(hours))
        snap = self._get_runtime_stats_snapshot()
        detail = (
            f"周期: 每 {hours} 小时\n"
            f"运行时长: {snap['runtime']}\n"
            f"进场飞机: {snap['approach']} 架次\n"
            f"离场飞机: {snap['depart']} 架次\n"
            f"分配地勤: {snap['stand_count']} 架次 / {snap['stand_staff']} 人次\n"
            f"数据来源: {'本次运行' if snap['source'] == 'session' else '当日CSV'}"
        )
        title = "统计汇报(手动)" if manual else f"{hours}小时统计汇报"
        self._send_mobile_notify(title, detail, force=True)

    def _periodic_stats_report_tick(self):
        try:
            if bool(self.var_notify_enabled.get()) and bool(self.var_stats_report_enabled.get()):
                bot = self.bot
                if bot and getattr(bot, "running", False):
                    now = time.time()
                    hours = self._normalize_stats_report_hours(self.var_stats_report_hours.get())
                    interval = float(hours) * 3600.0
                    if self._stats_report_anchor_ts <= 0:
                        self._stats_report_anchor_ts = now
                    elif now - self._stats_report_anchor_ts >= interval:
                        self._send_stats_report(manual=False)
                        self._stats_report_anchor_ts = now
                else:
                    self._stats_report_anchor_ts = 0.0
            else:
                self._stats_report_anchor_ts = 0.0
        except Exception as exc:
            print(f">>> [统计汇报] 定时任务异常: {exc}")
        finally:
            self.after(60000, self._periodic_stats_report_tick)

    def _set_system_status(self, message):
        text = (message or "环境待检查").strip()
        self.var_system_status.set(text)
        if self.var_device_status.get() in ("等待扫描设备", "环境检查中") or "已自动" in self.var_device_status.get() or "Platform Tools" in self.var_device_status.get():
            self.var_device_status.set(text)

    def _ensure_local_android_sdk(self):
        result = ensure_local_platform_tools()
        messages = []
        if result.get("copied"):
            copied = result["copied"]
            preview = ", ".join(copied[:3])
            suffix = "..." if len(copied) > 3 else ""
            messages.append(f"已自动安装 Platform Tools 缺失文件: {preview}{suffix}")
        elif result.get("ready"):
            messages.append("已检测到内置 Android SDK Platform Tools")
        else:
            messages.append("未检测到可用 Platform Tools")

        adb_path = result.get("adb_path", "")
        if adb_path:
            set_custom_adb_path(adb_path)
        return result, messages

    def _normalize_mumu_root(self, path):
        if not path:
            return ""
        norm = os.path.normpath(path)
        lowered = norm.lower()
        suffixes = [
            os.path.normpath("nx_main").lower(),
            os.path.normpath("MuMu").lower(),
            os.path.normpath(os.path.join("emulator", "nemu")).lower(),
        ]
        for suffix in suffixes:
            if lowered.endswith(suffix):
                return os.path.dirname(norm)
        return norm

    def _detect_preferred_mumu_path(self):
        candidates = []
        if get_mumu_install_from_registry:
            try:
                candidates.extend(get_mumu_install_from_registry())
            except Exception:
                pass
        for candidate in candidates:
            norm = self._normalize_mumu_root(candidate)
            if norm and os.path.isdir(norm):
                return norm
        adb_candidate = AdbController._find_mumu_adb()
        if adb_candidate and os.path.isfile(adb_candidate):
            return self._normalize_mumu_root(os.path.dirname(adb_candidate))
        return ""

    def _detect_preferred_adb_path(self, mumu_root=""):
        local_adb = adb_mod.get_bundled_resource_path(os.path.join("adb_tools", "adb.exe"))
        if os.path.isfile(local_adb):
            return local_adb
        if get_mumu_adb_paths:
            try:
                adb_candidates = get_mumu_adb_paths()
                if adb_candidates:
                    return adb_candidates[0]
            except Exception:
                pass
        adb_candidate = AdbController._find_mumu_adb()
        if adb_candidate and os.path.isfile(adb_candidate):
            return adb_candidate
        bundled = adb_mod.DEFAULT_ADB_PATH if hasattr(adb_mod, "DEFAULT_ADB_PATH") else CURRENT_ADB_PATH
        if bundled and bundled != "adb" and os.path.isfile(bundled):
            return bundled
        if mumu_root:
            for sub in ("nx_main", "MuMu", os.path.join("emulator", "nemu")):
                candidate = os.path.join(mumu_root, sub, "adb.exe")
                if os.path.isfile(candidate):
                    return candidate
        return ""

    def _prepare_first_run_environment(self, force=False, reason="启动"):
        sdk_result, messages = self._ensure_local_android_sdk()
        changed = self._maybe_detect_initial_emulator_paths(force=force, reason=reason)

        detected_mumu = self.config.get("mumu_path", "")
        detected_adb = self.config.get("adb_path", "") or sdk_result.get("adb_path", "")
        if detected_mumu:
            messages.append("已自动识别 MuMu 路径")
        if detected_adb:
            messages.append("已切换 MuMu ADB" if "MuMu" in detected_adb or "Netease" in detected_adb else "已切换内置 ADB")

        final_message = " / ".join(dict.fromkeys([m for m in messages if m])) or "环境初始化完成"
        self._set_system_status(final_message)
        if changed:
            self.var_runtime_status.set("环境已就绪")
        return changed

    def _maybe_detect_initial_emulator_paths(self, force=False, reason="启动"):
        if not force and self.config.get("initial_device_paths_detected", False):
            return False

        detected_mumu = self._detect_preferred_mumu_path()
        detected_adb = self._detect_preferred_adb_path(detected_mumu)

        changed = False
        if force or detected_mumu:
            normalized_mumu = self._normalize_mumu_root(detected_mumu) if detected_mumu else ""
            if normalized_mumu:
                if self.config.get("mumu_path") != normalized_mumu:
                    self.config["mumu_path"] = normalized_mumu
                    changed = True
            else:
                if "mumu_path" in self.config:
                    self.config.pop("mumu_path", None)
                    changed = True

        if force or detected_adb:
            if detected_adb:
                detected_adb = os.path.normpath(detected_adb)
                if self.config.get("adb_path") != detected_adb:
                    self.config["adb_path"] = detected_adb
                    changed = True
                set_custom_adb_path(detected_adb)
            else:
                if "adb_path" in self.config:
                    self.config.pop("adb_path", None)
                    changed = True
                set_custom_adb_path(None)

        self.config["initial_device_paths_detected"] = True
        if changed or force:
            self.save_config()
            print(
                f">>> [初始化] {reason}自动检测完成: MuMu={self.config.get('mumu_path', '未发现')} | ADB={self.config.get('adb_path', '默认')}"
            )
        return changed or force

    def create_info_icon(self, parent, text):
        lbl = ttkb.Label(parent, text="ⓘ", font=("Segoe UI Symbol", 10), bootstyle="secondary", cursor="hand2")
        ToolTip(lbl, text=text, bootstyle="secondary-inverse")
        return lbl

    def _build_two_columns(self, parent):
        body = ttkb.Frame(parent)
        body.pack(fill=BOTH, expand=True)
        body.grid_columnconfigure(0, weight=1, uniform="settings_cols")
        body.grid_columnconfigure(1, weight=1, uniform="settings_cols")

        left_col = ttkb.Frame(body, padding=(0, 0, 10, 0))
        right_col = ttkb.Frame(body, padding=(10, 0, 0, 0))
        left_col.grid(row=0, column=0, sticky="nsew")
        right_col.grid(row=0, column=1, sticky="nsew")
        return left_col, right_col

    def toggle_mode(self):
        if self.is_mini_mode:
            self.container_mini.pack_forget()
            self.geometry(self.last_geometry)
            self.attributes('-topmost', False)
            self.overrideredirect(False)
            self.container_main.pack(fill=BOTH, expand=True)
            self.is_mini_mode = False
        else:
            self.last_geometry = self.geometry()
            self.container_main.pack_forget()
            self.geometry("320x180")
            self.attributes('-topmost', self.var_mini_top.get())
            self.container_mini.pack(fill=BOTH, expand=True)
            self.is_mini_mode = True

    def toggle_mini_top_state(self):
        if self.is_mini_mode:
            self.attributes('-topmost', self.var_mini_top.get())

    def launch_new_instance(self):
        if self.bot and self.bot.running:
            messagebox.showwarning("多开模式", "建议先确认当前实例已稳定运行，再开启新实例。", parent=self)
        try:
            creation_flags = 0x08000000
            if getattr(sys, 'frozen', False):
                cmd = [sys.executable]
            else:
                cmd = [sys.executable, os.path.abspath(__file__)]
            subprocess.Popen(cmd, cwd=os.path.dirname(os.path.abspath(__file__)), creationflags=creation_flags)
            print(">>> [多开模式] 已请求启动新的实例窗口")
        except Exception as exc:
            messagebox.showerror("多开模式", f"启动新实例失败: {exc}", parent=self)

    def setup_mini_ui(self):
        pad = 5
        top_row = ttkb.Frame(self.container_mini)
        top_row.pack(fill=X, padx=pad, pady=(pad, 0))
        ttkb.Label(top_row, text=f"WOA Mini {LOCAL_VERSION}", font=("Microsoft YaHei UI", 9, "bold"), bootstyle="secondary").pack(side=LEFT)
        ttkb.Button(top_row, text="还原", bootstyle="outline-warning", command=self.toggle_mode, padding=(5, 0)).pack(
            side=RIGHT)
        cb_top = ttkb.Checkbutton(top_row, text="置顶", variable=self.var_mini_top, bootstyle="toolbutton-secondary",
                                  command=self.toggle_mini_top_state)
        cb_top.pack(side=RIGHT, padx=5)
        ctl_row = ttkb.Frame(self.container_mini)
        ctl_row.pack(fill=X, padx=pad, pady=2)
        self.btn_mini_start = ttkb.Button(ctl_row, text="▶", bootstyle="success", width=4, command=self.start_bot)
        self.btn_mini_start.pack(side=LEFT, padx=(0, 2), fill=X, expand=True)
        self.btn_mini_stop = ttkb.Button(ctl_row, text="■", bootstyle="danger", width=4, state="disabled",
                                         command=self.stop_bot)
        self.btn_mini_stop.pack(side=LEFT, padx=(2, 0), fill=X, expand=True)
        log_frame = ttkb.Frame(self.container_mini)
        log_frame.pack(fill=BOTH, expand=True, padx=pad, pady=pad)
        ttkb.Label(log_frame, textvariable=self.var_online_status, anchor="w", bootstyle="secondary").pack(fill=X, pady=(0, 4))
        self.txt_mini_log = tk.Text(log_frame, state="disabled", font=("Consolas", 8), bg="#f8f9fa", relief="flat",
                                    height=4)
        self.txt_mini_log.pack(fill=BOTH, expand=True)
        self.redirector.add_widget(self.txt_mini_log)

    def _toggle_functional_switch(self, t, v):
        self.sync_all_configs_to_bot()
        state = "开启" if v.get() else "关闭"
        print(f">>> [功能状态] {t}: 已{state}")

    def setup_main_ui(self):
        # 整体外层容器，增加 padding 留白更现代化
        outer = ttkb.Frame(self.container_main, padding=20)
        outer.pack(fill=BOTH, expand=True)

        # ================== 1. Header 区域 (Logo与标题 + 状态胶囊) ==================
        header_frame = ttkb.Frame(outer)
        header_frame.pack(fill=X, pady=(0, 20))
        
        # 左侧：应用标题与版本信息
        title_frame = ttkb.Frame(header_frame)
        title_frame.pack(side=LEFT, fill=Y)
        ttkb.Label(title_frame, text="WOA 控制面板", font=("Microsoft YaHei UI", 22, "bold"), bootstyle="primary").pack(anchor="w")
        ttkb.Label(
            title_frame,
            text=f"当前版本 v{LOCAL_VERSION} · 开源免费工具 · 官方源 {OFFICIAL_REPO_NAME}",
            font=("Microsoft YaHei UI", 10),
            bootstyle="secondary",
        ).pack(anchor="w", pady=(4, 0))

        # 右侧：现代化的状态指示胶囊
        status_frame = ttkb.Frame(header_frame)
        status_frame.pack(side=RIGHT, fill=Y, pady=5)
        
        def make_status_capsule(parent, label_text, var, color, margin=(5,0)):
            f = ttkb.Frame(parent)
            f.pack(side=LEFT, padx=margin)
            ttkb.Label(f, text=label_text, font=("Microsoft YaHei UI", 9, "bold"), bootstyle="secondary").pack(side=LEFT, padx=(0, 5))
            ttkb.Label(f, textvariable=var, padding=(10, 4), bootstyle=f"inverse-{color}").pack(side=LEFT)
            
        make_status_capsule(status_frame, "运行状态", self.var_runtime_status, "primary")
        make_status_capsule(status_frame, "设备状态", self.var_device_status, "info", margin=(15, 0))
        make_status_capsule(status_frame, "云端校验", self.var_online_status, "success", margin=(15, 0))

        # ================== 2. 内容区 (左右两栏分屏布局) ==================
        content_pane = ttkb.Frame(outer)
        content_pane.pack(fill=BOTH, expand=False)
        content_pane.columnconfigure(0, weight=4, uniform="modern_layout")  # 左侧占4份
        content_pane.columnconfigure(1, weight=5, uniform="modern_layout")  # 右侧占5份，空间更大
        content_pane.rowconfigure(0, weight=1)

        # ----------------- 左侧：核心控制 与 工具入口 -----------------
        left_col = ttkb.Frame(content_pane)
        left_col.grid(row=0, column=0, sticky="nsew", padx=(0, 15))

        # 【核心控制卡片】
        connect_card = ttkb.Labelframe(left_col, text=" 连接与控制中心 ", padding=15, bootstyle="info")
        connect_card.pack(fill=X, pady=(0, 15))
        
        ttkb.Label(connect_card, text="选择目标设备后启动自动化流程", font=("Microsoft YaHei UI", 9), bootstyle="secondary").pack(anchor="w", pady=(0, 10))
        
        device_row = ttkb.Frame(connect_card)
        device_row.pack(fill=X, pady=(0, 15))
        self.combo_devices = ttkb.Combobox(device_row, state="readonly")
        self.combo_devices.pack(side=LEFT, fill=X, expand=True, padx=(0, 10))
        self.btn_scan = ttkb.Button(device_row, text="刷新设备", bootstyle="outline-info", command=self.refresh_devices, width=10)
        self.btn_scan.pack(side=RIGHT)

        action_row = ttkb.Frame(connect_card)
        action_row.pack(fill=X)
        self.btn_main_start = ttkb.Button(action_row, text="▶ 启动脚本", bootstyle="success", command=self.start_bot)
        self.btn_main_start.pack(side=LEFT, fill=X, expand=True, padx=(0, 5))
        self.btn_main_stop = ttkb.Button(action_row, text="■ 停止", bootstyle="danger", state="disabled", command=self.stop_bot, width=8)
        self.btn_main_stop.pack(side=RIGHT, padx=(5, 0))

        # 【快捷工具组】
        tools_card = ttkb.Labelframe(left_col, text=" 高级与工具 ", padding=12, bootstyle="secondary")
        tools_card.pack(fill=BOTH, expand=True)
        
        def make_tool_btn(parent, text, style, cmd):
            btn = ttkb.Button(parent, text=text, bootstyle=style, command=cmd)
            btn.pack(fill=X, pady=4)
            return btn
            
        make_tool_btn(tools_card, "⚙️ 详细高级设置", "outline-secondary", self.open_settings_window)
        make_tool_btn(tools_card, "➕ 启动多开实例", "outline-primary", self.launch_new_instance)
        make_tool_btn(tools_card, "🪟 切换小窗模式", "outline-warning", self.toggle_mode)
        
        ttkb.Separator(tools_card, bootstyle="secondary").pack(fill=X, pady=8)
        
        # 两个并排的小按钮
        tool_row = ttkb.Frame(tools_card)
        tool_row.pack(fill=X)
        ttkb.Button(tool_row, text="在线验证", bootstyle="outline-success", command=self.run_online_validation).pack(side=LEFT, fill=X, expand=True, padx=(0,4))
        ttkb.Button(tool_row, text="国内网络方案", bootstyle="outline-info", command=self.show_cn_network_help).pack(side=RIGHT, fill=X, expand=True, padx=(4,0))
        
        make_tool_btn(tools_card, "📖 官方仓库与使用说明", "outline-dark", self.open_help_window).pack_configure(pady=(8,0))


        # ----------------- 右侧：策略配置 Notebook标签页 -----------------
        right_col = ttkb.Frame(content_pane)
        right_col.grid(row=0, column=1, sticky="nsew")
        
        notebook = ttkb.Notebook(right_col, bootstyle="primary")
        notebook.pack(fill=BOTH, expand=True)

        def add_toggle_row(parent, text, var, help_txt):
            row = ttkb.Frame(parent)
            row.pack(fill=X, pady=8)
            ttkb.Checkbutton(
                row, text=text, variable=var, bootstyle="success-round-toggle", command=lambda t=text, v=var: self._toggle_functional_switch(t, v)
            ).pack(side=LEFT)
            self.create_info_icon(row, help_txt).pack(side=LEFT, padx=10)

        # [Tab 1] 游戏内策略
        tab_game = ttkb.Frame(notebook, padding=15)
        notebook.add(tab_game, text=" 游戏内策略 ")
        
        add_toggle_row(tab_game, "✈️ 自动领取地勤人员", self.var_bonus_staff, "地勤不足时尝试领取免费地勤，重新开始脚本后冷却重新计时。")
        add_toggle_row(tab_game, "🚗 自动购买地勤车辆", self.var_vehicle_buy, "地勤车辆不足时自动购买（实验性功能）。")
        add_toggle_row(tab_game, "💰 延误飞机自动贿赂", self.var_delay_bribe, "处理延误飞机时自动贿赂代理，会消耗银色飞机道具。")
        add_toggle_row(tab_game, "🎲 任务处理顺序随机化", self.var_random_task, "随机打乱处理各项任务的顺序，降低行为固定化风险。")
        add_toggle_row(tab_game, "🔒 塔台全开仅停机位", self.var_tower_open_stand_only, "塔台四个控制器全部开启时，强制限制只处理停机位。")

        # [Tab 2] 挂机与防检测
        tab_rhythm = ttkb.Frame(notebook, padding=15)
        notebook.add(tab_rhythm, text=" 挂机与防检测 ")
        
        # 延时处理
        ttkb.Label(tab_rhythm, text="自动延时塔台配置", font=("Microsoft YaHei UI", 10, "bold"), bootstyle="primary").pack(anchor="w", pady=(0, 10))
        tower_row = ttkb.Frame(tab_rhythm)
        tower_row.pack(fill=X, pady=(0, 15))
        ttkb.Label(tower_row, text="延时控制器：").pack(side=LEFT)
        ttkb.Entry(tower_row, textvariable=self.var_delay_count, width=6).pack(side=LEFT, padx=5)
        ttkb.Label(tower_row, text="次").pack(side=LEFT)
        ttkb.Button(tower_row, text="应用", bootstyle="outline-primary", command=self.on_confirm_tower_delay, padding=(10,0)).pack(side=LEFT, padx=10)
        self.create_info_icon(tower_row, "填0关闭，最大144。仅延时手动开启的控制器，不会改变原塔台布局。").pack(side=LEFT)

        ttkb.Separator(tab_rhythm, bootstyle="secondary").pack(fill=X, pady=15)

        # 模式切换
        ttkb.Label(tab_rhythm, text="挂机模式快速切换", font=("Microsoft YaHei UI", 10, "bold"), bootstyle="primary").pack(anchor="w", pady=(0, 10))
        h_row = ttkb.Frame(tab_rhythm)
        h_row.pack(fill=X)
        col1 = ttkb.Frame(h_row)
        col1.pack(side=LEFT, fill=X, expand=True)
        col2 = ttkb.Frame(h_row)
        col2.pack(side=LEFT, fill=X, expand=True)

        add_toggle_row(col1, "不起飞模式", self.var_no_takeoff_mode, "停止发给离场跑道，只接机和派车。")
        add_toggle_row(col2, "独立小退控制", self.var_no_takeoff_logout_enabled, "挂机一定时间后自动小退释放内存。")

        # [Tab 3] 高级性能调优
        tab_advanced = ttkb.Frame(notebook, padding=15)
        notebook.add(tab_advanced, text=" 高级与性能 ")
        
        ttkb.Label(tab_advanced, text="识别策略级强化 (谨慎使用)", font=("Microsoft YaHei UI", 10, "bold"), bootstyle="danger").pack(anchor="w", pady=(0, 10))
        add_toggle_row(tab_advanced, "⚡ 跳过二次校验 (温和提速)", self.var_speed_mode, "略微跳过动画二次校验，适合环境较稳定时使用。")
        add_toggle_row(tab_advanced, "🔥 跳过地勤验证 (激进提速)", self.var_skip_staff, "速度大幅提升，但出现误判风险增加。")
        add_toggle_row(tab_advanced, "⚙️ 塔台关闭时处理所有飞机", self.var_cancel_stand_filter, "在塔台关闭时，取消停机位过滤。")
        
        ttkb.Separator(tab_advanced, bootstyle="secondary").pack(fill=X, pady=15)
        
        ttkb.Label(tab_advanced, text="自动化守护", font=("Microsoft YaHei UI", 10, "bold"), bootstyle="primary").pack(anchor="w", pady=(0, 10))
        add_toggle_row(tab_advanced, "🛡️ 启用防卡死自动恢复", self.var_anti_stuck_enabled, "自动侦测并尝试解除界面卡死，关闭则保留致命弹窗检测。")
        stuck_row = ttkb.Frame(tab_advanced)
        stuck_row.pack(fill=X, pady=(0, 5))
        ttkb.Label(stuck_row, text="卡死容忍阈值：").pack(side=LEFT)
        ttkb.Entry(stuck_row, textvariable=self.var_anti_stuck_threshold, width=6).pack(side=LEFT, padx=5)
        ttkb.Button(stuck_row, text="应用", bootstyle="outline-primary", command=self.on_confirm_anti_stuck, padding=(10,0)).pack(side=LEFT, padx=10)
        self.create_info_icon(stuck_row, "范围3-20。数值越小触发重置越频繁。").pack(side=LEFT)

        # [Tab 4] 通知与统计
        tab_notify = ttkb.Frame(notebook, padding=15)
        notebook.add(tab_notify, text=" 通知与统计 ")

        ttkb.Label(tab_notify, text="统计报告推送", font=("Microsoft YaHei UI", 10, "bold"), bootstyle="primary").pack(anchor="w", pady=(0, 10))
        add_toggle_row(tab_notify, "📊 定时统计汇报", self.var_stats_report_enabled, "按周期(可在高级设置中调整)向手机推送统计报表。")

        ttkb.Separator(tab_notify, bootstyle="secondary").pack(fill=X, pady=15)
        
        ttkb.Label(tab_notify, text="异常状态告警", font=("Microsoft YaHei UI", 10, "bold"), bootstyle="danger").pack(anchor="w", pady=(0, 10))
        add_toggle_row(tab_notify, "📱 手机报错提醒", self.var_notify_enabled, "发生严重错误、卡死或自动停机时推送警报，需先配置 Webhook。")

        # ================== 3. 底部终端日志区 ==================
        log_group = ttkb.Labelframe(outer, text=" 实时终端输出 ", padding=10, bootstyle="dark")
        log_group.pack(fill=BOTH, expand=True, pady=(20, 0))
        
        # 终端风格日志输出
        self.txt_main_log = ScrolledText(log_group, state="disabled", font=("Consolas", 10), bg="#1E1E1E", fg="#D4D4D4", relief="flat", insertbackground="white")
        self.txt_main_log.pack(fill=BOTH, expand=True)
        self.redirector.add_widget(self.txt_main_log)
        
        # 延迟执行首次扫描，避免启动卡顿
        self.after(100, self._do_initial_scan)

    def _do_initial_scan(self):
        """后台线程执行首次设备扫描，完成后更新 UI"""
        def _worker():
            try:
                devs = self._scan_devices_with_public_targets(debug=True)
            except Exception as e:
                print(f">>> [扫描异常] {e}")
                devs = []
            self.after(0, lambda: self._apply_scan_result(devs))

        self.var_device_status.set("扫描中")
        self.btn_scan.configure(text="扫描中...", state="disabled")
        for btn in [self.btn_main_start, self.btn_mini_start]:
            btn.configure(state="disabled")
        self.update_idletasks()
        t = threading.Thread(target=_worker)
        t.daemon = True
        t.start()

    def _apply_scan_result(self, devs):
        """在主线程更新扫描结果"""
        try:
            self.btn_scan.configure(text="智能扫描", state="normal")
            if not (getattr(self, 'bot', None) and self.bot.running):
                for btn in [self.btn_main_start, self.btn_mini_start]:
                    btn.configure(state="normal", text="▶ 启动脚本")
            self.combo_devices['values'] = devs
            if devs:
                self.combo_devices.current(0)
                self.var_device_status.set(f"已连接候选 {len(devs)} 台")
                print(f">>> 扫描完成: 发现 {len(devs)} 台设备")
            else:
                self.var_device_status.set("未发现设备")
                print(">>> 扫描完成: 未发现设备")
        except Exception:
            pass

    def _build_online_sources(self, relative_path):
        relative_path = relative_path.lstrip("/")
        raw_url = f"https://raw.githubusercontent.com/{OFFICIAL_REPO_NAME}/main/{relative_path}"
        jsdelivr_url = f"https://cdn.jsdelivr.net/gh/{OFFICIAL_REPO_NAME}@main/{relative_path}"
        ghproxy_url = f"https://ghproxy.cn/{raw_url}"
        return [
            ("GitHub Raw", raw_url),
            ("jsDelivr", jsdelivr_url),
            ("ghproxy", ghproxy_url),
        ]

    def _fetch_online_text(self, sources, timeout=6):
        headers = {
            "User-Agent": f"WOA-AutoBot/{LOCAL_VERSION}",
            "Accept": "application/json,text/plain,text/html;q=0.9,*/*;q=0.8",
        }
        errors = []
        for source_name, url in sources:
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    charset = resp.headers.get_content_charset() or "utf-8"
                    return resp.read().decode(charset, errors="replace"), source_name, url
            except Exception as exc:
                errors.append(f"{source_name}: {exc}")
        raise RuntimeError(" | ".join(errors) if errors else "未知网络错误")

    def _resolve_online_validation(self):
        manifest_sources = self._build_online_sources(ONLINE_VERSION_PATH)
        readme_sources = self._build_online_sources("README.md")
        repo_sources = [
            ("GitHub", OFFICIAL_REPO_URL),
            ("ghproxy", f"https://ghproxy.cn/{OFFICIAL_REPO_URL}"),
        ]

        manifest_error = None
        try:
            text, source_name, url = self._fetch_online_text(manifest_sources)
            manifest = json.loads(text)
            remote_version = str(manifest.get("version", "")).strip().lstrip("vV")
            if remote_version:
                version_cmp = _compare_version(remote_version, LOCAL_VERSION)
                if version_cmp <= 0:
                    return {
                        "status": "已通过",
                        "detail": f"官方源可达，当前已是最新版，来源 {source_name}",
                        "message": f"在线验证通过\n\n本地版本: {LOCAL_VERSION}\n线上版本: {remote_version}\n来源: {source_name}\n地址: {url}",
                        "remote_version": remote_version,
                    }
                return {
                    "status": "发现更新",
                    "detail": f"检测到线上版本 {remote_version}，来源 {source_name}",
                    "message": f"检测到新版本\n\n本地版本: {LOCAL_VERSION}\n线上版本: {remote_version}\n来源: {source_name}\n地址: {url}",
                    "remote_version": remote_version,
                }
        except Exception as exc:
            manifest_error = str(exc)

        try:
            _, source_name, url = self._fetch_online_text(readme_sources)
            return {
                "status": "已连接",
                "detail": f"官方仓库在线可达，当前未提供 version.json，来源 {source_name}",
                "message": f"官方仓库可访问\n\n本地版本: {LOCAL_VERSION}\n版本清单: 未提供\n已使用 {source_name} 回退验证\n地址: {url}",
            }
        except Exception:
            pass

        _, source_name, url = self._fetch_online_text(repo_sources, timeout=8)
        return {
            "status": "已连接",
            "detail": f"仓库主页可达，版本清单暂不可用，来源 {source_name}",
            "message": f"已连接官方仓库主页\n\n本地版本: {LOCAL_VERSION}\n版本清单: 不可用\n仓库地址: {url}\n版本清单错误: {manifest_error or '未返回'}",
        }

    def _set_online_validation_state(self, ok, detail=""):
        self._online_validation_ok = bool(ok)
        if ok:
            self._online_validation_last_ok_ts = time.time()
            self._online_last_error = ""
            self._online_guard_lockdown = False
            self._online_verified_once = True
            self.config["online_verified_once"] = True
            self.save_config()
        else:
            if detail:
                self._online_last_error = detail

    def _detect_missing_guard_modules(self):
        missing = []
        for mod_name in REQUIRED_GUARD_MODULES:
            try:
                spec = importlib.util.find_spec(mod_name)
                if spec is None:
                    missing.append(mod_name)
                    continue
                module_obj = sys.modules.get(mod_name)
                if module_obj is None:
                    module_obj = __import__(mod_name)
                token = str(getattr(module_obj, "WOA_FEATURE_GUARD_TOKEN", "")).strip()
                if token != FEATURE_GUARD_TOKEN:
                    missing.append(f"{mod_name}.guard")
            except Exception:
                missing.append(mod_name)

        # 打包后入口以 exe 形式存在，源码模式才检查当前 py 文件。
        if getattr(sys, "frozen", False):
            launcher_exists = os.path.exists(os.path.abspath(sys.executable))
        else:
            launcher_exists = os.path.exists(os.path.abspath(__file__))
        if not launcher_exists:
            missing.append("gui_launcher")

        # 关键功能守卫：资助入口和资源目录被删除/篡改时在严格模式触发阻断。
        donate_fn = getattr(self, "open_donate_window", None)
        if not callable(donate_fn):
            missing.append("donate.entry")
        if not isinstance(DONATE_IMAGE_CANDIDATES, dict) or not DONATE_IMAGE_CANDIDATES:
            missing.append("donate.candidates")
        donate_readme = get_resource_path(os.path.join("assets", "donate", "README.md"))
        if not os.path.isfile(donate_readme):
            missing.append("assets.donate")

        # 严格模式下校验关键更新源配置，防止被改为非官方源后继续分发。
        if str(OFFICIAL_REPO_URL).strip() != OFFICIAL_REPO_URL_EXPECTED:
            missing.append("official.repo_url")
        if str(OFFICIAL_REPO_NAME).strip() != OFFICIAL_REPO_NAME_EXPECTED:
            missing.append("official.repo_name")
        if str(ONLINE_VERSION_PATH).strip() != ONLINE_VERSION_PATH_EXPECTED:
            missing.append("online.version_path")
        # 兼容不同打包形态（源码/onefile/onedir）下 version.json 的落盘位置，避免误报缺失。
        version_candidates = []
        try:
            version_candidates.append(get_resource_path(ONLINE_VERSION_PATH_EXPECTED))
        except Exception:
            pass
        try:
            version_candidates.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), ONLINE_VERSION_PATH_EXPECTED))
        except Exception:
            pass
        try:
            version_candidates.append(os.path.join(os.path.dirname(os.path.abspath(sys.executable)), ONLINE_VERSION_PATH_EXPECTED))
        except Exception:
            pass
        try:
            version_candidates.append(os.path.join(os.getcwd(), ONLINE_VERSION_PATH_EXPECTED))
        except Exception:
            pass
        has_version_file = any(os.path.isfile(p) for p in set(version_candidates) if p)
        if not has_version_file:
            # 缺少本地版本清单不直接判定为篡改，交由在线验证链路继续判定可用性。
            print(">>> [在线校验] 未在本地找到 version.json，已跳过 online.version_file 本地校验，继续使用在线源校验")

        self._missing_guard_modules = sorted(set(missing))
        self._guard_integrity_ok = len(self._missing_guard_modules) == 0
        return self._guard_integrity_ok

    def _missing_modules_text(self):
        if not self._missing_guard_modules:
            return ""
        return ", ".join(self._missing_guard_modules)

    def _lockdown_runtime(self, reason):
        if self.bot:
            self.stop_bot()
        self._online_guard_lockdown = True
        self.var_runtime_status.set("在线校验阻断")
        self.var_online_status.set("阻断")
        self.var_online_detail.set(reason)
        for btn in [self.btn_main_start, self.btn_mini_start]:
            try:
                btn.configure(state="disabled", text="已阻断")
            except Exception:
                pass
        print(f">>> [在线验证阻断] {reason}")

    def _unlock_runtime_if_possible(self):
        if not self._online_guard_lockdown:
            return
        if not self._guard_integrity_ok:
            return
        self._online_guard_lockdown = False
        if not (getattr(self, 'bot', None) and self.bot.running):
            for btn in [self.btn_main_start, self.btn_mini_start]:
                try:
                    btn.configure(state="normal", text="▶ 启动脚本")
                except Exception:
                    pass

    def _bootstrap_online_guard(self):
        if not self._strict_online_guard:
            self.var_online_status.set("社区模式")
            self.var_online_detail.set("源码运行默认不做强制在线阻断，避免影响开源社区二创；可手动点击在线验证。")
            return
        guard_ok = self._detect_missing_guard_modules()
        if not guard_ok:
            missing = self._missing_modules_text()
            self._lockdown_runtime(f"检测到校验模块缺失: {missing}")
            self.run_online_validation(silent=True)
            return
        if not self._online_verified_once:
            self.run_online_validation(silent=True)
            return
        self.var_online_status.set("已授权")
        self.var_online_detail.set("首次在线验证已完成，当前无需重复验证")

    def _enforce_online_guard(self, scene, interactive=True):
        if not self._strict_online_guard:
            return True
        guard_ok = self._detect_missing_guard_modules()
        if not guard_ok:
            missing = self._missing_modules_text()
            self._lockdown_runtime(f"检测到校验模块缺失: {missing}")
            if not self._online_validation_running:
                self.run_online_validation(silent=True)
            if interactive:
                messagebox.showerror(
                    "校验模块缺失",
                    f"检测到关键校验模块缺失，已拒绝执行当前操作({scene})。\n\n缺失模块: {missing}",
                    parent=self,
                )
            return False

        if self._online_verified_once:
            self._unlock_runtime_if_possible()
            return True

        if self._online_validation_running:
            if interactive:
                messagebox.showwarning("在线验证中", "在线验证正在进行，请稍后再试。", parent=self)
            return False
        self.run_online_validation(silent=not interactive)
        if interactive:
            messagebox.showwarning(
                "在线验证未通过",
                f"当前操作({scene})需要完成首次在线验证。\n\n请等待验证完成后重试。",
                parent=self,
            )
        return False

    def _online_guard_tick(self):
        try:
            if not self._strict_online_guard:
                return
            if not self._detect_missing_guard_modules():
                missing = self._missing_modules_text()
                if self.bot and self.bot.running:
                    self._lockdown_runtime(f"运行期间发现校验模块缺失: {missing}")
                if not self._online_validation_running:
                    self.run_online_validation(silent=True)
        finally:
            if not getattr(self, "_is_closing", False):
                self.after(ONLINE_GUARD_RECHECK_SEC * 1000, self._online_guard_tick)

    def _startup_online_update_check(self):
        """仅在启动阶段执行一次联网版本检测，不执行自动下载更新。"""
        if self._startup_update_checked or getattr(self, "_is_closing", False):
            return
        if self._online_validation_running:
            self.after(1200, self._startup_online_update_check)
            return
        self._startup_update_checked = True
        self.run_online_validation(silent=True, show_update_popup=True)

    def run_online_validation(self, silent=False, show_update_popup=False):
        if self._online_validation_running:
            return
        self._online_validation_running = True
        self.var_online_status.set("校验中")
        self.var_online_detail.set("正在尝试 GitHub 与国内镜像节点...")

        def _worker():
            result = None
            error = None
            try:
                result = self._resolve_online_validation()
            except Exception as exc:
                error = str(exc)

            def _finish():
                self._online_validation_running = False
                if error:
                    self._set_online_validation_state(False, detail=error)
                    self.var_online_status.set("不可达")
                    self.var_online_detail.set("GitHub 直连和国内镜像均不可用")
                    if self.bot and self.bot.running:
                        self._lockdown_runtime("运行期间在线验证失败，已自动停止")
                    if not silent:
                        messagebox.showerror(
                            "在线验证失败",
                            "未能连接官方仓库。\n\n已尝试 GitHub Raw、jsDelivr 与 ghproxy。\n可在“国内网络方案”中查看建议。\n\n错误信息:\n" + error,
                            parent=self,
                        )
                    return

                self._set_online_validation_state(True)
                self.var_online_status.set(result["status"])
                self.var_online_detail.set(result["detail"])
                self._unlock_runtime_if_possible()
                print(f">>> [在线验证] {result['detail']}")
                if (
                    show_update_popup
                    and not self._startup_update_popup_shown
                    and result.get("status") == "发现更新"
                ):
                    self._startup_update_popup_shown = True
                    remote_v = str(result.get("remote_version") or "未知")
                    if messagebox.askyesno(
                        "发现新版本",
                        f"检测到新版本可用。\n\n当前版本: {LOCAL_VERSION}\n最新版本: {remote_v}\n\n是否立即打开官方仓库下载更新？",
                        parent=self,
                    ):
                        self.open_official_repo()
                if not silent:
                    messagebox.showinfo("在线验证", result["message"], parent=self)

            self.after(0, _finish)

        threading.Thread(target=_worker, daemon=True).start()

    def open_official_repo(self):
        webbrowser.open(OFFICIAL_REPO_URL)

    def show_cn_network_help(self):
        message = (
            "官方仓库: " + OFFICIAL_REPO_URL + "\n\n"
            "脚本在线验证会依次尝试以下来源:\n"
            "1. GitHub Raw\n"
            "2. jsDelivr 镜像\n"
            "3. ghproxy 代理\n\n"
            "如果你处于中国特殊网络环境，建议优先按以下顺序处理:\n"
            "1. 先点击“立即在线验证”，观察当前命中的来源。\n"
            "2. 若 GitHub Raw 失败，脚本会自动回退到 jsDelivr 或 ghproxy。\n"
            "3. 若三者都失败，请为系统配置代理或规则分流后再验证。\n"
            "4. 如需人工访问仓库，可先打开官方仓库按钮，必要时通过浏览器代理访问。"
        )
        messagebox.showinfo("国内网络方案", message, parent=self)

    def _resolve_donate_image(self, pay_type):
        candidates = DONATE_IMAGE_CANDIDATES.get(pay_type, ())
        fallback_rel = candidates[0] if candidates else ""
        for rel_path in candidates:
            abs_path = get_resource_path(rel_path)
            if os.path.isfile(abs_path):
                return abs_path, rel_path
        return "", fallback_rel

    def _load_donate_photo(self, image_path, max_width=330, max_height=520):
        with Image.open(image_path) as img:
            img.load()
            src_w, src_h = img.size
            if src_w <= 0 or src_h <= 0:
                raise ValueError("无效图片尺寸")
            scale = min(max_width / float(src_w), max_height / float(src_h), 1.0)
            new_w = max(1, int(src_w * scale))
            new_h = max(1, int(src_h * scale))
            if hasattr(Image, "Resampling"):
                resample = Image.Resampling.LANCZOS
            else:
                resample = Image.LANCZOS
            resized = img.resize((new_w, new_h), resample)
            return ImageTk.PhotoImage(resized)

    def open_donate_window(self):
        donate_win = getattr(self, "donate_win", None)
        if donate_win and donate_win.winfo_exists():
            donate_win.lift()
            donate_win.focus_force()
            return

        parent = self.settings_win if hasattr(self, "settings_win") and self.settings_win.winfo_exists() else self
        win = ttkb.Toplevel(self)
        self.donate_win = win
        win.title("自愿资助")
        win.geometry("860x760")
        win.minsize(760, 620)
        win.transient(parent)
        win.grab_set()

        outer = ttkb.Frame(win, padding=16)
        outer.pack(fill=BOTH, expand=True)
        ttkb.Label(outer, text="自愿资助作者买杯咖啡", font=("Microsoft YaHei UI", 16, "bold"), bootstyle="primary").pack(anchor="w")
        ttkb.Label(
            outer,
            text="完全自愿，无任何功能限制；感谢支持项目持续维护。",
            bootstyle="secondary",
        ).pack(anchor="w", pady=(4, 12))

        cards = ttkb.Frame(outer)
        cards.pack(fill=BOTH, expand=True)
        cards.grid_columnconfigure(0, weight=1, uniform="donate_cols")
        cards.grid_columnconfigure(1, weight=1, uniform="donate_cols")

        self._donate_image_refs = []
        for idx, pay_type in enumerate(("微信支付", "支付宝")):
            card = ttkb.Labelframe(cards, text=pay_type, padding=10, bootstyle="info")
            card.grid(row=0, column=idx, sticky="nsew", padx=(0, 8) if idx == 0 else (8, 0))

            abs_path, expected_rel = self._resolve_donate_image(pay_type)
            if abs_path:
                try:
                    photo = self._load_donate_photo(abs_path)
                    img_label = ttkb.Label(card, image=photo)
                    img_label.image = photo
                    img_label.pack(fill=BOTH, expand=True)
                    self._donate_image_refs.append(photo)
                    ttkb.Label(card, text=f"已加载: {os.path.basename(abs_path)}", bootstyle="secondary").pack(anchor="w", pady=(8, 0))
                except Exception as exc:
                    ttkb.Label(card, text=f"图片加载失败: {exc}", bootstyle="danger").pack(anchor="w", pady=(8, 0))
            else:
                ttkb.Label(
                    card,
                    text=(
                        "未找到收款码图片。\n"
                        f"请将图片放到: {expected_rel}"
                    ),
                    justify="left",
                    bootstyle="warning",
                ).pack(fill=BOTH, expand=True)

        ttkb.Label(
            outer,
            text="提示: 高级设置中点击“自愿资助”按钮时才会显示本窗口。",
            bootstyle="secondary",
        ).pack(anchor="w", pady=(12, 8))

        action_row = ttkb.Frame(outer)
        action_row.pack(fill=X)
        ttkb.Button(action_row, text="关闭", bootstyle="secondary-outline", command=win.destroy, width=10).pack(side=RIGHT)

        win.after(50, lambda: self._center_toplevel_on_parent(win))

    def _center_toplevel_on_parent(self, win):
        """将子窗口居中于主窗口"""
        self.update_idletasks()
        pw, ph = self.winfo_width(), self.winfo_height()
        px, py = self.winfo_rootx(), self.winfo_rooty()
        if pw < 100 or ph < 100:
            g = self.geometry()
            if "x" in g:
                parts = g.split("+")[0].split("x")
                if len(parts) == 2:
                    pw, ph = int(parts[0] or 680), int(parts[1] or 850)
        win.update_idletasks()
        w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        if w <= 1 or h <= 1:
            g = win.geometry()
            if "x" in g:
                parts = g.split("+")[0].split("x")
                if len(parts) == 2:
                    w, h = int(parts[0] or 400), int(parts[1] or 400)
        x = px + max(0, (pw - w) // 2)
        y = py + max(0, (ph - h) // 2)
        win.geometry(f"+{x}+{y}")

    _LOCAL_HELP_CONTENT = """
· 下载失败，您看到的使用说明是离线版本！
· 如您的网络没有问题，请确认脚本的获取来源是否正常！

【声明】
- 此脚本为开源免费项目，如您是从任何渠道，例如淘宝、闲鱼、拼多多购买的，请立即退款并举报！
- 获取更新和反馈问题请加入QQ群1067076460。
- 官方仓库地址：https://github.com/hjtr7mymht-dot/WOA_AutoBot
- 如遇任何问题或bug，请在QQ群内或github上进行反馈。
- 脚本尚不稳定，如果造成账号内游戏币损失，本人概不负责！使用辅助工具有风险，请自行评估，如造成账号封禁，与作者无关！

【环境配置】
1. 仅支持在Windows系统上使用的安卓模拟器，本脚本专为MuMu模拟器优化，强烈推荐使用MuMu模拟器，建议使用横屏分辨率，脚本会自动适配。
2. Mumu模拟器默认地址为127.0.0.1:16384（其他模拟器或多开，请到模拟器设置内查看），并且自备加速器，保证网络通畅。
3. 请优先连接127.0.0.1:16384，127.0.0.1:16416之类的端口，尽量不要连接127.0.0.1:5555，emulator-5554之类的端口。
4. 使用MuMu模拟器时，请在设备设置中关闭“网络桥接模式”，关闭“后台挂机时保活运行”选项。
5. - 如模拟器连接遇到问题，请首先尝试手动指定ADB路径。
    - 如nemu_ipc方案无法启用，请首先尝试手动指定MuMu安装路径（指定到例如D:\\Program Files\\MuMuPlayer即可，不要指定到MuMuPlayer\\nx_main文件夹）。
   - 如遇到未知问题，请尝试切换模拟器渲染模式为DirectX。

【使用须知】
1. 游戏语言：必须设置为[简体中文]。
2. 请勿与脚本同时操作！手动操作前请先停止运行。
3. 脚本使用双击空白处的方式关闭窗口，默认是窗口右上角附近的位置，如您发现脚本会误触飞机，请调整挂机视角，或将视角拉到最近并置于在空白处。
4. 机位分配只会点第一个，如果不希望C型机停DEF的机位等情况，需要手动筛选机位停机类型，并且与时刻表功能不兼容，请把时刻表重置。

【功能说明】
1. 推荐使用nemu_ipc + ADB 或 uiautomator2 + ADB 的方案。脚本运行速度主要取决于[截图方案]，运行速度如下：nemu_ipc > uiautomator2 >> droidcast_raw >= ADB。
2. 使用高速方案（如nemu_ipc或uiautomator2）时，由于速度很快，出错会增多，非常不建议关闭“跳过二次校验”和“跳过地勤分配验证”开关。 
3. 脚本运行时必须保持游戏右侧筛选选项中，仅筛选出带有黄色感叹号的待处理飞机。但您无需担心！脚本可以自动检测并调整筛选状态。
4. 使用“自动延时塔台”功能前，请保证您已开启塔台（且目前仅支持四个控制器全开），并设置好带有[延时]按钮的界面，脚本不会主动调整。

【在线验证与国内网络】
1. 脚本会优先通过 GitHub Raw 访问官方仓库，如果失败会自动回退到 jsDelivr 和 ghproxy。
2. 若在线验证失败，请打开主界面的“国内网络方案”查看回退说明，并在系统网络层配置代理或分流。
3. 当前官方仓库为 https://github.com/hjtr7mymht-dot/WOA_AutoBot。

【已知问题和缺陷】
1. 脚本本身支持多开，但测试并不充分，多开很可能存在未知问题。若脚本正在运行时，开启（或关闭）第二个脚本或类似软件（如ALAS），会导致脚本运行中断，请注意，尝试停止后再重新运行。
2. 脚本很有可能被杀毒软件误杀，如您遇到类似问题，请关闭杀毒软件。
3. 脚本处理[需要维护]的飞机时，暂无法应对绿币不足的情况，请您根据机队规模，预留充足的绿币。
4. 任何情况下脚本目前都没有滑动右侧任务列表的能力。
5. 地勤不足时，脚本只会在可用地勤数量发生变化时尝试恢复分配，暂无法根据不同机型的需求智能分配。
6. 脚本无法设置起降飞机的比例，如您需要处理的飞机很多，请配合塔台使用。
"""

    def _show_help_badge(self):
        if self._help_badge is not None:
            return
        parent = self.btn_help.master
        try:
            bg = ttkb.Style().lookup("TFrame", "background") or "#ffffff"
        except Exception:
            bg = "#ffffff"
        dot = tk.Canvas(parent, width=10, height=10, highlightthickness=0, bd=0, bg=bg)
        dot.create_oval(1, 1, 9, 9, fill="#e63946", outline="#e63946")
        dot.place(relx=1.0, rely=0.0, anchor="ne", x=-2, y=2)
        self._help_badge = dot

    def _hide_help_badge(self):
        if self._help_badge is not None:
            self._help_badge.destroy()
            self._help_badge = None

    def open_help_window(self):
        win = ttkb.Toplevel(self)
        win.title("使用说明")
        win.geometry("920x820")
        shell = ttkb.Frame(win, padding=16)
        shell.pack(fill=BOTH, expand=True)
        header = ttkb.Frame(shell, padding=(18, 16))
        header.pack(fill=X)
        ttkb.Label(header, text="使用说明与网络方案", font=("Microsoft YaHei UI", 16, "bold"), bootstyle="primary").pack(anchor="w")
        ttkb.Label(header, text=f"版本 {LOCAL_VERSION} · 官方源 {OFFICIAL_REPO_NAME}", bootstyle="secondary").pack(anchor="w", pady=(4, 0))
        container = ttkb.Labelframe(shell, text="离线帮助", padding=12, bootstyle="info")
        container.pack(fill=BOTH, expand=True, pady=(14, 0))
        text_area = tk.Text(container, font=("Microsoft YaHei UI", 10), wrap="word", bg="#fcfbf7", fg="#333333",
                            relief="flat")
        text_area.pack(side=LEFT, fill=BOTH, expand=True)
        scroll = ttkb.Scrollbar(container, command=text_area.yview)
        scroll.pack(side=RIGHT, fill=Y)
        text_area.config(yscrollcommand=scroll.set)
        text_area.insert("end", "正在加载...\n")
        text_area.configure(state="disabled")
        self._center_toplevel_on_parent(win)

        def _load():
            content = self._LOCAL_HELP_CONTENT
            def _fill():
                text_area.configure(state="normal")
                text_area.delete("1.0", "end")
                text_area.insert("end", content)
                text_area.configure(state="disabled")
                self._hide_help_badge()
            self.after(0, _fill)
        threading.Thread(target=_load, daemon=True).start()

    def _open_stats_chart(self):
        import csv
        from datetime import datetime, timedelta, date as date_type

        _base = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
        csv_path = os.path.join(_base, STATS_FILE)
        if not os.path.isfile(csv_path):
            messagebox.showinfo("统计图表", "暂无统计数据，请先运行脚本。", parent=self)
            return

        rows = []
        try:
            with open(csv_path, "r", encoding="utf-8-sig") as f:
                reader = csv.reader(f)
                for i, row in enumerate(reader):
                    if i == 0 and row and row[0].strip().lower() == "date":
                        continue
                    if len(row) >= 5:
                        rows.append(row)
        except Exception as e:
            messagebox.showerror("统计图表", f"读取 CSV 失败: {e}", parent=self)
            return
        if not rows:
            messagebox.showinfo("统计图表", "暂无统计数据。", parent=self)
            return

        cutoff = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        data = []
        for row in rows:
            if row[0] >= cutoff:
                try:
                    data.append((row[0], int(row[1]), int(row[2]), int(row[3]), int(row[4])))
                except (ValueError, IndexError):
                    pass
        if not data:
            messagebox.showinfo("统计图表", "最近 30 天内暂无统计数据。", parent=self)
            return
        data.sort(key=lambda r: r[0])

        settings_win = getattr(self, "settings_win", None)
        if settings_win and settings_win.winfo_exists():
            settings_win.grab_release()

        win = ttkb.Toplevel(self)
        win.title("统计图表 (最近 30 天)")
        win.geometry("780x760")
        win.transient(self)

        def _on_chart_close():
            if settings_win and settings_win.winfo_exists():
                try:
                    settings_win.grab_set()
                except tk.TclError:
                    pass
            try:
                win.destroy()
            except Exception:
                pass

        win.protocol("WM_DELETE_WINDOW", _on_chart_close)

        data_dict = {r[0]: (r[1], r[2], r[3], r[4]) for r in data}

        today = date_type.today()
        cutoff_date = today - timedelta(days=30)
        all_dates = []
        d = cutoff_date
        while d <= today:
            all_dates.append(d.strftime("%Y-%m-%d"))
            d += timedelta(days=1)

        titles = ["进场飞机 (架次)", "离场飞机 (架次)", "分配地勤 (架次)", "分配地勤 (人次)"]
        colors = ["#2196F3", "#4CAF50", "#FF9800", "#E91E63"]
        col_indices = [0, 1, 2, 3]

        outer = ttkb.Frame(win)
        outer.pack(fill=BOTH, expand=True, padx=10, pady=10)

        # 所有图表共享同一个 offset，默认显示最右侧（最新日期）
        shared_state = {"drawers": []}

        for idx in range(4):
            vals = []
            for dt in all_dates:
                row = data_dict.get(dt)
                vals.append((row[col_indices[idx]] if row is not None else None))
            labels = [d[5:] for d in all_dates]
            self._draw_chart_panel(outer, titles[idx], labels, vals, colors[idx], shared_state)

        win.after(50, lambda: self._center_toplevel_on_parent(win))

    def _draw_chart_panel(self, parent, title, labels, values, color, shared_state=None):
        frame = ttkb.Labelframe(parent, text=title, padding=5)
        frame.pack(fill=X, pady=4)

        cw, ch = 740, 140
        margin_l, margin_r, margin_t, margin_b = 50, 15, 15, 25
        plot_w = cw - margin_l - margin_r
        plot_h = ch - margin_t - margin_b

        canvas = tk.Canvas(frame, width=cw, height=ch, bg="white", highlightthickness=0)
        canvas.pack()

        n = len(values)
        v_max = max((v for v in values if v is not None), default=1)
        if v_max == 0:
            v_max = 1

        y_ticks = 5
        step = v_max / y_ticks
        if step < 1:
            step = 1
            y_ticks = int(v_max)
        else:
            nice_steps = [1, 2, 5, 10, 20, 25, 50, 100, 200, 500, 1000]
            for ns in nice_steps:
                if ns >= step:
                    step = ns
                    break
            v_max = step * y_ticks

        canvas.create_line(margin_l, margin_t, margin_l, ch - margin_b, fill="#cccccc")
        canvas.create_line(margin_l, ch - margin_b, cw - margin_r, ch - margin_b, fill="#cccccc")

        for i in range(y_ticks + 1):
            yv = int(step * i)
            yp = ch - margin_b - (yv / v_max) * plot_h
            canvas.create_line(margin_l - 3, yp, cw - margin_r, yp, fill="#eeeeee", dash=(2, 4))
            canvas.create_text(margin_l - 6, yp, text=str(yv), anchor="e", font=("Consolas", 7), fill="#888888")

        if n == 1:
            spacing = plot_w
        else:
            spacing = plot_w / (n - 1)

        visible = max(1, int(plot_w / 48))

        if shared_state is not None:
            # 初始化共享状态（仅第一次）
            if "visible" not in shared_state:
                shared_state["visible"] = visible
            if "n" not in shared_state:
                shared_state["n"] = n
            if "offset" not in shared_state:
                shared_state["offset"] = max(0, n - visible)
            state = shared_state
        else:
            state = {"offset": max(0, n - visible)}

        def _draw(off):
            canvas.delete("plotdata")
            end = min(n, off + visible)
            seg = list(range(off, end))
            if not seg:
                return
            seg_n = len(seg)
            sp = (plot_w / (seg_n - 1)) if seg_n > 1 else plot_w

            for si, gi in enumerate(seg):
                xp = margin_l + si * sp
                if si % max(1, seg_n // 8) == 0 or si == seg_n - 1:
                    canvas.create_text(xp, ch - margin_b + 12, text=labels[gi],
                                       font=("Consolas", 7), fill="#888888", tags="plotdata")

            points = []
            for si, gi in enumerate(seg):
                xp = margin_l + si * sp
                v = values[gi]
                if v is not None:
                    yp = ch - margin_b - (v / v_max) * plot_h
                    points.append((xp, yp, v))
                else:
                    yp = ch - margin_b
                    points.append((xp, yp, 0))

            for i in range(len(points) - 1):
                x1, y1, v1 = points[i]
                x2, y2, v2 = points[i + 1]
                canvas.create_line(x1, y1, x2, y2, fill=color, width=2, tags="plotdata")

            for xp, yp, v in points:
                canvas.create_oval(xp - 3, yp - 3, xp + 3, yp + 3, fill=color, outline="white",
                                   width=1, tags="plotdata")
                if v > 0:
                    canvas.create_text(xp, yp - 10, text=str(v),
                                       font=("Consolas", 7), fill=color, tags="plotdata")

        _draw(state["offset"])

        # 注册本图表的重绘回调，供联动使用
        if shared_state is not None:
            if "drawers" not in shared_state:
                shared_state["drawers"] = []
            shared_state["drawers"].append(lambda: _draw(shared_state["offset"]))

        def _on_scroll(event):
            if event.delta > 0:
                state["offset"] = max(0, state["offset"] - 1)
            else:
                state["offset"] = min(max(0, n - visible), state["offset"] + 1)
            # 联动重绘所有图表
            if isinstance(state, dict) and "drawers" in state:
                for d in state["drawers"]:
                    d()
            else:
                _draw(state["offset"])

        drag_state = {"x": None}

        def _on_press(event):
            drag_state["x"] = event.x

        def _on_drag(event):
            if drag_state["x"] is None:
                return
            dx = event.x - drag_state["x"]
            if abs(dx) > 20:
                if dx > 0:
                    state["offset"] = max(0, state["offset"] - 1)
                else:
                    state["offset"] = min(max(0, n - visible), state["offset"] + 1)
                drag_state["x"] = event.x
                # 联动重绘所有图表
                if isinstance(state, dict) and "drawers" in state:
                    for d in state["drawers"]:
                        d()
                else:
                    _draw(state["offset"])

        def _on_release(event):
            drag_state["x"] = None

        canvas.bind("<MouseWheel>", _on_scroll)
        canvas.bind("<ButtonPress-1>", _on_press)
        canvas.bind("<B1-Motion>", _on_drag)
        canvas.bind("<ButtonRelease-1>", _on_release)

    def open_settings_window(self):
        if hasattr(self, 'settings_win') and self.settings_win.winfo_exists():
            self.settings_win.lift()
            return
        if not self._enforce_online_guard("打开高级设置", interactive=True):
            return
        win = ttkb.Toplevel(self)
        self.settings_win = win
        win.title("高级设置")
        win.geometry("1280x860")
        win.minsize(1220, 820)
        win.transient(self)
        win.grab_set()
        body = ttkb.Frame(win, padding=20)
        body.pack(fill=BOTH, expand=True)

        header = ttkb.Frame(body, padding=(16, 14))
        header.pack(fill=X, pady=(0, 12))
        ttkb.Label(header, text="高级设置中心", font=("Microsoft YaHei UI", 15, "bold"), bootstyle="primary").pack(anchor="w")
        ttkb.Label(header, text="统一新版风格，保留设备、触控、防检测和在线校验相关配置。", bootstyle="secondary").pack(anchor="w", pady=(4, 0))

        top_action_row = ttkb.Frame(body)
        top_action_row.pack(fill=X, pady=(0, 12))

        online_frame = ttkb.Labelframe(body, text="在线验证", padding=12, bootstyle="success")
        online_frame.pack(fill=X, pady=(0, 12))
        ttkb.Label(online_frame, textvariable=self.var_online_detail, wraplength=470, justify="left", bootstyle="secondary").pack(anchor="w")
        online_btn_row = ttkb.Frame(online_frame)
        online_btn_row.pack(fill=X, pady=(8, 0))
        ttkb.Button(online_btn_row, text="立即在线验证", bootstyle="success-outline", command=self.run_online_validation).pack(side=LEFT)
        ttkb.Button(online_btn_row, text="国内网络方案", bootstyle="warning-outline", command=self.show_cn_network_help).pack(side=LEFT, padx=8)
        ttkb.Button(online_btn_row, text="官方仓库", bootstyle="primary-outline", command=self.open_official_repo).pack(side=LEFT)

        notebook = ttkb.Notebook(body, bootstyle="primary")
        notebook.pack(fill=BOTH, expand=True, pady=(0, 12))
        tab_device = ttkb.Frame(notebook, padding=16)
        tab_runtime = ttkb.Frame(notebook, padding=16)
        tab_notify = ttkb.Frame(notebook, padding=16)
        notebook.add(tab_device, text="设备与方案")
        notebook.add(tab_runtime, text="运行与防检测")
        notebook.add(tab_notify, text="手机报错提醒")

        tab_device_left, tab_device_right = self._build_two_columns(tab_device)
        tab_runtime_left, tab_runtime_right = self._build_two_columns(tab_runtime)
        tab_notify_left, tab_notify_right = self._build_two_columns(tab_notify)

        ttkb.Label(tab_notify_left, text="一键接入手机提醒", font=("bold")).pack(anchor="w")
        ttkb.Label(
            tab_notify_left,
            text="脚本出现报错时，自动把提醒推送到企业微信或钉钉机器人。",
            bootstyle="secondary",
        ).pack(anchor="w", pady=(4, 10))

        f_notify_enable = ttkb.Frame(tab_notify_left)
        f_notify_enable.pack(fill=X, pady=5)
        ttkb.Checkbutton(
            f_notify_enable,
            text="启用手机报错提醒",
            variable=self.var_notify_enabled,
            bootstyle="success-round-toggle",
        ).pack(side=LEFT)
        self.create_info_icon(
            f_notify_enable,
            "开启后，当脚本出现运行报错、严重错误、自动停机时会推送提醒。",
        ).pack(side=LEFT, padx=5)

        f_notify_provider = ttkb.Frame(tab_notify_left)
        f_notify_provider.pack(fill=X, pady=5)
        ttkb.Label(f_notify_provider, text="提醒平台:").pack(side=LEFT)
        provider_combo = ttkb.Combobox(
            f_notify_provider,
            values=("企业微信机器人", "钉钉机器人"),
            state="readonly",
            width=16,
        )
        provider_combo.pack(side=LEFT, padx=8)
        if self.var_notify_provider.get().strip().lower() == "dingtalk":
            provider_combo.current(1)
        else:
            provider_combo.current(0)

        f_notify_webhook = ttkb.Frame(tab_notify_left)
        f_notify_webhook.pack(fill=X, pady=5)
        ttkb.Label(f_notify_webhook, text="Webhook 地址:").pack(side=LEFT)
        e_notify_webhook = ttkb.Entry(f_notify_webhook, textvariable=self.var_notify_webhook)
        e_notify_webhook.pack(side=LEFT, fill=X, expand=True, padx=(8, 0))

        f_notify_keyword = ttkb.Frame(tab_notify_left)
        f_notify_keyword.pack(fill=X, pady=5)
        ttkb.Label(f_notify_keyword, text="关键词(可选):").pack(side=LEFT)
        e_notify_keyword = ttkb.Entry(f_notify_keyword, textvariable=self.var_notify_keyword, width=24)
        e_notify_keyword.pack(side=LEFT, padx=8)
        self.create_info_icon(
            f_notify_keyword,
            "部分机器人会要求消息包含指定关键词；没有要求可留空。",
        ).pack(side=LEFT, padx=5)

        def test_mobile_notify():
            provider = "dingtalk" if provider_combo.current() == 1 else "wecom"
            self.var_notify_provider.set(provider)
            self.var_notify_webhook.set(e_notify_webhook.get().strip())
            self.var_notify_keyword.set(e_notify_keyword.get().strip())
            if not self.var_notify_webhook.get().strip():
                messagebox.showwarning("提示", "请先填写 Webhook 地址", parent=win)
                return
            self._send_mobile_notify("测试提醒", "这是一条测试消息，说明机器人接入成功。", force=True)

        ttkb.Button(
            tab_notify_left,
            text="发送测试提醒",
            bootstyle="info-outline",
            width=16,
            command=test_mobile_notify,
        ).pack(anchor="w", pady=(10, 0))

        ttkb.Separator(tab_notify_left).pack(fill=X, pady=10)
        ttkb.Label(tab_notify_left, text="定时统计汇报", font=("bold")).pack(anchor="w")
        f_stats_report_enable = ttkb.Frame(tab_notify_left)
        f_stats_report_enable.pack(fill=X, pady=5)
        ttkb.Checkbutton(
            f_stats_report_enable,
            text="启用定时统计汇报",
            variable=self.var_stats_report_enabled,
            bootstyle="success-round-toggle",
        ).pack(side=LEFT)
        self.create_info_icon(
            f_stats_report_enable,
            "启用后会按设定周期将运行统计自动推送到机器人。",
        ).pack(side=LEFT, padx=5)

        f_stats_report_interval = ttkb.Frame(tab_notify_left)
        f_stats_report_interval.pack(fill=X, pady=5)
        ttkb.Label(f_stats_report_interval, text="汇报周期:").pack(side=LEFT)
        stats_report_combo = ttkb.Combobox(
            f_stats_report_interval,
            values=("3", "6", "12", "24"),
            state="readonly",
            width=8,
        )
        stats_current = str(self._normalize_stats_report_hours(self.var_stats_report_hours.get()))
        stats_report_combo.set(stats_current)
        stats_report_combo.pack(side=LEFT, padx=8)
        ttkb.Label(f_stats_report_interval, text="小时", bootstyle="secondary").pack(side=LEFT)

        def send_stats_report_now():
            self.var_stats_report_hours.set(stats_report_combo.get().strip() or "6")
            if not self.var_notify_webhook.get().strip():
                messagebox.showwarning("提示", "请先填写 Webhook 地址", parent=win)
                return
            self._send_stats_report(manual=True)

        ttkb.Button(
            tab_notify_left,
            text="立即发送统计汇报",
            bootstyle="secondary-outline",
            width=16,
            command=send_stats_report_now,
        ).pack(anchor="w", pady=(6, 0))

        ttkb.Label(tab_notify_right, text="小白接入指引", font=("bold")).pack(anchor="w")
        guide_lines = [
            "1. 在企业微信/钉钉群里添加自定义机器人，复制 Webhook 地址。",
            "2. 选择提醒平台并粘贴 Webhook，必要时填写关键词。",
            "3. 点击“发送测试提醒”，手机收到消息后再点保存设置。",
            "4. 后续脚本报错会自动推送，避免人不在电脑旁时漏看。",
        ]
        for line in guide_lines:
            ttkb.Label(tab_notify_right, text=line, bootstyle="secondary", justify="left", wraplength=460).pack(anchor="w", pady=2)

        ttkb.Label(tab_device_left, text="手动连接", font=("bold")).pack(anchor="w")
        f_manual = ttkb.Frame(tab_device_left);
        f_manual.pack(fill=X, pady=5)
        e_manual_ip = ttkb.Entry(f_manual)
        e_manual_ip.pack(side=LEFT, fill=X, expand=True, padx=(0, 5))
        e_manual_ip.insert(0, self.config.get("last_manual_adb_target", ""))

        def run_manual_connect():
            ip = e_manual_ip.get().strip()
            if ip:
                self.config["last_manual_adb_target"] = ip
                print(f">>> 尝试手动连接: {ip}")
                try:
                    adb_exe = adb_mod.CURRENT_ADB_PATH if adb_mod.CURRENT_ADB_PATH else "adb"
                    subprocess.run([adb_exe, "connect", ip], timeout=5, creationflags=0x08000000)
                    self.refresh_devices()
                except Exception as e:
                    print(f"❌ 连接失败: {e}")

        # 【颜色统一】手动连接按钮 -> 绿色
        ttkb.Button(f_manual, text="连接", bootstyle="success", command=run_manual_connect).pack(side=LEFT)
        self.create_info_icon(f_manual, "支持局域网 ADB、公网云手机、云真机，格式示例：1.2.3.4:5555 或 example.com:4555").pack(side=LEFT, padx=6)

        ttkb.Separator(tab_device_left).pack(fill=X, pady=10)
        ttkb.Label(tab_device_left, text="公网 ADB / 云手机", font=("bold")).pack(anchor="w")
        ttkb.Label(
            tab_device_left,
            text="参考 ALAS 云服务器方案：把公网云手机地址填在这里，扫描设备或启动脚本时会自动连接。",
            bootstyle="secondary",
            wraplength=520,
            justify="left",
        ).pack(anchor="w", pady=(4, 6))
        public_adb_box = ScrolledText(tab_device_left, height=6, font=("Consolas", 9), relief="flat")
        public_adb_box.pack(fill=X, pady=(0, 6))
        public_adb_box.insert("1.0", self.var_public_adb_targets.get())

        public_adb_hint = ttkb.Frame(tab_device_left)
        public_adb_hint.pack(fill=X, pady=(0, 6))
        ttkb.Label(public_adb_hint, text="每行一个地址，例如：47.101.10.8:5555", bootstyle="secondary").pack(side=LEFT)

        f_public_adb_actions = ttkb.Frame(tab_device_left)
        f_public_adb_actions.pack(fill=X, pady=(0, 8))

        def _get_public_adb_text():
            return public_adb_box.get("1.0", END).strip()

        def test_public_adb_targets():
            raw = _get_public_adb_text()
            targets = self._parse_public_adb_targets(raw)
            if not targets:
                messagebox.showwarning("提示", "请至少填写一个 host:port 地址", parent=win)
                return
            self.var_public_adb_targets.set(raw)
            self.config["public_adb_targets"] = raw
            connected, failed = self._connect_public_adb_targets(targets, debug=True)
            self.save_config()
            self.refresh_devices()
            msg = [f"成功: {len(connected)} 台", f"失败: {len(failed)} 台"]
            if connected:
                msg.append("\n成功列表:\n" + "\n".join(connected[:8]))
            if failed:
                fail_lines = [f"{target} -> {reason}" for target, reason in failed[:5]]
                msg.append("\n失败列表:\n" + "\n".join(fail_lines))
            messagebox.showinfo("公网 ADB 测试结果", "\n".join(msg), parent=win)

        def import_manual_target_to_public():
            target = e_manual_ip.get().strip()
            if not target:
                messagebox.showwarning("提示", "请先在上方输入一个公网 ADB 地址", parent=win)
                return
            current = _get_public_adb_text()
            merged = current.splitlines() if current else []
            if target not in merged:
                merged.append(target)
            public_adb_box.delete("1.0", END)
            public_adb_box.insert("1.0", "\n".join([line for line in merged if str(line).strip()]))

        ttkb.Button(f_public_adb_actions, text="测试并连接", bootstyle="info-outline", command=test_public_adb_targets).pack(side=LEFT)
        ttkb.Button(f_public_adb_actions, text="加入上方地址", bootstyle="secondary-outline", command=import_manual_target_to_public).pack(side=LEFT, padx=8)

        ttkb.Separator(tab_device_left).pack(fill=X, pady=10)
        ttkb.Label(tab_device_left, text="ADB 路径", font=("bold")).pack(anchor="w")
        f_adb = ttkb.Frame(tab_device_left);
        f_adb.pack(fill=X, pady=5)
        e_adb = ttkb.Entry(f_adb)
        e_adb.pack(side=LEFT, fill=X, expand=True, padx=(0, 5))
        if self.config.get("adb_path"): e_adb.insert(0, self.config["adb_path"])

        def browse():
            p = filedialog.askopenfilename(parent=win, filetypes=[("EXE", "*.exe")])
            if p: e_adb.delete(0, END); e_adb.insert(0, p)
            win.lift()

        # 【颜色统一】浏览路径按钮 -> 绿色边框
        ttkb.Button(f_adb, text="...", bootstyle="outline-success", command=browse).pack(side=LEFT)

        ttkb.Label(tab_device_left, text="MuMu 安装路径", font=("bold")).pack(anchor="w")
        f_mumu = ttkb.Frame(tab_device_left)
        f_mumu.pack(fill=X, pady=5)
        e_mumu = ttkb.Entry(f_mumu)
        e_mumu.pack(side=LEFT, fill=X, expand=True, padx=(0, 5))
        mp = self.config.get("mumu_path", "")
        if mp:
            e_mumu.insert(0, mp)

        def browse_mumu():
            p = filedialog.askdirectory(parent=win, title="选择 MuMu 安装目录")
            if p:
                e_mumu.delete(0, END)
                e_mumu.insert(0, p)
            win.lift()

        ttkb.Button(f_mumu, text="...", bootstyle="outline-success", command=browse_mumu).pack(side=LEFT)
        ToolTip(e_mumu, text="此路径仅用于 nemu_ipc 截图，非必需。留空则自动检测；自动检测成功时会回填此处。", bootstyle="info")

        ttkb.Separator(tab_device_right).pack(fill=X, pady=10)
        ttkb.Label(tab_device_right, text="触控方式（影响运行速度，但总体不明显）", font=("bold")).pack(anchor="w")
        f_ctrl = ttkb.Frame(tab_device_right)
        f_ctrl.pack(fill=X, pady=5)
        ctrl_values = ("ADB", "uiautomator2")
        ctrl_method = ttkb.Combobox(f_ctrl, values=ctrl_values, state="readonly", width=16)
        ctrl_method.pack(side=LEFT, padx=(0, 5))
        cm = self.config.get("control_method", "adb").lower()
        idx = next((i for i, v in enumerate(ctrl_values) if v.lower() == cm), 0)
        ctrl_method.current(idx)
        tip = ("选择点击/滑动时使用的方案，速度越快脚本反应越灵敏。\n\n"
               "• ADB：系统自带方式，兼容性最好但较慢。\n"
               "• uiautomator2：速度较快，滑动速度慢。")
        self.create_info_icon(f_ctrl, tip).pack(side=LEFT, padx=5)

        ttkb.Label(tab_device_right, text="截图方式（对整体运行速度影响最大）", font=("bold")).pack(anchor="w")
        f_scshot = ttkb.Frame(tab_device_right)
        f_scshot.pack(fill=X, pady=5)
        scshot_method = ttkb.Combobox(f_scshot, values=("ADB", "nemu_ipc", "uiautomator2", "DroidCast_raw"), state="readonly", width=16)
        scshot_method.pack(side=LEFT, padx=(0, 5))
        sm = self.config.get("screenshot_method", "nemu_ipc")
        if sm == "nemu_ipc":
            scshot_method.current(1)
        elif sm == "uiautomator2":
            scshot_method.current(2)
        elif sm == "droidcast_raw":
            scshot_method.current(3)
        else:
            scshot_method.current(0)
        self.create_info_icon(f_scshot,
            "选择获取屏幕画面的方式；截图越慢，整体运行越慢，建议优先选快的。\n\n"
            "• nemu_ipc：仅 MuMu 模拟器可用，速度极快。\n"
            "• uiautomator2：速度次快。\n"
            "• DroidCast_raw：速度较慢。\n"
            "• ADB：系统自带方式，兼容性最好但最慢。").pack(side=LEFT, padx=5)

        f_probe = ttkb.Frame(tab_device_right)
        f_probe.pack(fill=X, pady=(2, 8))

        def run_method_probe():
            device = self.combo_devices.get().strip()
            if not device:
                messagebox.showwarning("提示", "请先在主界面选择设备", parent=win)
                return
            probe_btn.configure(state="disabled", text="自检中...")

            def _worker():
                result = None
                err = None
                ctrl = (ctrl_method.get().strip().lower() or "adb")
                shot = (scshot_method.get().strip().lower() or "adb")
                if shot == "droidcast_raw":
                    shot = "droidcast_raw"
                try:
                    adb = AdbController(target_device=device, control_method=ctrl, screenshot_method=shot, instance_id=INSTANCE_ID)
                    adb.set_mumu_path(self.config.get("mumu_path", ""))
                    result = adb.ensure_methods_usable()
                    adb.close()
                except Exception as e:
                    err = str(e)

                def _done():
                    probe_btn.configure(state="normal", text="方案自检")
                    if err:
                        messagebox.showerror("自检失败", f"方案自检异常: {err}", parent=win)
                        return
                    if not result:
                        messagebox.showerror("自检失败", "未获得有效结果", parent=win)
                        return
                    self.config["control_method"] = result.get("control_method", "adb")
                    self.config["screenshot_method"] = result.get("screenshot_method", "adb")
                    self.save_config()
                    # 同步下拉框显示
                    new_ctrl = self.config["control_method"]
                    new_shot = self.config["screenshot_method"]
                    ctrl_values_l = [v.lower() for v in ctrl_values]
                    if new_ctrl in ctrl_values_l:
                        ctrl_method.current(ctrl_values_l.index(new_ctrl))
                    if new_shot == "nemu_ipc":
                        scshot_method.current(1)
                    elif new_shot == "uiautomator2":
                        scshot_method.current(2)
                    elif new_shot == "droidcast_raw":
                        scshot_method.current(3)
                    else:
                        scshot_method.current(0)
                    self.sync_all_configs_to_bot(from_advanced_save=True)
                    msg = f"触控: {result.get('control_method')}\n截图: {result.get('screenshot_method')}"
                    if result.get("repaired"):
                        msg += "\n\n已自动修复不可用方案。"
                    messagebox.showinfo("方案自检完成", msg, parent=win)

                self.after(0, _done)

            threading.Thread(target=_worker, daemon=True).start()

        probe_btn = ttkb.Button(f_probe, text="方案自检", bootstyle="info-outline", command=run_method_probe)
        probe_btn.pack(side=LEFT)
        self.create_info_icon(f_probe, "连接当前设备并检测触控/截图方案可用性；不可用时会自动回退到可用组合。")\
            .pack(side=LEFT, padx=6)

        ttkb.Separator(tab_runtime_left).pack(fill=X, pady=2)
        ttkb.Label(tab_runtime_left, text="速度优化（风险选项）", font=("bold")).pack(anchor="w")
        f_speed_row = ttkb.Frame(tab_runtime_left)
        f_speed_row.pack(fill=X, pady=5)
        ttkb.Checkbutton(f_speed_row, text="跳过二次校验", variable=self.var_speed_mode,
                         command=lambda: self._toggle_functional_switch("跳过二次校验", self.var_speed_mode),
                         bootstyle="success-round-toggle").pack(side=LEFT)
        self.create_info_icon(f_speed_row,
                              "跳过对于飞机类型的二次校验；\n风险较低，运行速度提升轻微。").pack(side=LEFT, padx=5)
        ttkb.Checkbutton(f_speed_row, text="跳过地勤分配验证", variable=self.var_skip_staff,
                         command=lambda: self._toggle_functional_switch("跳过地勤分配验证", self.var_skip_staff),
                         bootstyle="success-round-toggle").pack(side=LEFT, padx=(15, 0))
        self.create_info_icon(f_speed_row,
                              "地勤分配后不进行图标验证和颜色验证，直接开始；\n风险中等，可能导致飞机延误；\n仅推荐高峰期且有人在场时打开。").pack(side=LEFT, padx=5)

        ttkb.Separator(tab_runtime_left).pack(fill=X, pady=10)
        ttkb.Label(tab_runtime_left, text="防卡死", font=("bold")).pack(anchor="w")
        f_anti_stuck = ttkb.Frame(tab_runtime_left)
        f_anti_stuck.pack(fill=X, pady=5)
        ttkb.Checkbutton(
            f_anti_stuck,
            text="启用防卡死自动恢复与自动停机",
            variable=self.var_anti_stuck_enabled,
            command=lambda: self._toggle_functional_switch("启用防卡死", self.var_anti_stuck_enabled),
            bootstyle="success-round-toggle",
        ).pack(side=LEFT)
        self.create_info_icon(
            f_anti_stuck,
            "关闭后不再执行防卡死自修复和自动停机；\n游戏内错误弹窗检测与自动点击好的逻辑不会关闭。",
        ).pack(side=LEFT, padx=5)

        f_anti_stuck_threshold = ttkb.Frame(tab_runtime_left)
        f_anti_stuck_threshold.pack(fill=X, pady=5)
        ttkb.Label(f_anti_stuck_threshold, text="防卡死触发阈值:").pack(side=LEFT)
        e_anti_stuck_threshold = ttkb.Entry(f_anti_stuck_threshold, textvariable=self.var_anti_stuck_threshold, width=6)
        e_anti_stuck_threshold.pack(side=LEFT, padx=5)
        ttkb.Label(f_anti_stuck_threshold, text="范围 3-20", bootstyle="secondary").pack(side=LEFT, padx=(0, 8))

        def apply_anti_stuck_profile():
            try:
                threshold = int(e_anti_stuck_threshold.get().strip())
                threshold = max(3, min(20, threshold))
            except ValueError:
                messagebox.showerror("错误", "防卡死阈值必须为整数", parent=win)
                return
            self.var_anti_stuck_threshold.set(str(threshold))
            self.config["anti_stuck_enabled"] = self.var_anti_stuck_enabled.get()
            self.config["anti_stuck_threshold"] = threshold
            self.save_config()
            self.sync_all_configs_to_bot(from_advanced_save=True)
            print(f">>> [防卡死] 状态: {'开启' if self.var_anti_stuck_enabled.get() else '关闭'}")
            print(f">>> [防卡死] 触发阈值已更新: {threshold}")

        ttkb.Button(f_anti_stuck_threshold, text="确定", bootstyle="success-outline", command=apply_anti_stuck_profile, width=8).pack(side=LEFT)

        ttkb.Separator(tab_runtime_left).pack(fill=X, pady=10)
        ttkb.Label(tab_runtime_left, text="不起飞模式", font=("bold")).pack(anchor="w")

        f_no_takeoff_enable = ttkb.Frame(tab_runtime_left)
        f_no_takeoff_enable.pack(fill=X, pady=5)
        ttkb.Checkbutton(f_no_takeoff_enable, text="启用不起飞模式", variable=self.var_no_takeoff_mode,
                         command=lambda: self._toggle_functional_switch("不起飞模式", self.var_no_takeoff_mode),
                         bootstyle="success-round-toggle").pack(side=LEFT)
        self.create_info_icon(f_no_takeoff_enable,
                              "全新不起飞模式策略：\n"
                              "1. 塔台四个控制器全开时，只筛选停机坪待处理。\n"
                              "2. 仅 4 号塔台开启时，在待降落与停机坪之间轮流切换。\n"
                              "3. 开启不起飞模式后，会自动启用该模式自己的小退调度。\n"
                              "4. 当前筛选页中出现的任务，不再按图标类型限制，只要在目标页就执行。\n"
                              "建议配合塔台使用。").pack(side=LEFT, padx=5)

        f_no_takeoff_custom = ttkb.Frame(tab_runtime_left)
        f_no_takeoff_custom.pack(fill=X, pady=5)
        ttkb.Label(f_no_takeoff_custom, text="轮切间隔(秒):").pack(side=LEFT)
        e_nt_switch = ttkb.Entry(f_no_takeoff_custom, textvariable=self.var_no_takeoff_switch_interval, width=6)
        e_nt_switch.pack(side=LEFT, padx=(5, 10))
        ttkb.Label(f_no_takeoff_custom, text="自动小退间隔(分钟):").pack(side=LEFT)
        e_nt_auto_logout = ttkb.Entry(f_no_takeoff_custom, textvariable=self.var_no_takeoff_auto_logout_interval, width=6)
        e_nt_auto_logout.pack(side=LEFT, padx=(5, 10))

        def apply_no_takeoff_profile():
            try:
                switch_interval = max(3.0, min(300.0, float(e_nt_switch.get().strip())))
                logout_interval = max(1.0, min(120.0, float(e_nt_auto_logout.get().strip())))
            except ValueError:
                messagebox.showerror("错误", "不起飞模式时间设置必须为数字", parent=win)
                return
            self.var_no_takeoff_switch_interval.set(f"{switch_interval:g}")
            self.var_no_takeoff_auto_logout_interval.set(f"{logout_interval:g}")
            self.config["no_takeoff_switch_interval"] = switch_interval
            self.config["no_takeoff_auto_logout_interval"] = logout_interval
            self.save_config()
            self.sync_all_configs_to_bot(from_advanced_save=True)
            print(f">>> [不起飞模式] 轮切间隔已更新: {switch_interval:g} 秒")
            print(f">>> [不起飞模式] 自动小退间隔已更新: {logout_interval:g} 分钟")

        ttkb.Button(f_no_takeoff_custom, text="确定", bootstyle="success-outline", command=apply_no_takeoff_profile, width=8).pack(side=LEFT)

        f_logout_enable = ttkb.Frame(tab_runtime_left)
        f_logout_enable.pack(fill=X, pady=5)
        ttkb.Checkbutton(f_logout_enable, text="启用独立小退", variable=self.var_no_takeoff_logout_enabled,
                         command=lambda: self._toggle_functional_switch("启用独立小退", self.var_no_takeoff_logout_enabled),
                         bootstyle="success-round-toggle").pack(side=LEFT)
        self.create_info_icon(f_logout_enable,
                              "独立小退功能与不起飞模式自动小退分开。\n"
                              "即使不开启不起飞模式，也可以单独按固定间隔执行小退。\n"
                              "点击确定后立即写入配置并同步到运行中的脚本。").pack(side=LEFT, padx=5)

        f_cancel_filter = ttkb.Frame(tab_runtime_left)
        f_cancel_filter.pack(fill=X, pady=5)
        ttkb.Checkbutton(f_cancel_filter, text="塔台关闭时筛选全部飞机", variable=self.var_cancel_stand_filter,
                         command=lambda: self._toggle_functional_switch("塔台关闭时筛选全部飞机", self.var_cancel_stand_filter),
                         bootstyle="success-round-toggle").pack(side=LEFT)
        self.create_info_icon(f_cancel_filter,
                              "开启后，塔台关闭时，脚本会强制取消停机位飞机的筛选，处理全部的待处理飞机。" ).pack(side=LEFT, padx=5)

        f_logout = ttkb.Frame(tab_runtime_left)
        f_logout.pack(fill=X, pady=5)
        ttkb.Label(f_logout, text="独立小退间隔(分钟):").pack(side=LEFT)
        e_logout_single = ttkb.Entry(f_logout, textvariable=self.var_standalone_logout_interval, width=6)
        e_logout_single.pack(side=LEFT, padx=5)

        def apply_standalone_logout():
            try:
                logout_interval = max(1.0, min(120.0, float(e_logout_single.get().strip())))
            except ValueError:
                messagebox.showerror("错误", "独立小退时间必须为数字", parent=win)
                return
            self.var_standalone_logout_interval.set(f"{logout_interval:g}")
            self.config["standalone_logout_interval"] = logout_interval
            self.config["no_takeoff_logout_enabled"] = self.var_no_takeoff_logout_enabled.get()
            self.save_config()
            self.sync_all_configs_to_bot(from_advanced_save=True)
            print(f">>> [独立小退] 间隔已更新: {logout_interval:g} 分钟")
            print(f">>> [独立小退] 状态: {'开启' if self.var_no_takeoff_logout_enabled.get() else '关闭'}")

        ttkb.Button(f_logout, text="确定", bootstyle="success-outline", command=apply_standalone_logout, width=8).pack(side=LEFT, padx=(8, 0))
        self.create_info_icon(f_logout,
                              "独立小退采用固定间隔，不再使用随机范围。\n单位：分钟，范围 1-120。\n点击确定后生效。").pack(side=LEFT, padx=5)

        ttkb.Separator(tab_runtime_right).pack(fill=X, pady=10)
        ttkb.Label(tab_runtime_right, text="防检测设置", font=("bold")).pack(anchor="w")

        f_rnd = ttkb.Frame(tab_runtime_right);
        f_rnd.pack(fill=X, pady=5)
        # 【颜色统一】随机任务选择 -> 绿色开关
        ttkb.Checkbutton(f_rnd, text="随机任务选择", variable=self.var_random_task,
                         command=lambda: self._toggle_functional_switch("随机任务选择", self.var_random_task),
                         bootstyle="success-round-toggle").pack(side=LEFT)
        self.create_info_icon(f_rnd,
                              "开启后，脚本将在列表前3个任务中随机选择（80%概率），或从下方任务中随机选择（20%概率），以模拟真实操作。").pack(
            side=LEFT, padx=5)

        f_s = ttkb.Frame(tab_runtime_right);
        f_s.pack(fill=X, pady=5)
        ttkb.Label(f_s, text="地勤分配—拖动随机耗时(ms):").pack(side=LEFT)
        e_min = ttkb.Entry(f_s, width=5);
        e_min.pack(side=LEFT, padx=5)
        e_min.insert(0, str(self.config.get("slide_min", 250)))
        ttkb.Label(f_s, text="-").pack(side=LEFT)
        e_max = ttkb.Entry(f_s, width=5);
        e_max.pack(side=LEFT, padx=5)
        e_max.insert(0, str(self.config.get("slide_max", 500)))
        self.create_info_icon(f_s,
                              "控制地勤分配界面中滑块操作的持续时间。\n建议范围 200-500ms。\n若最低值小于200，可能出现地勤分配时滑动不到位的情况").pack(
            side=LEFT, padx=5)

        f_t = ttkb.Frame(tab_runtime_right);
        f_t.pack(fill=X, pady=5)
        ttkb.Label(f_t, text="随机思考时间:").pack(side=LEFT)
        c_th = ttkb.Combobox(f_t, values=("关闭", "短(0.1-0.4)", "中(0.3-1.0)", "长(0.8-2.0)"), state="readonly")
        cur = self.config.get("thinking_mode", 0)
        if 0 <= cur <= 3:
            c_th.current(cur)
        else:
            c_th.current(0)
        c_th.pack(side=LEFT, padx=5)
        self.create_info_icon(f_t,
                              "在点击操作前增加随机的“发呆”时间，\n模拟人类思考过程，大幅降低检测风险。\n追求极限速度可选择“关闭”。").pack(
            side=LEFT, padx=5)

        ttkb.Separator(tab_runtime_right).pack(fill=X, pady=16)

        def save():
            old_cfg = dict(self.config)
            ap = e_adb.get().strip()
            if ap and os.path.exists(ap):
                self.config["adb_path"] = ap
                set_custom_adb_path(ap)
            else:
                if "adb_path" in self.config: del self.config["adb_path"]
                set_custom_adb_path(None)
            mp = e_mumu.get().strip()
            if mp and os.path.isdir(mp):
                self.config["mumu_path"] = mp
            else:
                if "mumu_path" in self.config: del self.config["mumu_path"]
            ctrl = ctrl_method.get().strip().lower()
            valid_ctrl = ("adb", "uiautomator2")
            self.config["control_method"] = ctrl if ctrl in valid_ctrl else "adb"
            sshot = scshot_method.get().strip().lower()
            self.config["screenshot_method"] = sshot if sshot in ("adb", "nemu_ipc", "uiautomator2", "droidcast_raw") else "nemu_ipc"
            try:
                vm = int(e_min.get());
                vx = int(e_max.get())
                if vm < 100: vm = 100
                if vx > 2000: vx = 2000
                if vx < vm: vx = vm
                self.config["slide_min"] = vm;
                self.config["slide_max"] = vx
            except:
                messagebox.showerror("错误", "输入整数", parent=win)
                return
            self.config["thinking_mode"] = c_th.current()
            self.config["speed_mode"] = self.var_speed_mode.get()
            self.config["skip_staff"] = self.var_skip_staff.get()
            self.config["no_takeoff_mode"] = self.var_no_takeoff_mode.get()
            self.config["no_takeoff_logout_enabled"] = self.var_no_takeoff_logout_enabled.get()
            self.config["cancel_stand_filter"] = self.var_cancel_stand_filter.get()
            self.config["random_task_order"] = self.var_random_task.get()
            self.config["anti_stuck_enabled"] = self.var_anti_stuck_enabled.get()
            notify_provider = "dingtalk" if provider_combo.current() == 1 else "wecom"
            notify_webhook = e_notify_webhook.get().strip()
            notify_keyword = e_notify_keyword.get().strip()
            stats_report_enabled = bool(self.var_stats_report_enabled.get())
            stats_report_hours = self._normalize_stats_report_hours(stats_report_combo.get().strip())
            public_adb_targets = _get_public_adb_text()
            self.var_notify_provider.set(notify_provider)
            self.var_notify_webhook.set(notify_webhook)
            self.var_notify_keyword.set(notify_keyword)
            self.var_stats_report_hours.set(str(stats_report_hours))
            self.var_public_adb_targets.set(public_adb_targets)
            self.config["mobile_notify_enabled"] = bool(self.var_notify_enabled.get())
            self.config["mobile_notify_provider"] = notify_provider
            self.config["mobile_notify_webhook"] = notify_webhook
            self.config["mobile_notify_keyword"] = notify_keyword
            self.config["mobile_stats_report_enabled"] = stats_report_enabled
            self.config["mobile_stats_report_hours"] = stats_report_hours
            self.config["public_adb_targets"] = public_adb_targets
            if self.config["mobile_notify_enabled"] and not notify_webhook:
                messagebox.showerror("错误", "已开启手机提醒，但未填写 Webhook 地址", parent=win)
                return
            self.config.pop("filter_switch_min", None)
            self.config.pop("filter_switch_max", None)
            try:
                nt_switch = max(3.0, min(300.0, float(e_nt_switch.get().strip())))
                nt_logout = max(1.0, min(120.0, float(e_nt_auto_logout.get().strip())))
                logout_single = max(1.0, min(120.0, float(e_logout_single.get().strip())))
            except (ValueError, AttributeError):
                messagebox.showerror("错误", "不起飞模式或小退时间必须为数字", parent=win)
                return
            self.var_no_takeoff_switch_interval.set(f"{nt_switch:g}")
            self.var_no_takeoff_auto_logout_interval.set(f"{nt_logout:g}")
            self.var_standalone_logout_interval.set(f"{logout_single:g}")
            self.config["no_takeoff_switch_interval"] = nt_switch
            self.config["no_takeoff_auto_logout_interval"] = nt_logout
            self.config["standalone_logout_interval"] = logout_single
            self.config.pop("no_takeoff_logout_min", None)
            self.config.pop("no_takeoff_logout_max", None)
            try:
                anti_stuck_threshold = int(e_anti_stuck_threshold.get().strip())
                anti_stuck_threshold = max(3, min(20, anti_stuck_threshold))
            except (ValueError, AttributeError):
                messagebox.showerror("错误", "防卡死阈值必须为整数", parent=win)
                return
            self.var_anti_stuck_threshold.set(str(anti_stuck_threshold))
            self.config["anti_stuck_threshold"] = anti_stuck_threshold

            changed = []
            if old_cfg.get("adb_path") != self.config.get("adb_path"):
                v = self.config.get("adb_path") or "自动"
                changed.append(("ADB 路径", str(v)))
            if old_cfg.get("mumu_path") != self.config.get("mumu_path"):
                v = self.config.get("mumu_path") or "自动"
                changed.append(("MuMu 安装路径", str(v)))
            if old_cfg.get("control_method") != self.config.get("control_method"):
                changed.append(("触控方式", self.config.get("control_method", "adb")))
            if old_cfg.get("screenshot_method") != self.config.get("screenshot_method"):
                changed.append(("截图方式", self.config.get("screenshot_method", "nemu_ipc")))
            if old_cfg.get("speed_mode") != self.config.get("speed_mode"):
                changed.append(("跳过二次校验", "开" if self.config.get("speed_mode") else "关"))
            if old_cfg.get("skip_staff") != self.config.get("skip_staff"):
                changed.append(("跳过地勤分配验证", "开" if self.config.get("skip_staff") else "关"))
            if old_cfg.get("no_takeoff_mode") != self.config.get("no_takeoff_mode"):
                changed.append(("不起飞模式", "开" if self.config.get("no_takeoff_mode") else "关"))
            if old_cfg.get("no_takeoff_logout_enabled") != self.config.get("no_takeoff_logout_enabled"):
                changed.append(("独立小退", "开" if self.config.get("no_takeoff_logout_enabled") else "关"))
            if old_cfg.get("cancel_stand_filter") != self.config.get("cancel_stand_filter"):
                changed.append(("塔台关闭筛选全部飞机", "开" if self.config.get("cancel_stand_filter") else "关"))
            if old_cfg.get("anti_stuck_enabled") != self.config.get("anti_stuck_enabled"):
                changed.append(("防卡死", "开" if self.config.get("anti_stuck_enabled") else "关"))
            if old_cfg.get("anti_stuck_threshold") != self.config.get("anti_stuck_threshold"):
                changed.append(("防卡死触发阈值", str(self.config.get("anti_stuck_threshold", 6))))
            if old_cfg.get("mobile_notify_enabled") != self.config.get("mobile_notify_enabled"):
                changed.append(("手机报错提醒", "开" if self.config.get("mobile_notify_enabled") else "关"))
            if old_cfg.get("mobile_notify_provider") != self.config.get("mobile_notify_provider"):
                changed.append(("提醒平台", "企业微信" if self.config.get("mobile_notify_provider") == "wecom" else "钉钉"))
            if old_cfg.get("mobile_stats_report_enabled") != self.config.get("mobile_stats_report_enabled"):
                changed.append(("定时统计汇报", "开" if self.config.get("mobile_stats_report_enabled") else "关"))
            if old_cfg.get("mobile_stats_report_hours") != self.config.get("mobile_stats_report_hours"):
                changed.append(("统计汇报周期", f"每 {self.config.get('mobile_stats_report_hours', 6)} 小时"))
            if old_cfg.get("public_adb_targets") != self.config.get("public_adb_targets"):
                changed.append(("公网 ADB 地址列表", f"{len(self._parse_public_adb_targets(public_adb_targets))} 项"))
            if old_cfg.get("no_takeoff_switch_interval") != self.config.get("no_takeoff_switch_interval"):
                changed.append(("不起飞轮切间隔", f"{self.config.get('no_takeoff_switch_interval', 15)} 秒"))
            if old_cfg.get("no_takeoff_auto_logout_interval") != self.config.get("no_takeoff_auto_logout_interval"):
                changed.append(("不起飞自动小退间隔", f"{self.config.get('no_takeoff_auto_logout_interval', 30)} 分钟"))
            if old_cfg.get("standalone_logout_interval") != self.config.get("standalone_logout_interval"):
                changed.append(("独立小退间隔", f"{self.config.get('standalone_logout_interval', 30)} 分钟"))

            anti_changed = (
                old_cfg.get("slide_min") != self.config.get("slide_min") or
                old_cfg.get("slide_max") != self.config.get("slide_max") or
                old_cfg.get("thinking_mode") != self.config.get("thinking_mode") or
                old_cfg.get("random_task_order") != self.config.get("random_task_order")
            )

            for name, val in changed:
                print(f">>> [高级设置] {name} 已更新: {val}")
            if anti_changed:
                print(f">>> [高级设置] 防检测: 随机任务={self.var_random_task.get()}, 滑块={vm}-{vx}ms, 思考时间={c_th.get()}")

            self.save_config()
            self.sync_all_configs_to_bot(from_advanced_save=True)
            win.destroy()

        ttkb.Button(top_action_row, text="保存设置", bootstyle="success", width=18, command=save).pack(side=LEFT)
        ttkb.Button(top_action_row, text="📊 统计图表", bootstyle="info-outline", width=18,
                command=self._open_stats_chart).pack(side=LEFT, padx=(10, 0))
        ttkb.Button(top_action_row, text="自愿资助", bootstyle="warning-outline", width=18,
            command=self.open_donate_window).pack(side=LEFT, padx=(10, 0))
        ttkb.Separator(body).pack(fill=X, pady=10)
        win.after(50, lambda: self._center_toplevel_on_parent(win))

    def refresh_devices(self):
        if not self._enforce_online_guard("扫描设备", interactive=True):
            return
        self._prepare_first_run_environment(
            force=not self.config.get("initial_device_paths_detected", False),
            reason="首次智能扫描",
        )
        print(">>> 正在扫描设备...")
        self.var_device_status.set("扫描中")
        self.btn_scan.configure(text="扫描中...", state="disabled")
        for btn in [self.btn_main_start, self.btn_mini_start]:
            btn.configure(state="disabled")
        self.update()
        try:
            devs = self._scan_devices_with_public_targets(debug=True)
        except Exception as e:
            print(f">>> [扫描异常] {e}")
            devs = []
        finally:
            self.btn_scan.configure(text="智能扫描", state="normal")
            if not (getattr(self, 'bot', None) and self.bot.running):
                for btn in [self.btn_main_start, self.btn_mini_start]:
                    btn.configure(state="normal", text="▶ 启动脚本")
        self.combo_devices['values'] = devs
        if devs:
            self.combo_devices.current(0)
            self.var_device_status.set(f"已连接候选 {len(devs)} 台")
            print(f">>> 扫描完成: 发现 {len(devs)} 台设备")
        else:
            self.var_device_status.set("未发现设备")
            print(">>> 扫描完成: 未发现设备")

    def _try_use_mumu_adb_for_device(self, device_serial):
        """MuMu 设备（可读画面但无法点击时）自动切换到 MuMu 自带 adb"""
        if self.config.get("adb_path"):
            return
        if "127.0.0.1:" not in device_serial:
            return
        try:
            port = int(device_serial.split(":")[-1])
        except (ValueError, IndexError):
            return
        if port not in _MUMU_PORTS:
            return
        mumu_adb = AdbController._find_mumu_adb()
        if mumu_adb and os.path.isfile(mumu_adb):
            set_custom_adb_path(mumu_adb)
            print(f">>> [MuMu] 检测到 MuMu 设备，已切换至模拟器自带 ADB 以支持点击操作")

    def start_bot(self):
        if not self._enforce_online_guard("启动脚本", interactive=True):
            return
        device = self.combo_devices.get()
        if not device: messagebox.showwarning("提示", "请先选择设备"); return
        if self.bot and self.bot.running: return
        self.var_runtime_status.set("准备启动")
        self.save_config()
        self._connect_public_adb_targets(debug=False)
        self._try_use_mumu_adb_for_device(device)
        for btn in [self.btn_main_start, self.btn_mini_start]:
            btn.configure(state="disabled", text="运行中...")
        for btn in [self.btn_main_stop, self.btn_mini_stop]:
            btn.configure(state="normal")
        self.combo_devices.configure(state="disabled")
        from main_adb import WoaBot
        self.bot = WoaBot(log_callback=self.log_to_queue, config_callback=self.on_bot_config_update,
                          instance_id=INSTANCE_ID)
        self.bot.set_device(device)
        self.sync_all_configs_to_bot()
        self.bot.start()
        self._stats_report_anchor_ts = time.time()
        self.var_runtime_status.set("运行中")

    def stop_bot(self):
        bot = self.bot
        if bot:
            bot.running = False
            bot.stop()
        self._stats_report_anchor_ts = 0.0
        self.bot = None
        self.var_runtime_status.set("已停止")
        if not getattr(self, "_is_closing", False):
            for btn in [self.btn_main_start, self.btn_mini_start]:
                btn.configure(state="normal", text="▶ 启动脚本")
            for btn in [self.btn_main_stop, self.btn_mini_stop]:
                btn.configure(state="disabled")
            self.combo_devices.configure(state="readonly")
            print(">>> 脚本已停止")

    def on_confirm_tower_delay(self):
        if not self._enforce_online_guard("应用挂机节奏", interactive=True):
            return
        self.sync_all_configs_to_bot()
        val_str = self.var_delay_count.get()
        if val_str == "0":
            print(f">>> [配置] 自动延时塔台: 已关闭")
        else:
            print(f">>> [配置] 自动延时塔台: 已更新为 {val_str} 次")

    def on_confirm_anti_stuck(self):
        if not self._enforce_online_guard("应用防卡死配置", interactive=True):
            return
        try:
            threshold = int(self.var_anti_stuck_threshold.get())
            threshold = max(3, min(20, threshold))
        except ValueError:
            threshold = 6
        self.var_anti_stuck_threshold.set(str(threshold))
        self.sync_all_configs_to_bot()
        print(f">>> [配置] 防卡死: {'已开启' if self.var_anti_stuck_enabled.get() else '已关闭'}，阈值 {threshold}")

    def sync_all_configs_to_bot(self, from_advanced_save=False):
        if not from_advanced_save and not self._enforce_online_guard("同步配置", interactive=False):
            return
        no_log = from_advanced_save
        try:
            cnt = int(self.var_delay_count.get())
            if cnt < 0:
                cnt = 0
            elif cnt > 144:
                cnt = 144
        except ValueError:
            cnt = self.config.get("auto_delay_count", 0)
        self.var_delay_count.set(str(cnt))
        self.config["auto_delay_count"] = cnt
        try:
            anti_stuck_threshold = int(self.var_anti_stuck_threshold.get())
            anti_stuck_threshold = max(3, min(20, anti_stuck_threshold))
        except ValueError:
            anti_stuck_threshold = int(self.config.get("anti_stuck_threshold", 6))
            anti_stuck_threshold = max(3, min(20, anti_stuck_threshold))
        self.var_anti_stuck_threshold.set(str(anti_stuck_threshold))
        self.config["anti_stuck_enabled"] = self.var_anti_stuck_enabled.get()
        self.config["anti_stuck_threshold"] = anti_stuck_threshold
        self.save_config()
        if self.bot:
            self.bot.set_bonus_staff_feature(self.var_bonus_staff.get())
            self.bot.set_vehicle_buy_feature(self.var_vehicle_buy.get())
            self.bot.set_speed_mode(self.var_speed_mode.get())
            self.bot.set_skip_staff_verify(self.var_skip_staff.get())
            self.bot.set_delay_bribe(self.var_delay_bribe.get())
            self.bot.set_auto_delay(cnt)
            self.bot.set_random_task_mode(self.var_random_task.get(), log_change=not no_log)
            self.bot.set_slide_duration_range(
                self.config.get("slide_min", 250), self.config.get("slide_max", 500), log_change=not no_log)
            self.bot.set_thinking_time_mode(self.config.get("thinking_mode", 0), log_change=not no_log)
            self.bot.set_no_takeoff_mode(self.var_no_takeoff_mode.get())
            self.bot.set_no_takeoff_switch_interval(self.config.get("no_takeoff_switch_interval", 15))
            self.bot.set_no_takeoff_auto_logout_interval(self.config.get("no_takeoff_auto_logout_interval", 30))
            self.bot.set_standalone_logout_interval(self.config.get("standalone_logout_interval", 30))
            self.bot.set_standalone_logout_enabled(self.config.get("no_takeoff_logout_enabled", False))
            self.bot.set_cancel_stand_filter_when_tower_off(self.var_cancel_stand_filter.get())
            self.bot.set_filter_stand_only_when_tower_open(self.var_tower_open_stand_only.get())
            self.bot.set_anti_stuck_config(self.var_anti_stuck_enabled.get(), anti_stuck_threshold, log_change=not no_log)
            self.bot.set_control_method(self.config.get("control_method", "adb"))
            self.bot.set_screenshot_method(self.config.get("screenshot_method", "nemu_ipc"))
            self.bot.set_mumu_path(self.config.get("mumu_path", ""))
            self.bot.set_active_branch(self.config.get("active_branch", "full"), log_change=not no_log)
            self.bot.set_module_flags(self.config.get("modules", {}), log_change=not no_log)

    def on_bot_config_update(self, key, value):
        def _apply_update():
            if key == "auto_delay_count":
                self.var_delay_count.set(str(value))
            elif key == "vehicle_buy":
                self.var_vehicle_buy.set(bool(value))
            elif key == "mumu_path":
                self.config["mumu_path"] = value
                self.save_config()
            elif key == "bot_stopped":
                self.bot = None
                self.var_runtime_status.set("已停止")
                for btn in [self.btn_main_start, self.btn_mini_start]:
                    btn.configure(state="normal", text="▶ 启动脚本")
                for btn in [self.btn_main_stop, self.btn_mini_stop]:
                    btn.configure(state="disabled")
                self.combo_devices.configure(state="readonly")
                print(f">>> [自动停止] {value}")
                # 兜底通知：即使日志关键词未命中，也保证自动停机会触发手机提醒。
                self._send_mobile_notify("脚本已自动停止", str(value or "脚本触发了自动停止"), force=True)

        try:
            self.after(0, _apply_update)
        except Exception:
            _apply_update()

    def log_to_queue(self, msg):
        self.log_queue.put(msg)
        self._check_error_and_notify(msg)

    def process_log_queue(self):
        self.redirector._flush_queue()
        self.after(self.queue_check_interval, self.process_log_queue)


if __name__ == "__main__":
    try:
        app = Application()
        app.mainloop()
    except Exception:
        # 捕获 mainloop 中的异常并手动调用异常处理钩子
        if sys.excepthook:
            sys.excepthook(*sys.exc_info())
        else:
            traceback.print_exc()
            sys.exit(1)