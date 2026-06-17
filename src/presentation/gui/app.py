"""
CustomTkinter GUI — 表现层。

使用 queue.Queue 接收后台线程信号，通过 Tkinter after() 定时轮询，
避免跨线程直接操作 Tkinter 控件。
"""

from __future__ import annotations

import asyncio
import queue
import threading
import tkinter as tk
from typing import Any, Callable, Dict, Optional

# CustomTkinter 导入
try:
    import customtkinter as ctk
    HAS_CTK = True
except ImportError:
    HAS_CTK = False
    import tkinter.ttk as ttk  # 回退

from src.application.config import AppSettings
from src.application.services import BotOrchestrator, BotSignal


class WOAApp:
    """WOA AutoBot 主 GUI 应用。

    架构：
    - 主线程：Tkinter mainloop (GUI)
    - 后台线程：asyncio.run(bot.start()) (Bot 逻辑)
    - 信号通道：queue.Queue (Bot → GUI)
    """

    def __init__(self, settings: Optional[AppSettings] = None):
        self.settings = settings or AppSettings()
        self._signal_queue: queue.Queue = queue.Queue(maxsize=200)
        self._orchestrator: Optional[BotOrchestrator] = None
        self._bot_thread: Optional[threading.Thread] = None
        self._bot_running = False

        # 初始化 GUI
        self._init_gui()

    # ── GUI 初始化 ──

    def _init_gui(self) -> None:
        if HAS_CTK:
            ctk.set_appearance_mode(self.settings.gui_theme)
            ctk.set_default_color_theme(self.settings.gui_color_theme)
            self._root = ctk.CTk()
        else:
            self._root = tk.Tk()
            self._append_log("⚠️ CustomTkinter 未安装，使用 tkinter 回退", "WARNING")

        self._root.title("WOA AutoBot v2.0")
        self._root.geometry(self.settings.gui_window_geometry)
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)

        # macOS 菜单栏兼容
        if hasattr(self._root, 'createcommand'):
            self._root.createcommand('tkAboutDialog', lambda: None)

        self._build_ui()
        self._start_signal_poller()

    def _build_ui(self) -> None:
        """构建 UI 组件。"""
        # ── 顶栏 ──
        top_frame = ctk.CTkFrame(self._root) if HAS_CTK else tk.Frame(self._root)
        top_frame.pack(fill=tk.X, padx=10, pady=5)

        self._btn_start = (ctk.CTkButton if HAS_CTK else tk.Button)(
            top_frame, text="启动 Bot", command=self._toggle_bot,
            width=100, height=32,
        )
        self._btn_start.pack(side=tk.LEFT, padx=5)

        # 紧急停止按钮
        self._btn_emergency = (ctk.CTkButton if HAS_CTK else tk.Button)(
            top_frame, text="⚠ 紧急停止", command=self._emergency_stop,
            width=100, height=32,
            fg_color="#d32f2f" if HAS_CTK else None,
        )
        self._btn_emergency.pack(side=tk.LEFT, padx=5)
        if HAS_CTK:
            self._btn_emergency.configure(state="disabled")

        # ADB 状态指示器
        self._adb_indicator = (ctk.CTkLabel if HAS_CTK else tk.Label)(
            top_frame, text="⚫ ADB", font=("Consolas", 12), width=80,
        )
        self._adb_indicator.pack(side=tk.LEFT, padx=10)

        self._status_label = (ctk.CTkLabel if HAS_CTK else tk.Label)(
            top_frame, text="⚪ 就绪", font=("Microsoft YaHei UI", 13),
        )
        self._status_label.pack(side=tk.LEFT, padx=15)

        # ── 日志区（限制 500 行）──
        log_frame = ctk.CTkFrame(self._root) if HAS_CTK else tk.Frame(self._root)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self._log_text = tk.Text(
            log_frame, wrap=tk.WORD, state=tk.DISABLED,
            font=("Consolas", 10), bg="#1e1e1e", fg="#d4d4d4",
            relief=tk.FLAT, borderwidth=0,
            maxundo=0,  # 禁用 undo 以节省内存
        )
        self._log_text.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        self._log_max_lines = 500

        # ── 底栏 ──
        bottom_frame = ctk.CTkFrame(self._root) if HAS_CTK else tk.Frame(self._root)
        bottom_frame.pack(fill=tk.X, padx=10, pady=5)

        self._stats_label = (ctk.CTkLabel if HAS_CTK else tk.Label)(
            bottom_frame, text="进港: 0 | 离港: 0 | 失败: 0",
            font=("Consolas", 11),
        )
        self._stats_label.pack(side=tk.LEFT, padx=5)

        # 性能标签
        self._perf_label = (ctk.CTkLabel if HAS_CTK else tk.Label)(
            bottom_frame, text="匹配: -- ms",
            font=("Consolas", 10),
        )
        self._perf_label.pack(side=tk.RIGHT, padx=10)

    # ── Bot 控制 ──

    def _toggle_bot(self) -> None:
        """启动/停止 Bot。"""
        if self._bot_running:
            self._stop_bot()
        else:
            self._start_bot()

    def _start_bot(self) -> None:
        """在后台线程启动 Bot（asyncio 事件循环）。"""
        self._btn_start.configure(text="停止 Bot", state="normal")
        if HAS_CTK:
            self._btn_emergency.configure(state="normal")

        self._orchestrator = BotOrchestrator(self.settings, self._signal_queue)

        def _run_bot():
            try:
                asyncio.run(self._orchestrator.start())
            except Exception as e:
                # 将异常通过信号队列发送到 GUI
                try:
                    self._signal_queue.put_nowait(BotSignal(
                        type="error", message=f"Bot 崩溃: {e}", level="ERROR",
                    ))
                except queue.Full:
                    pass

        self._bot_thread = threading.Thread(target=_run_bot, daemon=True)
        self._bot_thread.start()
        self._bot_running = True
        self._status_label.configure(text="🟢 运行中")

    def _emergency_stop(self) -> None:
        """紧急停止：强制终止 asyncio 任务 + ADB 进程。"""
        self._append_log("🛑 紧急停止触发", "ERROR")
        if self._orchestrator:
            self._orchestrator.stop()
        self._bot_running = False
        # 强制杀掉 adb server
        try:
            import subprocess
            subprocess.run(["adb", "kill-server"], capture_output=True, timeout=5,
                          creationflags=0x08000000 if os.name == "nt" else 0)
        except Exception:
            pass
        self._btn_start.configure(text="启动 Bot")
        self._btn_emergency.configure(state="disabled") if HAS_CTK else None
        self._status_label.configure(text="🔴 紧急停止")
        self._adb_indicator.configure(text="⚫ ADB")

    def _stop_bot(self) -> None:
        """正常停止 Bot。"""
        if self._orchestrator:
            self._orchestrator.stop()
        self._bot_running = False
        self._btn_start.configure(text="启动 Bot")
        if HAS_CTK:
            self._btn_emergency.configure(state="disabled")
        self._status_label.configure(text="⚪ 已停止")

        if self._bot_thread and self._bot_thread.is_alive():
            self._bot_thread.join(timeout=3.0)
            if self._bot_thread.is_alive():
                self._append_log("⚠️ Bot 线程未能在 3s 内退出", "WARNING")

    # ── 信号轮询 ──

    def _start_signal_poller(self) -> None:
        """启动 Tkinter after 定时器轮询信号队列。"""
        self._poll_signals()

    def _poll_signals(self) -> None:
        """从信号队列中取出所有待处理信号并更新 UI。"""
        try:
            while True:
                signal: BotSignal = self._signal_queue.get_nowait()
                self._handle_signal(signal)
        except queue.Empty:
            pass
        finally:
            self._root.after(100, self._poll_signals)

    def _handle_signal(self, signal: BotSignal) -> None:
        """处理单个信号，更新对应 UI 控件。"""
        if signal.type == "log":
            self._append_log(signal.message, signal.level)
        elif signal.type == "status":
            self._status_label.configure(text=f"🔵 {signal.message}")
        elif signal.type == "error":
            code = f"[{signal.error_code}] " if signal.error_code else ""
            self._status_label.configure(text=f"🔴 {code}{signal.message}")
            self._append_log(f"❌ {code}{signal.message}", "ERROR")
        elif signal.type == "stats":
            data = signal.data or {}
            adb_ok = data.get("adb_connected", False)
            self._adb_indicator.configure(
                text=f"{'🟢' if adb_ok else '🔴'} ADB"
            )
            self._stats_label.configure(
                text=(f"进港: {data.get('approach', 0)} | "
                      f"离港: {data.get('depart', 0)} | "
                      f"失败: {data.get('consecutive_failures', 0)}")
            )
            bench = data.get("bench_avg_ms", 0)
            self._perf_label.configure(
                text=f"匹配: {bench:.0f} ms" if bench else "匹配: -- ms"
            )
        elif signal.type == "heartbeat":
            self._adb_indicator.configure(text="🟢 ADB")

    def _append_log(self, message: str, level: str = "INFO") -> None:
        """追加日志到文本框（限制最大行数）。"""
        self._log_text.configure(state=tk.NORMAL)
        self._log_text.insert(tk.END, f"{message}\n")
        self._log_text.see(tk.END)
        self._log_text.configure(state=tk.DISABLED)

        # 限制最大行数
        lines = int(self._log_text.index('end-1c').split('.')[0])
        if lines > self._log_max_lines:
            self._log_text.configure(state=tk.NORMAL)
            self._log_text.delete('1.0', f'{lines - self._log_max_lines}.0')
            self._log_text.configure(state=tk.DISABLED)

    # ── 生命周期 ──

    def _on_close(self) -> None:
        """窗口关闭回调。"""
        self._stop_bot()
        self._root.destroy()

    def run(self) -> None:
        """启动 GUI 主循环。"""
        self._root.mainloop()


# ─── 入口函数 ─────────────────────────────────────────────

def main():
    """WOA AutoBot v2.0 入口。"""
    settings = AppSettings()
    app = WOAApp(settings)
    app.run()


if __name__ == "__main__":
    main()
