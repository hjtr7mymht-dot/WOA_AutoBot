# 此模块的连接逻辑参考了 ALAS 项目的设计思路
# Reference: https://github.com/LmeSzinc/AzurLaneAutoScript

import atexit
import ctypes
import socket
import subprocess
import time
import os
import sys
import re
import random
import threading
import shutil

from woa_debug import (
    _woa_debug_enabled, woa_debug_set_runtime_started, _woa_debug_log,
    get_woa_debug_dir, read_image_safe, save_image_safe,
    _woa_debug_save_img, _woa_debug_save_screenshot,
    _woa_debug_save_click_before, woa_debug_save_roi,
)
from nemu_ipc import NemuIpcHelper, _load_dll_safe, NEMU_IPC_DEBUG

# 资助功能完整性守卫标记（由 gui_launcher 在严格模式下联动校验）
WOA_FEATURE_GUARD_TOKEN = "WOA_DONATE_GUARD_V1"

# 用于进程退出时清理残留（含非正常关闭）
_adb_instances = []


def kill_adb_server():
    """终止 adb server，释放对 adb_tools 目录的占用，避免无法删除打包文件夹"""
    adb_path = CURRENT_ADB_PATH if CURRENT_ADB_PATH and os.path.isfile(CURRENT_ADB_PATH) else None
    if not adb_path or adb_path == "adb":
        adb_path = get_bundled_resource_path(os.path.join("adb_tools", "adb.exe"))
    if not os.path.isfile(adb_path):
        return
    try:
        subprocess.run(
            [adb_path, "kill-server"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3,
            creationflags=0x08000000,
        )
    except Exception:
        pass


def close_all_and_kill_server():
    """先关闭所有 AdbController（含 shell、minitouch、DroidCast 子进程），再终止 adb server，避免进程残留"""
    for c in list(_adb_instances):
        try:
            c.close()
        except Exception:
            pass
    kill_adb_server()


def _atexit_cleanup():
    for c in list(_adb_instances):
        try:
            c.close()
        except Exception:
            pass
    # 注意：多实例共用时不要在此 kill-server，否则关闭一个窗口会导致其他脚本全部断连。
    # 用户如需释放 adb.exe 占用，可手动点击 GUI 的彻底退出或由 main_adb 触发。



atexit.register(_atexit_cleanup)

try:
    from emulator_discovery import (
        discover_all_serials_and_ports,
        get_mumu_adb_paths as _discover_mumu_adb,
    )
except ImportError:
    discover_all_serials_and_ports = None
    _discover_mumu_adb = None


def get_bundled_resource_path(relative_path):
    """获取资源路径，兼容 PyInstaller 与 Nuitka"""
    if getattr(sys, 'frozen', False):
        if hasattr(sys, '_MEIPASS'):
            # PyInstaller: 资源在临时解压目录
            base = sys._MEIPASS
        else:
            # Nuitka: 资源在 exe 同目录（--include-data-dir 输出位置）
            base = os.path.dirname(sys.executable)
        return os.path.join(base, relative_path)
    else:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)


def ensure_local_platform_tools():
    """确保 adb_tools 目录存在可用的本地 ADB 运行文件，缺失时从内置 platform-tools 自动补齐。"""
    source_dir = get_bundled_resource_path("platform-tools")
    target_dir = get_bundled_resource_path("adb_tools")
    copied = []
    errors = []

    try:
        os.makedirs(target_dir, exist_ok=True)
    except Exception as exc:
        errors.append(f"创建 adb_tools 目录失败: {exc}")

    if os.path.isdir(source_dir):
        try:
            for name in os.listdir(source_dir):
                src = os.path.join(source_dir, name)
                dst = os.path.join(target_dir, name)
                if not os.path.isfile(src):
                    continue
                if os.path.isfile(dst) and os.path.getsize(dst) > 0:
                    continue
                try:
                    shutil.copy2(src, dst)
                    copied.append(name)
                except Exception as exc:
                    errors.append(f"复制 {name} 失败: {exc}")
        except Exception as exc:
            errors.append(f"遍历 platform-tools 失败: {exc}")
    else:
        errors.append("未找到内置 platform-tools 目录")

    adb_path = os.path.join(target_dir, "adb.exe")
    ready = os.path.isfile(adb_path)
    return {
        "source_dir": source_dir,
        "target_dir": target_dir,
        "copied": copied,
        "adb_path": adb_path if ready else "",
        "ready": ready,
        "errors": errors,
    }


def _get_u2_jar_candidate_dirs():
    """返回 u2.jar 可能存在的目录（兼容开发环境与打包后，参考 ALAS uiautomator2cache）"""
    candidates = []
    if getattr(sys, "frozen", False):
        if hasattr(sys, "_MEIPASS"):
            candidates.append(sys._MEIPASS)
        candidates.append(os.path.dirname(sys.executable))
    candidates.append(os.path.dirname(os.path.abspath(__file__)))
    candidates.append(os.getcwd())
    try:
        import uiautomator2cache  # type: ignore[import-untyped]
        candidates.insert(0, os.path.join(os.path.dirname(uiautomator2cache.__file__), "cache"))
        candidates.insert(0, os.path.dirname(uiautomator2cache.__file__))
    except ImportError:
        pass
    return candidates


def _apply_u2_resource_patch():
    """打补丁：在 core 模块的 with_package_resource 处注入我们的查找逻辑（core 从 utils import 后持有引用，故需 patch core）"""
    try:
        import contextlib
        import pathlib
        u2_core = __import__("uiautomator2.core", fromlist=["with_package_resource"])
        if getattr(u2_core, "_woa_u2_patched", False):
            return
        _orig = getattr(u2_core, "with_package_resource", None)
        if _orig is None:
            return
        candidate_dirs = _get_u2_jar_candidate_dirs()

        @contextlib.contextmanager
        def _patched(filename):
            for base in candidate_dirs:
                p = pathlib.Path(base) / filename.replace("/", os.sep)
                if p.is_file():
                    yield p
                    return
            yield from _orig(filename)

        u2_core.with_package_resource = _patched
        u2_core._woa_u2_patched = True
    except Exception:
        pass


# 打包环境下提前打补丁，确保 u2 解压即用，无需用户额外配置
if getattr(sys, "frozen", False):
    try:
        _apply_u2_resource_patch()
    except Exception:
        pass


def find_adb_executable():
    """自动搜索 adb.exe"""
    internal_adb = get_bundled_resource_path(os.path.join("adb_tools", "adb.exe"))
    if os.path.exists(internal_adb):
        return internal_adb
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        external_adb = os.path.join(exe_dir, "adb_tools", "adb.exe")
        if os.path.exists(external_adb):
            return external_adb
    resolved = shutil.which("adb")
    if resolved:
        return resolved
    return "adb"


DEFAULT_ADB_PATH = find_adb_executable()
CURRENT_ADB_PATH = DEFAULT_ADB_PATH


def set_custom_adb_path(path):
    global CURRENT_ADB_PATH
    if path and os.path.exists(path):
        if CURRENT_ADB_PATH != path:
            CURRENT_ADB_PATH = path
            print(f">>> [系统] ADB 路径已切换为: {CURRENT_ADB_PATH}")
    else:
        if CURRENT_ADB_PATH != DEFAULT_ADB_PATH:
            CURRENT_ADB_PATH = DEFAULT_ADB_PATH
            print(f">>> [系统] ADB 路径重置为默认")


class AdbController:
    """支持多种触控方案: adb, uiautomator2"""
    VALID_CONTROL_METHODS = ("adb", "uiautomator2")
    LOGICAL_WIDTH = 1600
    LOGICAL_HEIGHT = 900

    def __init__(self, target_device=None, use_minitouch=False, screenshot_method="adb", control_method=None, instance_id=1):
        self.instance_id = instance_id
        self._minitouch_base_port = 17392 + (instance_id - 1)
        self._droidcast_base_port = 53516 + (instance_id - 1)
        self.device_serial = target_device
        self.adb_path = CURRENT_ADB_PATH or "adb"
        if control_method is not None:
            m = (control_method or "adb").lower()
            self.control_method = m if m in self.VALID_CONTROL_METHODS else "adb"
        else:
            self.control_method = "adb"
        self.use_minitouch = (self.control_method == "minitouch")
        self.screenshot_method = (screenshot_method or "adb").lower()
        if self.screenshot_method not in ("adb", "nemu_ipc", "uiautomator2", "droidcast_raw"):
            self.screenshot_method = "adb"
        self._desired_screenshot_method = self.screenshot_method
        self._desired_control_method = self.control_method
        self._screenshot_consec_fails = 0
        self._control_consec_fails = 0
        self._last_screenshot_recovery_time = 0.0
        self._last_control_recovery_time = 0.0
        self._adb_screenshot_consec_total_fails = 0
        self.think_min = 0.0
        self.think_max = 0.0
        self.default_click_jitter = 3
        self.default_swipe_jitter = 4
        _adb_instances.append(self)

        # 【核心升级】持久化 Shell 进程
        self.shell_process = None
        self.shell_lock = threading.RLock()
        self._closed = False

        # minitouch（本脚本分辨率 1600x900，参考 ALAS 支持旋转）
        self._minitouch_client = None
        self._minitouch_port = 0
        self._minitouch_ready = False
        self._minitouch_lock = threading.Lock()
        self._minitouch_proc = None
        self._minitouch_max_x = 1600  # 从 ^ 行解析
        self._minitouch_max_y = 900
        self._minitouch_orientation = 0  # 0=正常 1=右 2=上 3=左（参考 ALAS）
        self._minitouch_screen_w = 1600
        self._minitouch_screen_h = 900
        self._raw_screen_w = self.LOGICAL_WIDTH
        self._raw_screen_h = self.LOGICAL_HEIGHT

        # nemu_ipc 截图（MuMu12 专用）
        self._nemu_ipc = NemuIpcHelper(self)
        self.mumu_path = ""  # 手动指定的 MuMu 安装路径，留空则自动检测
        self._nemu_folder_callback = None  # 自动识别成功时回调 (folder) -> None

        # uiautomator2（可选，需 pip install uiautomator2）
        self._u2_device = None
        self._u2_fallback_logged = False
        self._u2_screenshot_fallback_logged = False

        # DroidCast_raw（参考 ALAS，需 assets/DroidCast_raw.apk）
        self._droidcast_port = 0
        self._droidcast_session = None
        self._droidcast_proc = None
        self._droidcast_fallback_logged = False

        # 初始化连接
        if self.device_serial:
            self._start_persistent_shell()

    def set_thinking_strategy(self, min_s, max_s):
        self.think_min = float(min_s)
        self.think_max = float(max_s)

    def set_control_method(self, method, _is_fallback=False):
        m = (method or "adb").lower()
        if m in self.VALID_CONTROL_METHODS:
            self.control_method = m
            self.use_minitouch = (m == "minitouch")
            if not _is_fallback:
                self._desired_control_method = m
                self._control_consec_fails = 0

    def _u2_ensure_assets(self, u2_module):
        """确保 u2.jar 可被 uiautomator2 找到，并打补丁（兼容打包后）"""
        _apply_u2_resource_patch()
        try:
            import shutil
            pkg_dir = os.path.dirname(os.path.abspath(u2_module.__file__))
            jar_in_pkg = os.path.join(pkg_dir, "assets", "u2.jar")
            if not os.path.isfile(jar_in_pkg):
                return
            for base in _get_u2_jar_candidate_dirs():
                assets_dir = os.path.join(base, "assets")
                jar_dst = os.path.join(assets_dir, "u2.jar")
                if os.path.isfile(jar_dst):
                    return
                try:
                    os.makedirs(assets_dir, exist_ok=True)
                    shutil.copy2(jar_in_pkg, jar_dst)
                    print(">>> [uiautomator2] 已复制 u2.jar 到 assets/")
                    return
                except (OSError, IOError):
                    continue
        except Exception:
            pass

    def set_screenshot_method(self, method, _is_fallback=False):
        m = (method or "adb").lower()
        if m in ("adb", "nemu_ipc", "uiautomator2", "droidcast_raw"):
            self.screenshot_method = m
            if not _is_fallback:
                self._desired_screenshot_method = m
                self._screenshot_consec_fails = 0

    def set_mumu_path(self, path):
        self.mumu_path = (path or "").strip()

    def ensure_methods_usable(self):
        """校验截图/触控方案可用性，不可用时自动回退到 ADB。"""
        repaired = False

        # 先校验截图方案，避免后续流程在首帧就失败。
        img = self.get_screenshot()
        if img is None:
            if self.screenshot_method != "adb":
                print(f">>> [模式] ⚠️ 截图方案 {self.screenshot_method} 不可用，自动回退到 ADB")
                self.set_screenshot_method("adb", _is_fallback=True)
                repaired = True
            img = self.get_screenshot(force_method="adb")
        shot_ok = img is not None

        ctrl_ok = True
        if self.control_method == "minitouch":
            try:
                ctrl_ok = bool(self._minitouch_init())
            except Exception:
                ctrl_ok = False
        elif self.control_method == "uiautomator2":
            try:
                ctrl_ok = bool(self._u2_init())
            except Exception:
                ctrl_ok = False

        if not ctrl_ok:
            if self.control_method != "adb":
                print(f">>> [模式] ⚠️ 触控方案 {self.control_method} 不可用，自动回退到 ADB")
                self.set_control_method("adb", _is_fallback=True)
                repaired = True
            ctrl_ok = True

        return {
            "screenshot_ok": shot_ok,
            "control_ok": ctrl_ok,
            "repaired": repaired,
            "control_method": self.control_method,
            "screenshot_method": self.screenshot_method,
        }

    def set_nemu_folder_callback(self, cb):
        """自动识别到 MuMu 路径时调用 cb(folder)，用于回填到配置/界面"""
        self._nemu_folder_callback = cb

    def _u2_init(self):
        """初始化 uiautomator2 连接（参考 ALAS 对 u2.jar 路径的兼容处理）"""
        return self._u2_init_impl(for_control=True)

    def _u2_init_screenshot(self):
        """初始化 uiautomator2 连接（仅用于截图，不依赖 control_method）"""
        return self._u2_init_impl(for_control=False)

    def _u2_init_impl(self, for_control=True, allow_screenshot_fallback=False):
        """初始化 u2 设备：参考 ALAS，模拟器使用 connect_usb，连接失败时自动安装 atx-agent"""
        if self._u2_device is not None:
            return True
        if self._closed or not self.device_serial:
            return False
        if for_control and self.control_method != "uiautomator2":
            return False
        if not for_control and self.screenshot_method != "uiautomator2" and not allow_screenshot_fallback:
            return False
        try:
            # lxml 是 u2 的依赖但本项目不使用 XML 解析功能，Nuitka 打包可能漏掉
            try:
                import lxml  # noqa: F401
            except ImportError:
                import types
                _mock_lxml = types.ModuleType("lxml")
                _mock_etree = types.ModuleType("lxml.etree")
                _mock_lxml.etree = _mock_etree
                import sys
                sys.modules["lxml"] = _mock_lxml
                sys.modules["lxml.etree"] = _mock_etree
            import uiautomator2 as u2  # type: ignore[import-untyped]
            self._u2_ensure_assets(u2)
            # 参考 ALAS：模拟器使用 connect_usb（走 ADB 通道），物理设备使用 connect
            serial = self.device_serial
            is_emulator = serial.startswith("127.0.0.1:") or serial.startswith("emulator-")
            for attempt in range(2):
                try:
                    if is_emulator:
                        self._u2_device = u2.connect_usb(serial)
                    else:
                        self._u2_device = u2.connect(serial)
                    # 保持长连接（参考 ALAS：7天超时）
                    if hasattr(self._u2_device, 'set_new_command_timeout'):
                        self._u2_device.set_new_command_timeout(604800)
                    msg = "触控将使用 atx-agent" if for_control else "截图将使用 atx-agent"
                    print(f">>> [uiautomator2] 已启用，{msg}")
                    return True
                except Exception as e:
                    if attempt == 0:
                        # 首次失败：尝试自动安装 atx-agent（参考 ALAS install_uiautomator2）
                        try:
                            print(f">>> [uiautomator2] 连接失败({e})，尝试自动安装 atx-agent...")
                            import logging
                            init = u2.init.Initer(self._get_adb_client_for_u2(), loglevel=logging.WARNING)
                            # MuMu X 可能没有 ro.product.cpu.abi，从 abilist 取（参考 ALAS）
                            if hasattr(init, 'abi') and hasattr(init, 'abis'):
                                if init.abi not in ['x86_64', 'x86', 'arm64-v8a', 'armeabi-v7a', 'armeabi']:
                                    if init.abis:
                                        init.abi = init.abis[0]
                            if hasattr(init, 'set_atx_agent_addr'):
                                init.set_atx_agent_addr('127.0.0.1:7912')
                            try:
                                init.install()
                            except ConnectionError:
                                # GitHub 下载失败，尝试国内镜像
                                if hasattr(u2.init, 'GITHUB_BASEURL'):
                                    u2.init.GITHUB_BASEURL = 'http://tool.appetizer.io/openatx'
                                    init.install()
                            print(">>> [uiautomator2] atx-agent 安装完成，重试连接...")
                        except Exception as install_err:
                            print(f">>> [uiautomator2] atx-agent 安装失败: {install_err}")
                            break
                    else:
                        # 第二次仍然失败
                        flag = self._u2_fallback_logged if for_control else self._u2_screenshot_fallback_logged
                        if not flag:
                            if for_control:
                                self._u2_fallback_logged = True
                            else:
                                self._u2_screenshot_fallback_logged = True
                            print(f">>> [uiautomator2] 连接失败: {e}，回退到 ADB")
            return False
        except ImportError as e:
            flag = self._u2_fallback_logged if for_control else self._u2_screenshot_fallback_logged
            if not flag:
                if for_control:
                    self._u2_fallback_logged = True
                else:
                    self._u2_screenshot_fallback_logged = True
                # 打印具体缺少的模块名
                print(f">>> [uiautomator2] 未安装({e})，回退到 ADB")
            return False
        except Exception as e:
            flag = self._u2_fallback_logged if for_control else self._u2_screenshot_fallback_logged
            if not flag:
                if for_control:
                    self._u2_fallback_logged = True
                else:
                    self._u2_screenshot_fallback_logged = True
                print(f">>> [uiautomator2] 初始化异常: {e}，回退到 ADB")
            return False

    def _get_adb_client_for_u2(self):
        """获取 adbutils 的 AdbDevice 对象，供 u2.init.Initer 使用"""
        try:
            import adbutils
            adb_client = adbutils.AdbClient(host="127.0.0.1", port=5037)
            return adb_client.device(self.device_serial)
        except Exception:
            # 回退：直接传 serial 字符串，部分 u2 版本支持
            return self.device_serial

    def _do_think(self):
        if self.think_max > 0:
            mu = (self.think_min + self.think_max) / 2
            sigma = (self.think_max - self.think_min) / 4
            wait = random.gauss(mu, sigma)
            wait = max(self.think_min, min(self.think_max, wait))
            time.sleep(wait)

    def _start_persistent_shell(self):
        """启动持久化 ADB Shell 会话"""
        if not self.device_serial or self._closed:
            return

        # 防止频繁重建：冷却 3 秒
        now = time.time()
        last = getattr(self, '_last_shell_start_time', 0)
        if now - last < 3.0:
            return
        self._last_shell_start_time = now

        try:
            with self.shell_lock:
                if self.shell_process and self.shell_process.poll() is None:
                    return

                if self.shell_process:
                    try:
                        self.shell_process.terminate()
                        self.shell_process.wait(timeout=0.5)
                    except Exception:
                        try:
                            self.shell_process.kill()
                        except Exception:
                            pass
                    self.shell_process = None

                adb = self.adb_path
                cmd = [adb, "-s", self.device_serial, "shell"]
                self.shell_process = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=0x08000000
                )
                print(f">>> [底层] ADB Shell 长连接已建立: {self.device_serial}")
        except Exception as e:
            if self.shell_process:
                try:
                    self.shell_process.kill()
                except Exception:
                    pass
                self.shell_process = None
            print(f"❌ [底层] 建立 Shell 失败: {e}")

    def _adb_forward(self, local, remote):
        """adb forward local remote"""
        r = self.run_cmd(["forward", local, remote], timeout=5)
        return r and r.returncode == 0

    def _minitouch_init(self):
        """初始化 minitouch：仅 x86 设备、推送二进制、启动服务、建立转发与 socket 连接"""
        with self._minitouch_lock:
            if self._minitouch_ready and self._minitouch_client:
                return True
            if self._closed or not self.device_serial or not self.use_minitouch:
                return False
        tout = 15 if "127.0.0.1" not in (self.device_serial or "") else 8
        abi_r = self.run_cmd(["shell", "getprop", "ro.product.cpu.abi"], timeout=tout)
        abilist_r = self.run_cmd(["shell", "getprop", "ro.product.cpu.abilist"], timeout=tout)
        abi = ""
        abilist = []
        if abi_r and abi_r.stdout:
            abi = (abi_r.stdout.decode("utf-8", errors="ignore") or "").strip().lower().replace("\r", "")
        if abilist_r and abilist_r.stdout:
            abilist = [item.strip().lower() for item in abilist_r.stdout.decode("utf-8", errors="ignore").split(",") if item.strip()]
        if abi and abi not in abilist:
            abilist.insert(0, abi)
        # ABI -> minitouch 目录映射（须先匹配更具体的，避免 x86 误匹配 x86_64）
        _abi_map = [
            ("x86_64", ("minitouch-69336c8f34", "minitouch-1e3ccbf4fa", "minitouch_x86")),
            ("arm64-v8a", ("minitouch-f7a806902f", "minitouch-4575799dba")),
            ("x86", ("minitouch-1e3ccbf4fa", "minitouch_x86")),
            ("armeabi-v7a", ("minitouch-4575799dba",)),
        ]
        def _resolve_minitouch(name):
            # minitouch-xxx 目录下是 minitouch 文件；minitouch_x86 是根目录下的文件
            p = get_bundled_resource_path(os.path.join("adb_tools", name, "minitouch"))
            if os.path.isfile(p):
                return p
            p = get_bundled_resource_path(os.path.join("adb_tools", name))
            return p if os.path.isfile(p) else None

        candidate_names = []
        for abi_name in abilist or [abi]:
            for key, candidates in _abi_map:
                if key and key in abi_name:
                    for name in candidates:
                        if name not in candidate_names:
                            candidate_names.append(name)
        for fallback_name in ("minitouch-1e3ccbf4fa", "minitouch_x86", "minitouch-4575799dba", "minitouch-f7a806902f"):
            if fallback_name not in candidate_names:
                candidate_names.append(fallback_name)

        candidate_paths = []
        for name in candidate_names:
            resolved = _resolve_minitouch(name)
            if resolved and os.path.isfile(resolved):
                candidate_paths.append((name, resolved))

        if not candidate_paths:
            print(f"⚠️ [minitouch] 未找到兼容 ABI={abi!r}, abilist={abilist!r} 的 minitouch，回退到 ADB")
            self.use_minitouch = False
            return False

        is_net = "127.0.0.1" not in (self.device_serial or "")
        port = self._minitouch_base_port
        adb_path = get_bundled_resource_path(os.path.join("adb_tools", "adb.exe"))
        if not os.path.isfile(adb_path):
            adb_path = "adb"

        socket_targets = ("localabstract:minitouch", "localabstract:minitouchagent", "localabstract:mini_touch")
        last_error = "未知错误"

        for bin_name, local_path in candidate_paths:
            print(f">>> [minitouch] 设备 ABI={abi!r}, abilist={abilist!r}，尝试二进制: {bin_name}")
            r1 = self.run_cmd(["push", local_path, "/data/local/tmp/minitouch"], timeout=tout)
            if not r1 or r1.returncode != 0:
                err = (r1.stderr.decode("utf-8", errors="ignore") if r1 and r1.stderr else "未知")[:200]
                last_error = f"推送失败: {err}"
                print(f"⚠️ [minitouch] {bin_name} 推送失败: {err}")
                continue
            self.run_cmd(["shell", "chmod", "755", "/data/local/tmp/minitouch"], timeout=tout)
            self.run_cmd(["shell", "pkill", "-f", "minitouch"], timeout=tout)
            time.sleep(0.5)

            proc = None
            proc_exit_msg = ""
            try:
                proc = subprocess.Popen(
                    [adb_path, "-s", self.device_serial, "shell", "/data/local/tmp/minitouch"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    creationflags=0x08000000 if sys.platform == "win32" else 0,
                )
                time.sleep(2.0 if is_net else 1.0)
                if proc.poll() is not None:
                    out, err = proc.communicate(timeout=1)
                    proc_exit_msg = ((out or b"") + b"\n" + (err or b"")).decode("utf-8", errors="ignore").strip()
                    proc = None
            except Exception as e:
                proc_exit_msg = str(e)
                proc = None

            self.run_cmd(["forward", "--remove", f"tcp:{port}"], timeout=5)
            client = None
            err_msg = proc_exit_msg or "无输出"
            target_used = None

            for target in socket_targets:
                if not self._adb_forward(f"tcp:{port}", target):
                    continue
                retry_count = 4
                for attempt in range(retry_count):
                    s = None
                    try:
                        print(f">>> [minitouch] 连接 127.0.0.1:{port} via {target} (尝试 {attempt + 1}/{retry_count})...")
                        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        s.settimeout(3)
                        s.connect(("127.0.0.1", port))
                        s.settimeout(2)
                        out = s.makefile(mode="rb")
                        try:
                            first = out.readline().decode("utf-8", errors="replace").strip().replace("\r", "")
                            if first and first[:1] in ("v", "^", "$"):
                                max_x, max_y = 1600, 900
                                line2 = out.readline().decode("utf-8", errors="replace").strip().replace("\r", "")
                                if line2.startswith("^"):
                                    parts = line2.split()
                                    if len(parts) >= 5:
                                        max_x, max_y = int(parts[2]), int(parts[3])
                                out.readline()
                                self._minitouch_max_x, self._minitouch_max_y = max_x, max_y
                                self._minitouch_orientation = self._get_minitouch_orientation()
                                s.settimeout(5.0)
                                client = s
                                target_used = target
                            else:
                                err_msg = f"首行无效: {first[:60]!r}" if first else "无输出"
                        finally:
                            out.close()
                        if client is not None:
                            break
                        s.close()
                    except (socket.timeout, socket.error, OSError) as e:
                        err_msg = str(e)
                        if s:
                            try:
                                s.close()
                            except Exception:
                                pass
                    if attempt < retry_count - 1:
                        time.sleep(1.0)
                if client is not None:
                    break

            if client is not None:
                self._minitouch_proc = proc
                try:
                    with self._minitouch_lock:
                        self._minitouch_client = client
                        self._minitouch_port = self._minitouch_base_port
                        self._minitouch_ready = True
                    _o = self._minitouch_orientation
                    _ominfo = f", orientation={_o}" if _o else ""
                    print(f">>> [minitouch] 已启用 ({bin_name}, {target_used}, 1600x900{_ominfo})，触控将使用 socket 加速")
                    return True
                except Exception as e:
                    last_error = f"连接收尾失败: {e}"
                    try:
                        client.close()
                    except Exception:
                        pass
            else:
                if proc:
                    try:
                        proc.terminate()
                    except Exception:
                        pass
                last_error = f"{bin_name} 握手失败: {err_msg}"
                print(f">>> [minitouch] {last_error}")

        print(f"⚠️ [minitouch] 初始化失败，回退到 ADB: {last_error}")
        self.use_minitouch = False
        raise RuntimeError(f"minitouch handshake failed: {last_error}")

    def _get_minitouch_orientation(self):
        """获取设备方向 0/1/2/3（参考 ALAS dumpsys display）"""
        try:
            r = self.run_cmd(["shell", "dumpsys", "display"], timeout=8)
            if r and r.stdout:
                out = r.stdout.decode("utf-8", errors="ignore")
                # DisplayViewport{...orientation=N,...} 或 mCurrentOrientation=N
                m = re.search(r"orientation=(\d+)", out)
                if not m:
                    m = re.search(r"mCurrentOrientation=(\d+)", out)
                if m:
                    o = int(m.group(1))
                    if o in (0, 1, 2, 3):
                        return o
        except Exception:
            pass
        return 0

    def _minitouch_scale(self, x, y):
        """将屏幕坐标映射到 minitouch 设备坐标，含旋转（参考 ALAS convert）"""
        sw, sh = self._minitouch_screen_w, self._minitouch_screen_h
        mx, my = self._minitouch_max_x, self._minitouch_max_y
        o = self._minitouch_orientation
        if o == 0:
            pass
        elif o == 1:
            x, y = sh - y, x
            mx, my = my, mx
        elif o == 2:
            x, y = sw - x, sh - y
        elif o == 3:
            x, y = y, sw - x
            mx, my = my, mx
        return int(x * mx / sw), int(y * my / sh)

    def _adb_click_fallback(self, xi, yi):
        """ADB input tap 兜底"""
        if not self._write_shell_cmd(f"input tap {xi} {yi}"):
            self.run_cmd(["shell", "input", "tap", str(xi), str(yi)])

    def _logical_to_device_point(self, x, y):
        rw = max(1, int(getattr(self, "_raw_screen_w", self.LOGICAL_WIDTH)))
        rh = max(1, int(getattr(self, "_raw_screen_h", self.LOGICAL_HEIGHT)))
        dx = int(round(float(x) * rw / self.LOGICAL_WIDTH))
        dy = int(round(float(y) * rh / self.LOGICAL_HEIGHT))
        dx = max(0, min(rw - 1, dx))
        dy = max(0, min(rh - 1, dy))
        return dx, dy

    def _apply_coordinate_jitter(self, x, y, jitter):
        if jitter <= 0:
            return x, y
        return (
            x + random.uniform(-jitter, jitter),
            y + random.uniform(-jitter, jitter),
        )

    def _normalize_to_logical_resolution(self, img):
        import cv2
        if img is None:
            return None
        h, w = img.shape[:2]
        self._raw_screen_w = int(w)
        self._raw_screen_h = int(h)
        if w == self.LOGICAL_WIDTH and h == self.LOGICAL_HEIGHT:
            return img
        return cv2.resize(img, (self.LOGICAL_WIDTH, self.LOGICAL_HEIGHT), interpolation=cv2.INTER_AREA)

    def get_resolution_info(self):
        return {
            "logical": (self.LOGICAL_WIDTH, self.LOGICAL_HEIGHT),
            "raw": (int(getattr(self, "_raw_screen_w", self.LOGICAL_WIDTH)),
                    int(getattr(self, "_raw_screen_h", self.LOGICAL_HEIGHT))),
        }

    def _minitouch_send(self, text):
        with self._minitouch_lock:
            if not self._minitouch_client:
                return False
            try:
                self._minitouch_client.sendall(text.encode("utf-8"))
                time.sleep(0.012)
                return True
            except (socket.error, OSError, BrokenPipeError):
                self._minitouch_ready = False
                try:
                    self._minitouch_client.close()
                except Exception:
                    pass
                self._minitouch_client = None
                return False
            except Exception:
                self._minitouch_ready = False
                self._minitouch_client = None
                return False

    def close(self):
        """关闭 Shell 长连接并终止子进程，避免进程残留导致文件夹无法删除"""
        try:
            _adb_instances.remove(self)
        except ValueError:
            pass
        self._closed = True
        with self._minitouch_lock:
            if self._minitouch_client:
                try:
                    self._minitouch_client.close()
                except Exception:
                    pass
                self._minitouch_client = None
                self._minitouch_ready = False
        if self._minitouch_proc:
            try:
                self._minitouch_proc.terminate()
                self._minitouch_proc.wait(timeout=0.5)
            except Exception:
                try:
                    self._minitouch_proc.kill()
                except Exception:
                    pass
            self._minitouch_proc = None
        try:
            self.run_cmd(["forward", "--remove", f"tcp:{self._minitouch_base_port}"], timeout=1)
        except Exception:
            pass
        self._u2_device = None
        if getattr(self, "_droidcast_proc", None):
            try:
                self._droidcast_proc.terminate()
                self._droidcast_proc.wait(timeout=0.5)
            except Exception:
                try:
                    self._droidcast_proc.kill()
                except Exception:
                    pass
            self._droidcast_proc = None
        self._droidcast_session = None
        self._droidcast_port = 0
        try:
            self.run_cmd(["forward", "--remove", f"tcp:{self._droidcast_base_port}"], timeout=1)
        except Exception:
            pass
        if self._nemu_ipc:
            try:
                self._nemu_ipc.close()
            except Exception:
                pass
        acquired = self.shell_lock.acquire(timeout=1.0)
        try:
            if not self.shell_process:
                return
            try:
                if self.shell_process.poll() is None:
                    try:
                        if self.shell_process.stdin and not self.shell_process.stdin.closed:
                            self.shell_process.stdin.close()
                    except (OSError, BrokenPipeError):
                        pass
                    self.shell_process.terminate()
                    try:
                        self.shell_process.wait(timeout=0.5)
                    except subprocess.TimeoutExpired:
                        self.shell_process.kill()
                        try:
                            self.shell_process.wait(timeout=0.5)
                        except Exception:
                            pass
            except Exception:
                pass
            finally:
                self.shell_process = None
        finally:
            if acquired:
                self.shell_lock.release()

    def _write_shell_cmd(self, cmd_str):
        """通过长连接快速写入命令"""
        with self.shell_lock:
            if not self.shell_process or self.shell_process.poll() is not None:
                self._start_persistent_shell()

            if self.shell_process:
                try:
                    # 必须加 \n 模拟回车
                    cmd_bytes = (cmd_str + "\n").encode('utf-8')
                    self.shell_process.stdin.write(cmd_bytes)
                    self.shell_process.stdin.flush()
                    return True
                except (BrokenPipeError, OSError):
                    # 管道断裂，尝试底层 ADB 重连后再重启 shell
                    print("⚠️ [底层] Shell 管道断裂，尝试重连...")
                    self.shell_process = None
                    time.sleep(0.5)
                    self.connect()
                    time.sleep(0.3)
                    self._start_persistent_shell()
                    try:
                        if self.shell_process and self.shell_process.stdin:
                            self.shell_process.stdin.write((cmd_str + "\n").encode('utf-8'))
                            self.shell_process.stdin.flush()
                            return True
                        return False
                    except Exception:
                        return False
            return False

    def run_cmd(self, args, timeout=15):
        """普通一次性命令 (用于非交互式指令，如 pull/push/connect)"""
        cmd_list = [self.adb_path]
        if self.device_serial:
            cmd_list.extend(["-s", self.device_serial])

        if isinstance(args, list):
            cmd_list.extend([str(a) for a in args])
        elif isinstance(args, str):
            cmd_list.extend(args.split())

        try:
            result = subprocess.run(
                cmd_list,
                shell=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
                creationflags=0x08000000
            )
            return result
        except subprocess.TimeoutExpired:
            print(f"❌ [ADB] 命令超时: {cmd_list[:4]}...")
            return None
        except Exception as e:
            print(f"❌ [ADB错误] {e}")
            return None

    @staticmethod
    def _find_mumu_adb():
        """尝试从常见路径及 ALAS 风格发现找到 MuMu 自带的 adb"""
        if _discover_mumu_adb:
            for p in _discover_mumu_adb():
                if p and os.path.isfile(p):
                    return p
        candidates = [
            os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), "Netease", "MuMu Player 12", "nx_main", "adb.exe"),
            os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), "Netease", "MuMu", "nx_main", "adb.exe"),
            os.path.join("D:", "Program Files", "Netease", "MuMu", "nx_main", "adb.exe"),
            os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), "Netease", "MuMu Player 6", "MuMu", "adb.exe"),
            os.path.join(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"), "Netease", "MuMu Player 12", "nx_main", "adb.exe"),
        ]
        for p in candidates:
            if p and os.path.isfile(p):
                return p
        for drive in ["C", "D", "E", "F"]:
            for base in [rf"{drive}:\Program Files\Netease", rf"{drive}:\Program Files (x86)\Netease"]:
                if not os.path.isdir(base):
                    continue
                try:
                    for name in os.listdir(base):
                        if "MuMu" in name or "MuMuPlayer" in name:
                            for sub in ["nx_main", "MuMu"]:
                                p = os.path.join(base, name, sub, "adb.exe")
                                if os.path.isfile(p):
                                    return p
                except Exception:
                    pass
        return None

    @staticmethod
    def _get_mumu_ports_from_vms():
        """从 MuMu vms 及注册表获取 ADB 端口（ALAS 风格 + 原有逻辑）"""
        if discover_all_serials_and_ports:
            _, ports = discover_all_serials_and_ports()
            if ports:
                return ports[:12]
        ports = []
        for base in [os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), "Netease"),
                      os.path.join(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"), "Netease")]:
            vms_dir = os.path.join(base, "vms") if os.path.isdir(base) else None
            if not vms_dir or not os.path.isdir(vms_dir):
                continue
            try:
                for name in os.listdir(vms_dir):
                    if "MuMuPlayer" in name or "myandrovm" in name:
                        folder = os.path.join(vms_dir, name)
                        if not os.path.isdir(folder):
                            continue
                        for fname in os.listdir(folder):
                            if fname.endswith((".ini", ".cfg", ".vmx", ".nvram", ".nemu")) or "config" in fname.lower():
                                path = os.path.join(folder, fname)
                                if os.path.isfile(path):
                                    try:
                                        with open(path, "r", encoding="utf-8", errors="ignore") as f:
                                            content = f.read()
                                        for m in re.finditer(r"adb[_-]?port[\s\":=]*(\d+)", content, re.I):
                                            p = int(m.group(1))
                                            if 5000 < p < 70000 and p not in ports:
                                                ports.append(p)
                                        for m in re.finditer(r"hostport=\"(\d+)\"", content, re.I):
                                            p = int(m.group(1))
                                            if 5000 < p < 70000 and p not in ports:
                                                ports.append(p)
                                        for m in re.finditer(r"(\d{4,5})", content):
                                            p = int(m.group(1))
                                            if p in (16384, 16385, 16416, 16448, 5555, 5557, 5559) and p not in ports:
                                                ports.append(p)
                                    except Exception:
                                        pass
            except Exception:
                pass
        return ports[:12]

    @staticmethod
    def scan_devices(debug=False):
        """扫描所有可用模拟器（MuMu/雷电/BlueStacks 等），列出供用户选择"""
        debug = debug or _woa_debug_enabled()
        creationflags = 0x08000000
        _woa_debug_log("scan_devices 开始")
        # 优先使用自带 adb_tools，以便同时连接 MuMu、雷电等不同模拟器
        bundled = get_bundled_resource_path(os.path.join("adb_tools", "adb.exe"))
        adb_path = CURRENT_ADB_PATH or "adb"
        if os.path.isfile(bundled):
            scan_adb = bundled
            if debug:
                print(f">>> [扫描调试] 使用自带 ADB 以识别多款模拟器: {scan_adb}")
        elif adb_path != "adb" and os.path.isfile(adb_path):
            scan_adb = adb_path
        else:
            resolved = shutil.which("adb")
            if resolved:
                scan_adb = resolved
                if debug:
                    print(f">>> [扫描调试] 使用 PATH 中的 ADB: {scan_adb}")
            else:
                mumu_adb = AdbController._find_mumu_adb()
                scan_adb = mumu_adb if (mumu_adb and os.path.isfile(mumu_adb)) else "adb"
                if debug and scan_adb != "adb":
                    print(f">>> [扫描调试] 使用 MuMu ADB: {scan_adb}")
        if scan_adb == "adb":
            if debug:
                print(">>> [扫描调试] 未找到 adb 可执行文件，请安装 Android SDK Platform Tools 或在设置中指定 adb_path")
            return []
        if not os.path.isfile(scan_adb):
            if debug:
                print(f">>> [扫描调试] ADB 路径无效: {scan_adb}")
            return []

        # 汇总所有可能端口（MuMu/雷电/BlueStacks 等）
        if discover_all_serials_and_ports:
            _, all_ports = discover_all_serials_and_ports()
            all_ports = list(dict.fromkeys(all_ports))
        else:
            vms_ports = AdbController._get_mumu_ports_from_vms()
            all_ports = list(dict.fromkeys(
                vms_ports + [5555, 5557, 5559, 5561, 16384, 16385, 16416, 16448, 7555,
                             5554, 5556, 62001, 62025, 16480, 16512, 16544, 16576]
            ))
        if debug:
            print(f">>> [扫描调试] 待连接端口数: {len(all_ports)}")

        def _devices_list():
            try:
                r = subprocess.run([scan_adb, "devices"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   timeout=8, creationflags=creationflags)
                out = (r.stdout or b"").decode('utf-8', errors='ignore')
                err = (r.stderr or b"").decode('utf-8', errors='ignore')
                if debug and err.strip():
                    print(f">>> [扫描调试] adb devices stderr: {err.strip()[:300]}")
                devices = []
                for line in out.strip().split('\n'):
                    line = line.strip()
                    if not line or "List of devices" in line:
                        continue
                    parts = line.split()
                    if len(parts) >= 2 and parts[1] == 'device':
                        devices.append(parts[0])
                return devices
            except Exception as e:
                if debug:
                    print(f">>> [扫描调试] adb devices 异常: {e}")
                return []

        # 先尝试不重启 server 直接获取已连接设备
        pre_devices = _devices_list()
        if debug:
            print(f">>> [扫描调试] 预扫描已连接设备: {pre_devices if pre_devices else '(无)'}")

        # 仅在没有任何已连接设备时才重启 server
        if not pre_devices:
            try:
                subprocess.run([scan_adb, "kill-server"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=3, creationflags=creationflags)
            except Exception:
                pass
            time.sleep(0.25)
            try:
                subprocess.run([scan_adb, "start-server"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               timeout=5, creationflags=creationflags)
            except Exception as e:
                if debug:
                    print(f">>> [扫描调试] start-server 异常: {e}")
            time.sleep(0.2)

        # MuMuManager 连接已存在的 MuMu 实例（仅连接 vms 中实际存在的，避免自动创建新设备）
        mumu_adb = AdbController._find_mumu_adb()
        if mumu_adb and os.path.isfile(mumu_adb):
            existing_ids = set()
            try:
                from emulator_discovery import get_mumu_serials_from_vms, _mum12_id_from_name
                for _, name, _ in get_mumu_serials_from_vms():
                    mid = _mum12_id_from_name(name)
                    if mid is not None:
                        existing_ids.add(mid)
            except Exception:
                pass
            if not existing_ids:
                existing_ids = {0}
            mumu_base = os.path.dirname(mumu_adb)
            for manager_name in ["MuMuManager.exe", "MuMuManager"]:
                manager_path = os.path.join(mumu_base, manager_name)
                if not os.path.isfile(manager_path):
                    manager_path = os.path.join(os.path.dirname(mumu_base), "shell", manager_name)
                if os.path.isfile(manager_path):
                    cwd = os.path.dirname(manager_path)
                    for instance_id in sorted(existing_ids):
                        try:
                            subprocess.Popen([manager_path, "adb", "-v", str(instance_id), "connect"],
                                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                             creationflags=creationflags, cwd=cwd)
                        except Exception:
                            pass
                    if debug:
                        print(f">>> [扫描调试] 已启动 MuMuManager 连接实例 {sorted(existing_ids)}")
                    break

        # 用当前扫描用 adb 对全部端口执行 connect
        _scan_procs = []
        for port in all_ports:
            try:
                p = subprocess.Popen([scan_adb, "connect", f"127.0.0.1:{port}"],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     creationflags=creationflags)
                _scan_procs.append(p)
            except Exception:
                pass
        time.sleep(1.5)
        for p in _scan_procs:
            try:
                p.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                try:
                    p.terminate()
                    p.wait(timeout=0.3)
                except Exception:
                    try:
                        p.kill()
                    except Exception:
                        pass
            except Exception:
                pass
        devices = _devices_list()
        # 去重并保持顺序（127.0.0.1:xxx 与 emulator-xxxx 可能同时存在，保留用户可读的）
        seen = set()
        unique = []
        for d in devices:
            if d not in seen:
                seen.add(d)
                unique.append(d)
        if debug:
            print(f">>> [扫描调试] 最终设备列表: {unique if unique else '(无)'}")
            if not unique:
                print(">>> [扫描调试] 可尝试在高级设置中指定 ADB 路径")
        _woa_debug_log(f"scan_devices 结束, 设备数={len(unique)}")
        return unique

    def connect(self):
        _woa_debug_log(f"connect 设备={getattr(self, 'device_serial', None)}")
        if self.device_serial and ":" in self.device_serial:
            # 针对网络设备的重连逻辑
            self.run_cmd(["disconnect", self.device_serial], timeout=5)
            time.sleep(0.3)
            r = self.run_cmd(["connect", self.device_serial], timeout=8)
            ok = False
            if r and r.stdout:
                out = r.stdout.decode('utf-8', errors='ignore')
                ok = "connected" in out.lower()
            if not ok:
                # 第一次失败，等待后重试
                time.sleep(1.0)
                r = self.run_cmd(["connect", self.device_serial], timeout=8)
                if r and r.stdout:
                    out = r.stdout.decode('utf-8', errors='ignore')
                    ok = "connected" in out.lower()
            if ok:
                _woa_debug_log("connect 成功")
            else:
                print(f"⚠️ [底层] ADB connect 未确认成功: {self.device_serial}")
            _woa_debug_log("connect 已执行 disconnect+connect")
            return ok
        return True

    def run_all_method_tests(self):
        """调试模式：在启动前测试所有截图方案和触控方案"""
        if not _woa_debug_enabled():
            return
        print(">>> [WOA_DEBUG] ========== 开始方案测试 ==========")
        bak_shot = self.screenshot_method
        bak_ctrl = self.control_method
        results = []

        # 测试截图方案
        for method in ("adb", "nemu_ipc", "uiautomator2", "droidcast_raw"):
            self.screenshot_method = method
            try:
                img = self.get_screenshot()
                ok = img is not None and img.size > 0
                hw = f"{img.shape[1]}x{img.shape[0]}" if ok else "-"
                msg = f"截图 {method}: {'✓' if ok else '✗'} {hw}"
                print(f">>> [WOA_DEBUG] {msg}")
                results.append(msg)
                if ok and _woa_debug_enabled():
                    _woa_debug_save_img(img, "method_test", f"screenshot_{method}")
            except Exception as e:
                msg = f"截图 {method}: ✗ 异常 {e}"
                print(f">>> [WOA_DEBUG] {msg}")
                results.append(msg)

        # 测试触控方案（仅检测初始化是否成功）
        for method in ("adb", "uiautomator2"):
            self.control_method = method
            self.use_minitouch = False
            ok = False
            try:
                if method == "adb":
                    ok = True
                else:
                    ok = self._u2_init() and bool(self._u2_device)
                msg = f"触控 {method}: {'✓' if ok else '✗'}"
                print(f">>> [WOA_DEBUG] {msg}")
                results.append(msg)
            except Exception as e:
                msg = f"触控 {method}: ✗ 异常 {e}"
                print(f">>> [WOA_DEBUG] {msg}")
                results.append(msg)

        self.screenshot_method = bak_shot
        self.control_method = bak_ctrl
        self.use_minitouch = False
        print(">>> [WOA_DEBUG] ========== 方案测试结束 ==========")

    def _get_screenshot_nemu_ipc(self):
        """MuMu12 nemu_ipc 截图（委托给 NemuIpcHelper）"""
        return self._nemu_ipc.get_screenshot()

    def _get_droidcast_raw_apk_path(self):
        """获取 DroidCast_raw.apk 路径（参考 ALAS，需从 Torther/DroidCastS 下载）"""
        for base in _get_u2_jar_candidate_dirs():
            p = os.path.join(base, "assets", "DroidCast_raw.apk")
            if os.path.isfile(p):
                return p
        return None

    def _droidcast_init(self):
        """初始化 DroidCast_raw：推送 APK、启动服务、建立端口转发（参考 ALAS droidcast.py）"""
        if self._droidcast_session is not None and self._droidcast_port > 0:
            return True
        if self._closed or not self.device_serial or self.screenshot_method != "droidcast_raw":
            return False
        apk_path = self._get_droidcast_raw_apk_path()
        if not apk_path:
            if not self._droidcast_fallback_logged:
                self._droidcast_fallback_logged = True
                print(">>> [DroidCast_raw] 未找到 assets/DroidCast_raw.apk，请从 https://github.com/Torther/DroidCastS/releases 下载并放入 assets/")
            return False
        try:
            self._droidcast_stop()
            r = self.run_cmd(["push", apk_path, "/data/local/tmp/DroidCast_raw.apk"], timeout=15)
            if not r or r.returncode != 0:
                if not self._droidcast_fallback_logged:
                    self._droidcast_fallback_logged = True
                    print(">>> [DroidCast_raw] 推送 APK 失败，回退到 ADB")
                return False
            adb_path = self.adb_path if self.adb_path and os.path.isfile(self.adb_path) else None
            if not adb_path:
                adb_path = get_bundled_resource_path(os.path.join("adb_tools", "adb.exe"))
            adb_path = adb_path if adb_path and os.path.isfile(adb_path) else "adb"
            try:
                self._droidcast_proc = subprocess.Popen(
                    [adb_path, "-s", self.device_serial, "shell",
                     "CLASSPATH=/data/local/tmp/DroidCast_raw.apk app_process / ink.mol.droidcast_raw.Main"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=0x08000000 if sys.platform == "win32" else 0,
                )
            except Exception as e:
                if not self._droidcast_fallback_logged:
                    self._droidcast_fallback_logged = True
                    print(f">>> [DroidCast_raw] 启动失败: {e}，回退到 ADB")
                return False
            time.sleep(2.0)
            self.run_cmd(["forward", "--remove", f"tcp:{self._droidcast_base_port}"], timeout=5)
            if not self._adb_forward(f"tcp:{self._droidcast_base_port}", f"tcp:{self._droidcast_base_port}"):
                if getattr(self, "_droidcast_proc", None):
                    try:
                        self._droidcast_proc.terminate()
                    except Exception:
                        pass
                    self._droidcast_proc = None
                if not self._droidcast_fallback_logged:
                    self._droidcast_fallback_logged = True
                    print(">>> [DroidCast_raw] 端口转发失败，回退到 ADB")
                return False
            self._droidcast_port = self._droidcast_base_port
            self._droidcast_session = True  # 使用 urlopen 无需 session 对象
            print(">>> [DroidCast_raw] 已启用")
            return True
        except Exception as e:
            if not self._droidcast_fallback_logged:
                self._droidcast_fallback_logged = True
                print(f">>> [DroidCast_raw] 初始化异常: {e}，回退到 ADB")
            return False

    def _droidcast_stop(self):
        """停止 DroidCast 进程（参考 ALAS）"""
        try:
            self.run_cmd(["shell", "pkill", "-9", "-f", "ink.mol.droidcast_raw"], timeout=5)
        except Exception:
            pass
        try:
            self.run_cmd(["shell", "pkill", "-9", "-f", "DroidCast"], timeout=5)
        except Exception:
            pass
        self.run_cmd(["forward", "--remove", f"tcp:{self._droidcast_base_port}"], timeout=3)

    def _get_screenshot_droidcast_raw(self):
        """DroidCast 截图（PNG模式）：使用 /preview 接口避免 RGB565 格式问题，请求 1600x900。
        部分云手机/不同机型会返回非 1600x900 分辨率，这里统一放宽并交由后续标准化处理。"""
        import cv2
        import numpy as np
        if not self._droidcast_init():
            return None
        
        # 尝试请求 PNG 预览图，指定分辨率
        w_req, h_req = 1600, 900
        try:
            from urllib.request import urlopen
            # DroidCast_raw 也支持 /preview 接口返回 PNG
            url = f"http://127.0.0.1:{self._droidcast_base_port}/preview?width={w_req}&height={h_req}"
            resp = urlopen(url, timeout=5)
            image = resp.read()
        except Exception:
            return None
            
        if not image:
            return None
            
        try:
            # 解码 PNG
            arr = np.frombuffer(image, np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if img is None:
                return None
                
            # 检查分辨率并修正
            h, w = img.shape[:2]

            # 若为竖屏则旋转到横屏，剩余缩放统一由 _normalize_to_logical_resolution 处理。
            if h > w:
                img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)

            return img
        except Exception:
            return None

    def _get_screenshot_u2(self, as_fallback=False):
        """uiautomator2 截图（atx-agent）。as_fallback=True 时允许在非 u2 配置下尝试（用于 nemu_ipc 等回退链）
        参考 ALAS：失败时重试，JSONDecodeError 时重装 atx-agent"""
        import cv2
        import numpy as np
        if as_fallback:
            ok = self._u2_init_impl(for_control=False, allow_screenshot_fallback=True)
        else:
            ok = self._u2_init_screenshot()
        if not ok or not self._u2_device:
            return None
        for attempt in range(2):
            try:
                pil_img = self._u2_device.screenshot()
                if pil_img is None:
                    raise RuntimeError("screenshot returned None")
                arr = np.asarray(pil_img)
                if arr.ndim != 3 or arr.size == 0:
                    raise RuntimeError("invalid screenshot array")
                if arr.shape[2] == 3:
                    img = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
                elif arr.shape[2] == 4:
                    img = cv2.cvtColor(arr, cv2.COLOR_RGBA2BGR)
                else:
                    return None
                return img
            except Exception as e:
                if attempt == 0:
                    # 首次失败：重置 u2 连接，尝试重连
                    err_name = type(e).__name__
                    _woa_debug_log(f"u2 screenshot 失败({err_name}: {e})，尝试重连...")
                    self._u2_device = None
                    # JSONDecodeError 通常意味着 atx-agent 崩溃，需要重装
                    try:
                        from json import JSONDecodeError
                        if isinstance(e, JSONDecodeError):
                            print(f">>> [uiautomator2] atx-agent 异常，尝试重装...")
                            self._u2_reinstall_atx_agent()
                    except ImportError:
                        pass
                    # 重新初始化连接
                    if as_fallback:
                        self._u2_init_impl(for_control=False, allow_screenshot_fallback=True)
                    else:
                        self._u2_init_screenshot()
                    if not self._u2_device:
                        return None
                else:
                    return None
        return None

    def _u2_reinstall_atx_agent(self):
        """重装 atx-agent（参考 ALAS install_uiautomator2）"""
        try:
            import uiautomator2 as u2
            import logging
            adb_dev = self._get_adb_client_for_u2()
            init = u2.init.Initer(adb_dev, loglevel=logging.WARNING)
            if hasattr(init, 'abi') and hasattr(init, 'abis'):
                if init.abi not in ['x86_64', 'x86', 'arm64-v8a', 'armeabi-v7a', 'armeabi']:
                    if init.abis:
                        init.abi = init.abis[0]
            if hasattr(init, 'set_atx_agent_addr'):
                init.set_atx_agent_addr('127.0.0.1:7912')
            try:
                init.install()
            except ConnectionError:
                if hasattr(u2.init, 'GITHUB_BASEURL'):
                    u2.init.GITHUB_BASEURL = 'http://tool.appetizer.io/openatx'
                    init.install()
            print(">>> [uiautomator2] atx-agent 重装完成")
        except Exception as e:
            print(f">>> [uiautomator2] atx-agent 重装失败: {e}")

    _SCREENSHOT_MAX_CONSEC_FAILS = 3
    _SCREENSHOT_RECOVERY_INTERVAL = 120
    _CONTROL_MAX_CONSEC_FAILS = 3
    _CONTROL_RECOVERY_INTERVAL = 120

    def get_screenshot(self, force_method=None):
        """force_method: 可选 'adb'，强制使用 ADB 截图（用于 nemu_ipc 检测异常时回退）"""
        import cv2
        import numpy as np
        import tempfile
        _woa_debug_log(f"get_screenshot 请求 force_method={force_method} 当前方法={getattr(self, 'screenshot_method', 'adb')}")
        if not self.device_serial:
            _woa_debug_log("get_screenshot 无 device_serial 返回 None")
            return None

        if force_method != "adb" and self._desired_screenshot_method != "adb" \
                and self.screenshot_method != self._desired_screenshot_method:
            now = time.time()
            if now - self._last_screenshot_recovery_time > self._SCREENSHOT_RECOVERY_INTERVAL:
                self._last_screenshot_recovery_time = now
                self.screenshot_method = self._desired_screenshot_method
                self._screenshot_consec_fails = 0
                print(f">>> [模式] 尝试恢复截图方案: {self._desired_screenshot_method}")

        use_nemu = (self.screenshot_method == "nemu_ipc" and force_method != "adb")
        use_u2 = (self.screenshot_method == "uiautomator2" and force_method != "adb")
        use_droidcast = (self.screenshot_method == "droidcast_raw" and force_method != "adb")

        def _log_screenshot_fallback(from_m, to_m, reason=""):
            msg = f">>> [模式] ⚠️ 截图方案已切换: {from_m} -> {to_m}"
            if reason:
                msg += f"（原因: {reason}）"
            print(msg)

        def _handle_screenshot_degrade(from_m, to_m, reason=""):
            self._screenshot_consec_fails += 1
            if self._screenshot_consec_fails >= self._SCREENSHOT_MAX_CONSEC_FAILS:
                self.set_screenshot_method(to_m, _is_fallback=True)
                _log_screenshot_fallback(from_m, to_m, reason)
                self._last_screenshot_recovery_time = time.time()

        if use_droidcast:
            img = self._get_screenshot_droidcast_raw()
            if img is not None:
                self._screenshot_consec_fails = 0
                _woa_debug_log("get_screenshot 成功 droidcast_raw")
                normalized = self._normalize_to_logical_resolution(img)
                _woa_debug_save_screenshot(normalized, "droidcast_raw")
                return normalized
            _woa_debug_log("get_screenshot droidcast_raw 失败，尝试 uiautomator2")
            img = self._get_screenshot_u2(as_fallback=True)
            if img is not None:
                self.set_screenshot_method("uiautomator2", _is_fallback=True)
                _log_screenshot_fallback("droidcast_raw", "uiautomator2", "droidcast_raw 截图失败，u2 回退成功")
                _woa_debug_log("get_screenshot 成功 uiautomator2(回退)")
                normalized = self._normalize_to_logical_resolution(img)
                _woa_debug_save_screenshot(normalized, "u2")
                return normalized
            _handle_screenshot_degrade("droidcast_raw", "adb", "droidcast_raw 与 u2 均失败")
            _woa_debug_log("get_screenshot droidcast_raw 回退链结束，使用 ADB")

        if use_u2:
            img = self._get_screenshot_u2()
            if img is not None:
                self._screenshot_consec_fails = 0
                _woa_debug_log("get_screenshot 成功 uiautomator2")
                normalized = self._normalize_to_logical_resolution(img)
                _woa_debug_save_screenshot(normalized, "u2")
                return normalized
            _handle_screenshot_degrade("uiautomator2", "adb", "uiautomator2 截图失败")
            _woa_debug_log("get_screenshot uiautomator2 失败，回退 ADB")

        if use_nemu:
            if sys.platform != "win32":
                if self._nemu_ipc._logged != "fail":
                    self._nemu_ipc._logged = "fail"
                    self.set_screenshot_method("adb", _is_fallback=True)
                    _log_screenshot_fallback("nemu_ipc", "adb", "nemu_ipc 仅支持 Windows")
            else:
                img = self._get_screenshot_nemu_ipc()
                if img is not None:
                    self._screenshot_consec_fails = 0
                    _woa_debug_log("get_screenshot 成功 nemu_ipc")
                    normalized = self._normalize_to_logical_resolution(img)
                    _woa_debug_save_screenshot(normalized, "nemu_ipc")
                    return normalized
                _woa_debug_log("get_screenshot nemu_ipc 失败，尝试 uiautomator2")
                img = self._get_screenshot_u2(as_fallback=True)
                if img is not None:
                    self.set_screenshot_method("uiautomator2", _is_fallback=True)
                    _log_screenshot_fallback("nemu_ipc", "uiautomator2", "nemu_ipc 截图失败，u2 回退成功")
                    _woa_debug_log("get_screenshot 成功 uiautomator2(回退)")
                    normalized = self._normalize_to_logical_resolution(img)
                    _woa_debug_save_screenshot(normalized, "u2")
                    return normalized
                _handle_screenshot_degrade("nemu_ipc", "adb", "nemu_ipc 与 u2 均失败")
                _woa_debug_log("get_screenshot nemu_ipc 回退链结束，使用 ADB")

        def _try_exec_out():
            adb = self.adb_path
            cmd = [adb, "-s", self.device_serial, "exec-out", "screencap", "-p"]
            try:
                result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=8,
                                        creationflags=0x08000000, cwd=os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else None)
                if result.stdout and len(result.stdout) > 100:
                    image_array = np.frombuffer(result.stdout, np.uint8)
                    img = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
                    if img is not None:
                        return img
            except Exception:
                pass
            return None

        def _try_pull():
            tmp_path = os.path.join(tempfile.gettempdir(), f"woa_sc_{os.getpid()}.png")
            try:
                r1 = self.run_cmd(["shell", "screencap", "-p", "/sdcard/woa_sc.png"], timeout=8)
                if r1 is None:
                    return None
                r2 = self.run_cmd(["pull", "/sdcard/woa_sc.png", tmp_path], timeout=8)
                if r2 is None:
                    return None
                if os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 100:
                    img = self._read_image_safe(tmp_path)
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass
                    if img is not None:
                        return img
            except Exception:
                pass
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
            return None

        img = _try_exec_out()
        if img is not None:
            self._adb_screenshot_consec_total_fails = 0
            _woa_debug_log("get_screenshot 成功 adb(exec-out)")
            normalized = self._normalize_to_logical_resolution(img)
            _woa_debug_save_screenshot(normalized, "adb_exec")
            return normalized
        img = _try_pull()
        if img is not None:
            self._adb_screenshot_consec_total_fails = 0
            _woa_debug_log("get_screenshot 成功 adb(pull)")
            normalized = self._normalize_to_logical_resolution(img)
            _woa_debug_save_screenshot(normalized, "adb_pull")
            return normalized
        # 重试一次（部分模拟器偶发失败）
        time.sleep(0.2)
        img = _try_exec_out() or _try_pull()
        if img is not None:
            self._adb_screenshot_consec_total_fails = 0
            _woa_debug_log("get_screenshot 成功 adb(重试)")
            normalized = self._normalize_to_logical_resolution(img)
            _woa_debug_save_screenshot(normalized, "adb_retry")
            return normalized
        else:
            # 连续全部失败时尝试 ADB 重连
            if not hasattr(self, '_adb_screenshot_consec_total_fails'):
                self._adb_screenshot_consec_total_fails = 0
            self._adb_screenshot_consec_total_fails += 1
            _woa_debug_log(f"get_screenshot 全部失败 (连续{self._adb_screenshot_consec_total_fails}次)")
            if self._adb_screenshot_consec_total_fails >= 3:
                print(f"⚠️ [底层] 截图连续{self._adb_screenshot_consec_total_fails}次全部失败，尝试 ADB 重连...")
                self._adb_screenshot_consec_total_fails = 0
                self.connect()
                self._start_persistent_shell()
        return None

    def get_pixel_color(self, x, y):
        screen = self.get_screenshot()
        if screen is None: return None
        try:
            b, g, r = screen[y, x]
            return int(b), int(g), int(r)
        except:
            return None

    def click(self, x, y, random_offset=5):
        self._do_think()
        jitter = max(float(random_offset), float(self.default_click_jitter))
        x, y = self._apply_coordinate_jitter(x, y, jitter)
        xi, yi = int(round(x)), int(round(y))
        adb_x, adb_y = self._logical_to_device_point(xi, yi)

        if self._desired_control_method != "adb" \
                and self.control_method != self._desired_control_method:
            now = time.time()
            if now - self._last_control_recovery_time > self._CONTROL_RECOVERY_INTERVAL:
                self._last_control_recovery_time = now
                self.control_method = self._desired_control_method
                self.use_minitouch = (self._desired_control_method == "minitouch")
                self._control_consec_fails = 0
                self._minitouch_ready = False
                self._minitouch_runtime_fallback_logged = False
                print(f">>> [模式] 尝试恢复触控方案: {self._desired_control_method}")

        def _log_control_fallback(from_m, to_m, reason=""):
            msg = f">>> [模式] ⚠️ 触控方案已切换: {from_m} -> {to_m}"
            if reason:
                msg += f"（原因: {reason}）"
            print(msg)

        def _handle_control_degrade(from_m, reason=""):
            self._control_consec_fails += 1
            if self._control_consec_fails >= self._CONTROL_MAX_CONSEC_FAILS:
                self.set_control_method("adb", _is_fallback=True)
                _log_control_fallback(from_m, "adb", reason)
                self._last_control_recovery_time = time.time()

        # uiautomator2
        if self.control_method == "uiautomator2":
            _woa_debug_log(f"click 使用 uiautomator2 logical=({xi},{yi}) device=({adb_x},{adb_y})")
            if self._u2_init() and self._u2_device:
                try:
                    self._u2_device.click(adb_x, adb_y)
                    self._control_consec_fails = 0
                    _woa_debug_log("click 已发送 uiautomator2")
                    return
                except Exception as e:
                    _woa_debug_log(f"click uiautomator2 异常: {e}")
                    if not self._u2_fallback_logged:
                        self._u2_fallback_logged = True
                        print("⚠️ [uiautomator2] 触控失败，回退到 ADB")
            _handle_control_degrade("uiautomator2", "uiautomator2 触控失败")
            self._adb_click_fallback(adb_x, adb_y)
            _woa_debug_log("click 已回退 adb_click_fallback")
            return

        if self.use_minitouch:
            if not self._minitouch_ready:
                self._minitouch_init()
            if self._minitouch_ready and self._minitouch_client:
                tx, ty = self._minitouch_scale(xi, yi)
                _woa_debug_log(f"click 使用 minitouch 屏幕({xi},{yi}) -> minitouch({tx},{ty})")
                s = f"d 0 {tx} {ty} 50\nc\nu 0\nc\n"
                if self._minitouch_send(s):
                    self._control_consec_fails = 0
                    _woa_debug_log("click 已发送 minitouch")
                    return
                self._minitouch_ready = False
                _woa_debug_log("click minitouch 发送失败")
                if not getattr(self, '_minitouch_runtime_fallback_logged', False):
                    self._minitouch_runtime_fallback_logged = True
                    print("⚠️ [minitouch] 触控发送失败，已回退到 ADB")
            _handle_control_degrade("minitouch", "minitouch 发送失败")

        _woa_debug_log(f"click 使用 adb shell input tap logical=({xi},{yi}) device=({adb_x},{adb_y})")
        self._adb_click_fallback(adb_x, adb_y)
        _woa_debug_log("click 已发送 adb")

    def double_click(self, x, y, random_offset=20):
        self.click(x, y, random_offset)
        time.sleep(0.08)  # 双击间隔
        self.click(x, y, random_offset)

    def swipe(self, x1, y1, x2, y2, duration_ms=1000):
        self._do_think()
        x1, y1 = self._apply_coordinate_jitter(x1, y1, self.default_swipe_jitter)
        x2, y2 = self._apply_coordinate_jitter(x2, y2, self.default_swipe_jitter)
        x1i, y1i = int(round(x1)), int(round(y1))
        x2i, y2i = int(round(x2)), int(round(y2))
        d1x, d1y = self._logical_to_device_point(x1i, y1i)
        d2x, d2y = self._logical_to_device_point(x2i, y2i)
        _woa_debug_log(f"swipe ({x1i},{y1i})->({x2i},{y2i}) duration={duration_ms}ms method={self.control_method} minitouch={self.use_minitouch}")

        if self.control_method == "uiautomator2":
            if self._u2_init() and self._u2_device:
                try:
                    self._u2_device.swipe(d1x, d1y, d2x, d2y, duration=duration_ms / 1000.0)
                    _woa_debug_log("swipe 已发送 uiautomator2")
                    return
                except Exception as e:
                    _woa_debug_log(f"swipe u2 异常: {e}")
            self.run_cmd(["shell", "input", "swipe", str(d1x), str(d1y), str(d2x), str(d2y), str(duration_ms)])
            _woa_debug_log("swipe 已发送 adb")
            return

        if self.use_minitouch:
            if not self._minitouch_ready:
                self._minitouch_init()
            if self._minitouch_ready and self._minitouch_client:
                n = max(5, duration_ms // 20)
                pts = []
                for i in range(n + 1):
                    t = i / n
                    px = int(x1i + (x2i - x1i) * t)
                    py = int(y1i + (y2i - y1i) * t)
                    pts.append(self._minitouch_scale(px, py))
                sb = []
                for i, (tx, ty) in enumerate(pts):
                    if i == 0:
                        sb.append(f"d 0 {tx} {ty} 50\nc\n")
                    else:
                        sb.append(f"m 0 {tx} {ty} 50\nc\n")
                    sb.append(f"w {duration_ms // n}\n")
                sb.append("u 0\nc\nw 10\n")
                if self._minitouch_send("".join(sb)):
                    _woa_debug_log("swipe 已发送 minitouch")
                    return
                self._minitouch_ready = False

        _woa_debug_log("swipe 使用 adb shell input swipe")
        cmd = f"input swipe {d1x} {d1y} {d2x} {d2y} {duration_ms}"
        if not self._write_shell_cmd(cmd):
            self.run_cmd([
                "shell", "input", "swipe",
                str(d1x), str(d1y), str(d2x), str(d2y), str(duration_ms)
            ])

    # 图像识别相关方法保持不变，因为它们不涉及 ADB 通信
    def _read_image_safe(self, path):
        return read_image_safe(path)

    _template_cache = {}

    def locate_image(self, template_path, confidence=0.8, screen_image=None):
        import cv2
        if screen_image is not None:
            screen = screen_image
        else:
            screen = self.get_screenshot()
        if screen is None: return None
        template = self._template_cache.get(template_path)
        if template is None:
            template = self._read_image_safe(template_path)
            if template is None: return None
            self._template_cache[template_path] = template
        result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
        if max_val >= confidence:
            h, w = template.shape[:2]
            return (max_loc[0] + w // 2, max_loc[1] + h // 2, (max_loc[0], max_loc[1], w, h))
        return None

    def locate_all_images(self, template_path, confidence=0.8, screen_image=None):
        import cv2
        import numpy as np
        if screen_image is not None:
            screen = screen_image
        else:
            screen = self.get_screenshot()
        if screen is None: return []
        template = self._template_cache.get(template_path)
        if template is None:
            template = self._read_image_safe(template_path)
            if template is None: return []
            self._template_cache[template_path] = template
        result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
        h, w = template.shape[:2]
        loc = np.where(result >= confidence)
        found_items = []
        for pt in zip(*loc[::-1]):
            score = result[pt[1], pt[0]]
            is_duplicate = False
            for item in found_items:
                if abs(pt[0] - item['box'][0]) < 10 and abs(pt[1] - item['box'][1]) < 10:
                    if score > item['score']:
                        item['score'] = score
                        item['box'] = (pt[0], pt[1], w, h)
                        item['top'] = pt[1]
                        item['center'] = (pt[0] + w // 2, pt[1] + h // 2)
                    is_duplicate = True
                    break
            if not is_duplicate:
                found_items.append(
                    {'box': (pt[0], pt[1], w, h), 'top': pt[1], 'center': (pt[0] + w // 2, pt[1] + h // 2),
                     'score': score})
        return found_items
