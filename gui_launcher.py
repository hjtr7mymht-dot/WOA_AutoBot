import sys
import os
import threading
import queue
import json
import datetime
import collections
import traceback
import tkinter as tk
import ctypes
import subprocess
import msvcrt
import shutil
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
from adb_controller import set_custom_adb_path, AdbController, CURRENT_ADB_PATH, close_all_and_kill_server, get_woa_debug_dir

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

LOCAL_VERSION = "1.0.0"
OFFICIAL_REPO_URL = "https://github.com/hjtr7mymht-dot/WOA_AutoBot"
OFFICIAL_REPO_NAME = "hjtr7mymht-dot/WOA_AutoBot"
ONLINE_VERSION_PATH = "version.json"

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
            myappid = 'woabot.launcher.v1.0.0'
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except:
            pass

        super().__init__(themename="sandstone")

        self.style.colors.success = "#4f6f52"
        self.style.colors.danger = "#b85c38"
        self.style.colors.primary = "#355c7d"
        self.style.colors.info = "#6c8ead"

        self.title(f"WOA AutoBot {LOCAL_VERSION}" + (f" [实例 {INSTANCE_ID}]" if INSTANCE_ID > 1 else ""))
        self.geometry("980x860")
        self.last_geometry = "980x860"
        self.is_mini_mode = False

        self.config = self.load_config()
        self.var_bonus_staff = tk.BooleanVar(value=self.config.get("bonus_staff", False))
        self.var_vehicle_buy = tk.BooleanVar(value=self.config.get("vehicle_buy", False))
        self.var_speed_mode = tk.BooleanVar(value=self.config.get("speed_mode", False))
        self.var_skip_staff = tk.BooleanVar(value=self.config.get("skip_staff", False))
        self.var_delay_bribe = tk.BooleanVar(value=self.config.get("delay_bribe", False))
        self.var_delay_count = tk.StringVar(value=str(self.config.get("auto_delay_count", 0)))
        self.var_random_task = tk.BooleanVar(value=self.config.get("random_task_order", True))
        self.var_no_takeoff_mode = tk.BooleanVar(value=self.config.get("no_takeoff_mode", False))
        self.var_no_takeoff_logout_enabled = tk.BooleanVar(
            value=self.config.get("no_takeoff_logout_enabled",
                                  bool(self.config.get("no_takeoff_logout_min", 0) or self.config.get("no_takeoff_logout_max", 0))))
        self.var_cancel_stand_filter = tk.BooleanVar(value=self.config.get("cancel_stand_filter", True))
        self.var_tower_open_stand_only = tk.BooleanVar(value=self.config.get("tower_open_stand_only", False))
        for legacy_key in (
            "auto_exit_time", "auto_exit_enabled", "auto_exit_rest_time", "auto_exit_rest_enabled",
            "auto_exit_loop_count", "auto_exit_loop_infinite", "restart_game_icon_file",
            "filter_switch_min", "filter_switch_max",
        ):
            self.config.pop(legacy_key, None)
        self.var_mini_top = tk.BooleanVar(value=False)
        self.var_runtime_status = tk.StringVar(value="待命")
        self.var_device_status = tk.StringVar(value="等待扫描设备")
        self.var_online_status = tk.StringVar(value="未验证")
        self.var_online_detail = tk.StringVar(value="官方仓库校验未执行")
        self._online_validation_running = False

        if self.config.get("adb_path"):
            set_custom_adb_path(self.config["adb_path"])

        self.bot = None
        self.log_queue = queue.Queue()
        self.queue_check_interval = 100

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

        self.container_main = ttkb.Frame(self)
        self.container_mini = ttkb.Frame(self)

        self.setup_main_ui()
        self.setup_mini_ui()

        self.container_main.pack(fill=BOTH, expand=True)
        self.after(self.queue_check_interval, self.process_log_queue)

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
        self.after(1200, lambda: self.run_online_validation(silent=True))
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
        self.config["no_takeoff_logout_enabled"] = self.var_no_takeoff_logout_enabled.get()
        try:
            self.config["auto_delay_count"] = int(self.var_delay_count.get())
        except:
            self.config["auto_delay_count"] = 0
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=4)
        except Exception as e:
            print(f"配置保存失败: {e}")

    def create_info_icon(self, parent, text):
        lbl = ttkb.Label(parent, text="ⓘ", font=("Segoe UI Symbol", 10), bootstyle="secondary", cursor="hand2")
        ToolTip(lbl, text=text, bootstyle="secondary-inverse")
        return lbl

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

    def setup_main_ui(self):
        outer = ttkb.Frame(self.container_main, padding=(18, 18, 18, 14))
        outer.pack(fill=BOTH, expand=True)

        hero = ttkb.Frame(outer, padding=(18, 16))
        hero.pack(fill=X)
        hero_left = ttkb.Frame(hero)
        hero_left.pack(side=LEFT, fill=X, expand=True)
        ttkb.Label(hero_left, text="WOA AutoBot Control Deck", font=("Microsoft YaHei UI", 18, "bold"), bootstyle="primary").pack(anchor="w")
        ttkb.Label(
            hero_left,
            text=f"版本 {LOCAL_VERSION} · 免费版本 请勿售卖 · 官方源 {OFFICIAL_REPO_NAME}",
            font=("Microsoft YaHei UI", 10),
            bootstyle="secondary",
        ).pack(anchor="w", pady=(4, 10))
        status_row = ttkb.Frame(hero_left)
        status_row.pack(fill=X)
        ttkb.Label(status_row, text="运行状态", font=("Microsoft YaHei UI", 9, "bold"), bootstyle="secondary").pack(side=LEFT)
        ttkb.Label(status_row, textvariable=self.var_runtime_status, padding=(10, 4), bootstyle="inverse-primary").pack(side=LEFT, padx=(8, 12))
        ttkb.Label(status_row, text="设备状态", font=("Microsoft YaHei UI", 9, "bold"), bootstyle="secondary").pack(side=LEFT)
        ttkb.Label(status_row, textvariable=self.var_device_status, padding=(10, 4), bootstyle="inverse-light").pack(side=LEFT, padx=(8, 0))
        online_row = ttkb.Frame(hero_left)
        online_row.pack(fill=X, pady=(8, 0))
        ttkb.Label(online_row, text="在线验证", font=("Microsoft YaHei UI", 9, "bold"), bootstyle="secondary").pack(side=LEFT)
        ttkb.Label(online_row, textvariable=self.var_online_status, padding=(10, 4), bootstyle="inverse-success").pack(side=LEFT, padx=(8, 12))
        ttkb.Label(online_row, textvariable=self.var_online_detail, bootstyle="secondary", wraplength=430, justify="left").pack(side=LEFT, fill=X, expand=True)

        hero_right = ttkb.Frame(hero)
        hero_right.pack(side=RIGHT, padx=(18, 0))
        f_help_wrap = ttkb.Frame(hero_right)
        f_help_wrap.pack(fill=X, pady=(0, 6))
        self.btn_help = ttkb.Button(f_help_wrap, text="使用说明", bootstyle="outline-info", command=self.open_help_window, width=14)
        self.btn_help.pack(fill=X)
        self._help_badge = None
        ttkb.Button(hero_right, text="高级设置", bootstyle="outline-secondary", command=self.open_settings_window, width=14).pack(fill=X, pady=6)
        ttkb.Button(hero_right, text="在线验证", bootstyle="outline-success", command=self.run_online_validation, width=14).pack(fill=X, pady=(0, 6))
        ttkb.Button(hero_right, text="紧凑小窗", bootstyle="outline-warning", command=self.toggle_mode, width=14).pack(fill=X)

        content = ttkb.Frame(outer)
        content.pack(fill=BOTH, expand=False, pady=(16, 14))
        left_col = ttkb.Frame(content)
        left_col.pack(side=LEFT, fill=BOTH, expand=True)
        right_col = ttkb.Frame(content)
        right_col.pack(side=LEFT, fill=BOTH, padx=(16, 0))

        connect_card = ttkb.Labelframe(left_col, text="连接与执行", padding=16, bootstyle="primary")
        connect_card.pack(fill=X)
        ttkb.Label(
            connect_card,
            text="选择设备后即可直接启动，扫描结果会自动刷新到状态区。",
            font=("Microsoft YaHei UI", 9),
            bootstyle="secondary",
        ).pack(anchor="w", pady=(0, 10))
        device_row = ttkb.Frame(connect_card)
        device_row.pack(fill=X)
        self.combo_devices = ttkb.Combobox(device_row, state="readonly", width=24)
        self.combo_devices.pack(side=LEFT, fill=X, expand=True, padx=(0, 8))
        self.btn_scan = ttkb.Button(device_row, text="智能扫描", bootstyle="outline-primary", command=self.refresh_devices, width=12)
        self.btn_scan.pack(side=LEFT)
        action_row = ttkb.Frame(connect_card)
        action_row.pack(fill=X, pady=(12, 0))
        self.btn_main_start = ttkb.Button(action_row, text="启动脚本", bootstyle="success", command=self.start_bot)
        self.btn_main_start.pack(side=LEFT, fill=X, expand=True, padx=(0, 6))
        self.btn_main_stop = ttkb.Button(action_row, text="停止运行", bootstyle="danger", state="disabled", command=self.stop_bot)
        self.btn_main_stop.pack(side=LEFT, fill=X, expand=True, padx=(6, 0))

        tower_card = ttkb.Labelframe(left_col, text="挂机节奏", padding=16, bootstyle="secondary")
        tower_card.pack(fill=X, pady=(14, 0))
        tower_top = ttkb.Frame(tower_card)
        tower_top.pack(fill=X)
        ttkb.Label(tower_top, text="自动延时塔台", font=("Microsoft YaHei UI", 10, "bold")).pack(side=LEFT)
        ttkb.Label(tower_top, text="仅控制已手动开启的控制器", bootstyle="secondary").pack(side=LEFT, padx=(8, 0))
        tower_row = ttkb.Frame(tower_card)
        tower_row.pack(fill=X, pady=(10, 0))
        ttkb.Entry(tower_row, textvariable=self.var_delay_count, width=6).pack(side=LEFT)
        ttkb.Label(tower_row, text="次", bootstyle="secondary").pack(side=LEFT, padx=(6, 10))
        ttkb.Button(tower_row, text="应用", bootstyle="outline-success", width=8, command=self.on_confirm_tower_delay).pack(side=LEFT)
        self.create_info_icon(
            tower_row,
            "填 0 表示关闭，最大值 144。脚本只会延时你已手动开启的控制器，不会改动塔台布局。",
        ).pack(side=LEFT, padx=8)

        quick_card = ttkb.Labelframe(right_col, text="快捷策略", padding=16, bootstyle="success")
        quick_card.pack(fill=X)

        def add_toggle_row(parent, text, var, help_txt):
            row = ttkb.Frame(parent)
            row.pack(fill=X, pady=4)
            ttkb.Checkbutton(
                row,
                text=text,
                variable=var,
                bootstyle="success-round-toggle",
                command=self.sync_all_configs_to_bot,
            ).pack(side=LEFT)
            self.create_info_icon(row, help_txt).pack(side=RIGHT)

        add_toggle_row(quick_card, "自动领取地勤", self.var_bonus_staff, "地勤不足时尝试领取免费地勤，重新开始脚本后冷却会重新计时。")
        add_toggle_row(quick_card, "自动购买地勤车辆", self.var_vehicle_buy, "地勤车辆不足时自动购买，属于实验性功能。")
        add_toggle_row(quick_card, "延误飞机贿赂", self.var_delay_bribe, "处理延误飞机时可自动贿赂代理，会消耗银飞机。")
        add_toggle_row(quick_card, "塔台全开仅停机位", self.var_tower_open_stand_only, "塔台四个控制器全开时，强制筛选为仅停机位待处理。")

        tools_card = ttkb.Labelframe(right_col, text="工具入口", padding=16, bootstyle="warning")
        tools_card.pack(fill=X, pady=(14, 0))
        ttkb.Label(
            tools_card,
            text="高级配置、在线验证、国内网络方案和紧凑模式都集中到了这里。",
            wraplength=260,
            justify="left",
            bootstyle="secondary",
        ).pack(anchor="w", pady=(0, 10))
        ttkb.Button(tools_card, text="打开高级设置", bootstyle="secondary", command=self.open_settings_window).pack(fill=X)
        ttkb.Button(tools_card, text="立即在线验证", bootstyle="success-outline", command=self.run_online_validation).pack(fill=X, pady=8)
        ttkb.Button(tools_card, text="官方仓库", bootstyle="primary-outline", command=self.open_official_repo).pack(fill=X)
        ttkb.Button(tools_card, text="国内网络方案", bootstyle="warning-outline", command=self.show_cn_network_help).pack(fill=X, pady=8)
        ttkb.Button(tools_card, text="查看使用说明", bootstyle="info-outline", command=self.open_help_window).pack(fill=X, pady=8)
        ttkb.Button(tools_card, text="切换紧凑小窗", bootstyle="warning-outline", command=self.toggle_mode).pack(fill=X)

        log_group = ttkb.Labelframe(outer, text="运行日志", padding=8, bootstyle="dark")
        log_group.pack(fill=BOTH, expand=True)
        self.txt_main_log = ScrolledText(log_group, state="disabled", font=("Consolas", 9), relief="flat", bg="#f7f3eb")
        self.txt_main_log.pack(fill=BOTH, expand=True)
        self.redirector.add_widget(self.txt_main_log)
        # 先显示 UI，延迟执行首次扫描（避免启动卡顿）
        self.after(100, self._do_initial_scan)

    def _do_initial_scan(self):
        """后台线程执行首次设备扫描，完成后更新 UI"""
        def _worker():
            try:
                devs = AdbController.scan_devices(debug=True)
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
                if remote_version == LOCAL_VERSION:
                    return {
                        "status": "已通过",
                        "detail": f"官方源可达，当前已是最新版，来源 {source_name}",
                        "message": f"在线验证通过\n\n本地版本: {LOCAL_VERSION}\n线上版本: {remote_version}\n来源: {source_name}\n地址: {url}",
                    }
                return {
                    "status": "发现更新",
                    "detail": f"检测到线上版本 {remote_version}，来源 {source_name}",
                    "message": f"检测到新版本\n\n本地版本: {LOCAL_VERSION}\n线上版本: {remote_version}\n来源: {source_name}\n地址: {url}",
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

    def run_online_validation(self, silent=False):
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
                    self.var_online_status.set("不可达")
                    self.var_online_detail.set("GitHub 直连和国内镜像均不可用")
                    if not silent:
                        messagebox.showerror(
                            "在线验证失败",
                            "未能连接官方仓库。\n\n已尝试 GitHub Raw、jsDelivr 与 ghproxy。\n可在“国内网络方案”中查看建议。\n\n错误信息:\n" + error,
                            parent=self,
                        )
                    return

                self.var_online_status.set(result["status"])
                self.var_online_detail.set(result["detail"])
                print(f">>> [在线验证] {result['detail']}")
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
        win = ttkb.Toplevel(self)
        self.settings_win = win
        win.title("高级设置")
        win.geometry("1120x760")
        win.transient(self)
        win.grab_set()
        body = ttkb.Frame(win, padding=20)
        body.pack(fill=BOTH, expand=True)

        header = ttkb.Frame(body, padding=(16, 14))
        header.pack(fill=X, pady=(0, 12))
        ttkb.Label(header, text="高级设置中心", font=("Microsoft YaHei UI", 15, "bold"), bootstyle="primary").pack(anchor="w")
        ttkb.Label(header, text="统一新版风格，保留设备、触控、防检测和在线校验相关配置。", bootstyle="secondary").pack(anchor="w", pady=(4, 0))

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
        notebook.add(tab_device, text="设备与方案")
        notebook.add(tab_runtime, text="运行与防检测")

        ttkb.Label(tab_device, text="手动连接", font=("bold")).pack(anchor="w")
        f_manual = ttkb.Frame(tab_device);
        f_manual.pack(fill=X, pady=5)
        e_manual_ip = ttkb.Entry(f_manual)
        e_manual_ip.pack(side=LEFT, fill=X, expand=True, padx=(0, 5))

        def run_manual_connect():
            ip = e_manual_ip.get().strip()
            if ip:
                print(f">>> 尝试手动连接: {ip}")
                try:
                    adb_exe = adb_mod.CURRENT_ADB_PATH if adb_mod.CURRENT_ADB_PATH else "adb"
                    subprocess.run([adb_exe, "connect", ip], timeout=5, creationflags=0x08000000)
                    self.refresh_devices()
                except Exception as e:
                    print(f"❌ 连接失败: {e}")

        # 【颜色统一】手动连接按钮 -> 绿色
        ttkb.Button(f_manual, text="连接", bootstyle="success", command=run_manual_connect).pack(side=LEFT)

        ttkb.Separator(tab_device).pack(fill=X, pady=10)
        ttkb.Label(tab_device, text="ADB 路径", font=("bold")).pack(anchor="w")
        f_adb = ttkb.Frame(tab_device);
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

        ttkb.Label(tab_device, text="MuMu 安装路径", font=("bold")).pack(anchor="w")
        f_mumu = ttkb.Frame(tab_device)
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

        ttkb.Separator(tab_device).pack(fill=X, pady=10)
        ttkb.Label(tab_device, text="触控方式（影响运行速度，但总体不明显）", font=("bold")).pack(anchor="w")
        f_ctrl = ttkb.Frame(tab_device)
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

        ttkb.Label(tab_device, text="截图方式（对整体运行速度影响最大）", font=("bold")).pack(anchor="w")
        f_scshot = ttkb.Frame(tab_device)
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

        f_probe = ttkb.Frame(tab_device)
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

        ttkb.Separator(tab_runtime).pack(fill=X, pady=2)
        ttkb.Label(tab_runtime, text="速度优化（风险选项）", font=("bold")).pack(anchor="w")
        f_speed_row = ttkb.Frame(tab_runtime)
        f_speed_row.pack(fill=X, pady=5)
        ttkb.Checkbutton(f_speed_row, text="跳过二次校验", variable=self.var_speed_mode,
                         bootstyle="success-round-toggle").pack(side=LEFT)
        self.create_info_icon(f_speed_row,
                              "跳过对于飞机类型的二次校验；\n风险较低，运行速度提升轻微。").pack(side=LEFT, padx=5)
        ttkb.Checkbutton(f_speed_row, text="跳过地勤分配验证", variable=self.var_skip_staff,
                         bootstyle="success-round-toggle").pack(side=LEFT, padx=(15, 0))
        self.create_info_icon(f_speed_row,
                              "地勤分配后不进行图标验证和颜色验证，直接开始；\n风险中等，可能导致飞机延误；\n仅推荐高峰期且有人在场时打开。").pack(side=LEFT, padx=5)

        ttkb.Separator(tab_runtime).pack(fill=X, pady=10)
        ttkb.Label(tab_runtime, text="不起飞模式", font=("bold")).pack(anchor="w")

        f_no_takeoff_enable = ttkb.Frame(tab_runtime)
        f_no_takeoff_enable.pack(fill=X, pady=5)
        ttkb.Checkbutton(f_no_takeoff_enable, text="启用不起飞模式", variable=self.var_no_takeoff_mode,
                         bootstyle="success-round-toggle").pack(side=LEFT)
        self.create_info_icon(f_no_takeoff_enable,
                              "开启后，脚本会控制筛选状态在停机位：\n"
                              "并且可以自动点击更改机场再重进以清空起飞飞机。\n"
                              "此功能开启后，需要搭配自动塔台。").pack(side=LEFT, padx=5)

        f_logout_enable = ttkb.Frame(tab_runtime)
        f_logout_enable.pack(fill=X, pady=5)
        ttkb.Checkbutton(f_logout_enable, text="启用小退", variable=self.var_no_takeoff_logout_enabled,
                         bootstyle="success-round-toggle").pack(side=LEFT)
        self.create_info_icon(f_logout_enable,
                              "开启后将根据下方随机时长执行小退：\n"
                              "点击左上角菜单->更改机场->开始->等待返回主界面。\n"
                              "填 0-0 表示关闭自动小退。单位：分钟，最大 120 分钟。\n"
                              "该功能可独立开启，不依赖于不起飞模式。").pack(side=LEFT, padx=5)

        f_cancel_filter = ttkb.Frame(tab_runtime)
        f_cancel_filter.pack(fill=X, pady=5)
        ttkb.Checkbutton(f_cancel_filter, text="塔台关闭时筛选全部飞机", variable=self.var_cancel_stand_filter,
                         bootstyle="success-round-toggle").pack(side=LEFT)
        self.create_info_icon(f_cancel_filter,
                              "开启后，塔台关闭时，脚本会强制取消停机位飞机的筛选，处理全部的待处理飞机。" ).pack(side=LEFT, padx=5)

        f_logout = ttkb.Frame(tab_runtime)
        f_logout.pack(fill=X, pady=5)
        ttkb.Label(f_logout, text="小退间隔随机范围(分钟):").pack(side=LEFT)
        e_logout_min = ttkb.Entry(f_logout, width=5)
        e_logout_min.pack(side=LEFT, padx=5)
        e_logout_min.insert(0, str(self.config.get("no_takeoff_logout_min", 30)))
        ttkb.Label(f_logout, text="-").pack(side=LEFT)
        e_logout_max = ttkb.Entry(f_logout, width=5)
        e_logout_max.pack(side=LEFT, padx=5)
        e_logout_max.insert(0, str(self.config.get("no_takeoff_logout_max", 40)))
        self.create_info_icon(f_logout,
                              "启用小退后，每隔该随机时长执行一次小退，清空起飞飞机\n（点击左上角菜单->更改机场->开始->等待返回主界面）。\n填 0-0 表示关闭自动小退。单位：分钟，最大 120 分钟。\n默认 30-40 分钟。").pack(side=LEFT, padx=5)

        ttkb.Separator(tab_runtime).pack(fill=X, pady=10)
        ttkb.Label(tab_runtime, text="防检测设置", font=("bold")).pack(anchor="w")

        f_rnd = ttkb.Frame(tab_runtime);
        f_rnd.pack(fill=X, pady=5)
        # 【颜色统一】随机任务选择 -> 绿色开关
        ttkb.Checkbutton(f_rnd, text="随机任务选择", variable=self.var_random_task,
                         bootstyle="success-round-toggle").pack(side=LEFT)
        self.create_info_icon(f_rnd,
                              "开启后，脚本将在列表前3个任务中随机选择（80%概率），或从下方任务中随机选择（20%概率），以模拟真实操作。").pack(
            side=LEFT, padx=5)

        f_s = ttkb.Frame(tab_runtime);
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

        f_t = ttkb.Frame(tab_runtime);
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

        ttkb.Separator(tab_runtime).pack(fill=X, pady=16)

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
            self.config.pop("filter_switch_min", None)
            self.config.pop("filter_switch_max", None)
            if self.var_no_takeoff_logout_enabled.get():
                try:
                    lo_min = float(e_logout_min.get().strip())
                    lo_max = float(e_logout_max.get().strip())
                    lo_min = max(0, lo_min)
                    lo_max = max(0, min(120, lo_max))
                    if lo_max < lo_min: lo_max = lo_min
                except (ValueError, AttributeError):
                    lo_min, lo_max = 0, 0
            else:
                lo_min, lo_max = 0, 0
            self.config["no_takeoff_logout_min"] = lo_min
            self.config["no_takeoff_logout_max"] = lo_max

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
                changed.append(("小退", "开" if self.config.get("no_takeoff_logout_enabled") else "关"))
            if old_cfg.get("cancel_stand_filter") != self.config.get("cancel_stand_filter"):
                changed.append(("塔台关闭筛选全部飞机", "开" if self.config.get("cancel_stand_filter") else "关"))
            if (old_cfg.get("no_takeoff_logout_min") != self.config.get("no_takeoff_logout_min") or
                    old_cfg.get("no_takeoff_logout_max") != self.config.get("no_takeoff_logout_max")):
                changed.append(("小退间隔随机范围", f"{self.config.get('no_takeoff_logout_min', 30)}-{self.config.get('no_takeoff_logout_max', 40)} 分钟"))

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

        action_row = ttkb.Frame(body)
        action_row.pack(fill=X)
        ttkb.Button(action_row, text="📊 统计图表", bootstyle="info-outline", width=20,
                    command=self._open_stats_chart).pack(pady=(0, 5))
        ttkb.Separator(body).pack(fill=X, pady=10)
        ttkb.Button(body, text="保存设置", bootstyle="success", width=20, command=save).pack(pady=(5, 0))
        win.after(50, lambda: self._center_toplevel_on_parent(win))

    def refresh_devices(self):
        print(">>> 正在扫描设备...")
        self.var_device_status.set("扫描中")
        self.btn_scan.configure(text="扫描中...", state="disabled")
        for btn in [self.btn_main_start, self.btn_mini_start]:
            btn.configure(state="disabled")
        self.update()
        try:
            devs = AdbController.scan_devices(debug=True)
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
        device = self.combo_devices.get()
        if not device: messagebox.showwarning("提示", "请先选择设备"); return
        if self.bot and self.bot.running: return
        self.var_runtime_status.set("准备启动")
        self.save_config()
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
        self.var_runtime_status.set("运行中")

    def stop_bot(self):
        bot = self.bot
        if bot:
            bot.running = False
            bot.stop()
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
        self.sync_all_configs_to_bot()
        val_str = self.var_delay_count.get()
        if val_str == "0":
            print(f">>> [配置] 自动延时塔台: 已关闭")
        else:
            print(f">>> [配置] 自动延时塔台: 已更新为 {val_str} 次")

    def sync_all_configs_to_bot(self, from_advanced_save=False):
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
            self.bot.set_no_takeoff_logout_interval(
                self.config.get("no_takeoff_logout_min", 30), self.config.get("no_takeoff_logout_max", 40))
            self.bot.set_no_takeoff_logout_enabled(self.config.get("no_takeoff_logout_enabled", False))
            self.bot.set_cancel_stand_filter_when_tower_off(self.var_cancel_stand_filter.get())
            self.bot.set_filter_stand_only_when_tower_open(self.var_tower_open_stand_only.get())
            self.bot.set_control_method(self.config.get("control_method", "adb"))
            self.bot.set_screenshot_method(self.config.get("screenshot_method", "nemu_ipc"))
            self.bot.set_mumu_path(self.config.get("mumu_path", ""))
            self.bot.set_active_branch(self.config.get("active_branch", "full"), log_change=not no_log)
            self.bot.set_module_flags(self.config.get("modules", {}), log_change=not no_log)

    def on_bot_config_update(self, key, value):
        if key == "auto_delay_count":
            self.var_delay_count.set(str(value))
        elif key == "vehicle_buy":
            self.var_vehicle_buy.set(bool(value))
        elif key == "mumu_path":
            self.config["mumu_path"] = value
            self.save_config()

    def log_to_queue(self, msg):
        self.log_queue.put(msg)

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