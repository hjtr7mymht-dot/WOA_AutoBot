# MuMu12 nemu_ipc DLL 截图模块
# 从 adb_controller.py 提取的独立模块

import ctypes
import os
import sys

from woa_debug import _woa_debug_log, save_image_safe

# 写死为 0，长期关闭 nemu_ipc_debug 文件夹内截图保存；改为 1 可重新开启
NEMU_IPC_DEBUG = 0


class _SafeDLLWrapper:
    """包装 DLL 句柄，手动通过 GetProcAddress 获取函数地址，绕过 Nuitka 的 ctypes 拦截逻辑"""
    def __init__(self, handle, path):
        self._handle = handle
        self._path = path
        self._funcs = {}

        # 必须显式定义 GetProcAddress 的签名，否则 64位 下默认返回 c_int 会导致地址截断/溢出
        self._get_proc_addr = ctypes.windll.kernel32.GetProcAddress
        self._get_proc_addr.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        self._get_proc_addr.restype = ctypes.c_void_p

    def __getattr__(self, name):
        if name in self._funcs:
            return self._funcs[name]

        # 尝试多种可能的函数名变体
        camel_name = "".join(x.capitalize() for x in name.split("_"))
        parts = name.split("_")

        variants = [
            name.encode('ascii'),                             # nemu_connect
            f"{name}W".encode('ascii'),                        # nemu_connectW
            camel_name.encode('ascii'),                        # NemuConnect
            f"{camel_name}W".encode('ascii'),                  # NemuConnectW
            name.replace("nemu_", "nemu_ipc_").encode('ascii'),# nemu_ipc_connect
            # NemuIpcConnect
            (parts[0].capitalize() + "Ipc" + "".join(p.capitalize() for p in parts[1:])).encode('ascii'),
            name.replace("nemu_", "mumu_").encode('ascii'),   # mumu_connect
            name.replace("nemu_", "mumu_ipc_").encode('ascii'),# mumu_ipc_connect
            ("Renderer" + "".join(p.capitalize() for p in parts[1:])).encode('ascii'), # RendererConnect
            name.replace("nemu_", "").encode('ascii'),        # connect
            f"_{name}".encode('ascii'),                        # _nemu_connect
            f"_{name}@8".encode('ascii')                       # _nemu_connect@8
        ]

        addr = None
        for v in variants:
            addr = self._get_proc_addr(self._handle, v)
            if addr: break

        if not addr:
            raise AttributeError(f"function '{name}' (variants: {variants}) not found in {self._path}")

        class FuncWrapper:
            def __init__(self, addr, name):
                self._addr = addr
                self._name = name
                self.argtypes = None
                self.restype = ctypes.c_int
            def __call__(self, *args):
                types = self.argtypes if self.argtypes is not None else []
                try:
                    f = ctypes.CFUNCTYPE(self.restype, *types)(self._addr)
                    return f(*args)
                except ValueError:
                    f = ctypes.WINFUNCTYPE(self.restype, *types)(self._addr)
                    return f(*args)

        wrapped = FuncWrapper(addr, name)
        self._funcs[name] = wrapped
        return wrapped


def _load_dll_safe(dll_path):
    """从可能包含中文的路径加载 DLL，兼容 ctypes 在非 ASCII 路径下的问题"""
    dll_path = os.path.abspath(dll_path)
    if not os.path.exists(dll_path):
        return None

    handle = None

    # 策略1：直接尝试 ctypes.CDLL
    try:
        dll_dir = os.path.dirname(dll_path)
        if hasattr(os, 'add_dll_directory'):
            try:
                os.add_dll_directory(dll_dir)
            except Exception:
                pass

        lib = ctypes.CDLL(dll_path)
        handle = lib._handle
    except Exception:
        pass

    # 策略2：Nuitka 兼容模式 / 手动 LoadLibraryExW
    if not handle:
        try:
            load_lib = ctypes.windll.kernel32.LoadLibraryExW
            load_lib.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_uint32]
            load_lib.restype = ctypes.c_void_p
            handle = load_lib(dll_path, None, 0x00000008)
        except Exception:
            pass

    # 策略3：回退到 chdir + CDLL
    if not handle:
        dll_dir = os.path.dirname(dll_path)
        dll_name = os.path.basename(dll_path)
        old_cwd = os.getcwd()
        try:
            os.chdir(dll_dir)
            lib = ctypes.CDLL(dll_name)
            handle = lib._handle
        except Exception:
            pass
        finally:
            try:
                os.chdir(old_cwd)
            except OSError:
                pass

    if handle:
        return _SafeDLLWrapper(handle, dll_path)

    return None


class NemuIpcHelper:
    """封装 MuMu12 nemu_ipc 截图逻辑，从 AdbController 中提取。
    通过 self._ctrl 引用父 AdbController 实例以访问 device_serial、adb_path 等。"""

    def __init__(self, controller):
        self._ctrl = controller
        self._lib = None
        self._connect_id = 0
        self._folder = None
        self._instance_id = None
        self._logged = None  # "ok"/"fail"
        self._pixel_format = None
        self._executor = None
        self._nx_device = False
        self._debug_count = 0

    def find_folder_and_id(self):
        """从 serial 解析 MuMu12 安装路径和实例 ID（参考 ALAS NemuIpcImpl.serial_to_id）"""
        if not self._ctrl.device_serial or ":" not in self._ctrl.device_serial:
            return None, None
        try:
            port = int(self._ctrl.device_serial.split(":")[1])
        except (ValueError, IndexError):
            return None, None
        index, offset = divmod(port - 16384 + 16, 32)
        offset -= 16
        if not (0 <= index < 33 and offset in (-2, -1, 0, 1, 2)):
            return None, None

        # 优先使用手动指定的 MuMu 安装路径
        if self._ctrl.mumu_path and os.path.isdir(self._ctrl.mumu_path):
            folder = os.path.abspath(self._ctrl.mumu_path)
            if "MuMuPlayerGlobal" in folder:
                return None, None
            for rel in ("shell/sdk/external_renderer_ipc.dll", "nx_device/12.0/shell/sdk/external_renderer_ipc.dll"):
                fp = os.path.join(folder, rel)
                if os.path.isfile(fp):
                    try:
                        if self._ctrl._nemu_folder_callback:
                            self._ctrl._nemu_folder_callback(folder)
                    except Exception:
                        pass
                    return folder, index

        try:
            from emulator_discovery import get_mumu_serials_from_vms
        except ImportError:
            return None, None
        for serial, name, emu_dir in get_mumu_serials_from_vms():
            if serial != self._ctrl.device_serial:
                continue
            if not emu_dir or not os.path.isdir(emu_dir):
                continue
            cand_folders = [emu_dir]
            if "MuMuPlayerGlobal" in emu_dir:
                print(f"❌ [nemu_ipc] MuMuPlayerGlobal 不支持 nemu_ipc 截图")
                return None, None
            for sub in ("MuMu Player 12", "MuMuPlayer-12.0", "MuMuPlayer12", "MuMu"):
                p = os.path.join(emu_dir, sub)
                if os.path.isdir(p):
                    cand_folders.append(p)
            for folder in cand_folders:
                for rel in ("shell/sdk/external_renderer_ipc.dll", "nx_device/12.0/shell/sdk/external_renderer_ipc.dll"):
                    fp = os.path.join(folder, rel)
                    if os.path.isfile(fp):
                        try:
                            if self._ctrl._nemu_folder_callback:
                                self._ctrl._nemu_folder_callback(os.path.abspath(folder))
                        except Exception:
                            pass
                        return folder, index
        # 回退2：从当前 ADB 路径推断 MuMu 根目录
        adb_path = self._ctrl.adb_path if self._ctrl.adb_path and os.path.isfile(self._ctrl.adb_path) else None
        if adb_path and "nx_main" in adb_path.replace("\\", "/") and "Netease" in adb_path:
            mumu_root = os.path.dirname(os.path.dirname(os.path.abspath(adb_path)))
            if "MuMuPlayerGlobal" in mumu_root:
                return None, None
            if os.path.isdir(mumu_root):
                for rel in ("shell/sdk/external_renderer_ipc.dll", "nx_device/12.0/shell/sdk/external_renderer_ipc.dll"):
                    fp = os.path.join(mumu_root, rel)
                    if os.path.isfile(fp):
                        try:
                            if self._ctrl._nemu_folder_callback:
                                self._ctrl._nemu_folder_callback(os.path.abspath(mumu_root))
                        except Exception:
                            pass
                        return mumu_root, index
        # 回退3：扫描 Netease 等目录
        try:
            from emulator_discovery import get_mumu_nemu_folders_for_serial
        except ImportError:
            pass
        else:
            for folder, idx in get_mumu_nemu_folders_for_serial(self._ctrl.device_serial):
                if folder and os.path.isdir(folder) and idx == index:
                    try:
                        if self._ctrl._nemu_folder_callback:
                            self._ctrl._nemu_folder_callback(os.path.abspath(folder))
                    except Exception:
                        pass
                    return folder, idx
        return None, None

    def _capture_stderr(self, func, *args):
        """捕获 DLL 输出的 stderr（参考 ALAS CaptureNemuIpc）"""
        stderr_b = b''
        r = w = None
        try:
            fd_err = sys.stderr.fileno()
        except (ValueError, OSError):
            return stderr_b
        try:
            r, w = os.pipe()
            old_stderr = os.dup(fd_err)
            os.dup2(w, fd_err)
            sys.stderr.flush()
            try:
                func(*args)
            finally:
                os.dup2(old_stderr, fd_err)
                os.close(old_stderr)
                if w is not None:
                    os.close(w)
                    w = None
            chunks = []
            while r is not None:
                try:
                    chunk = os.read(r, 4096)
                    if not chunk:
                        break
                    chunks.append(chunk)
                except (OSError, BlockingIOError):
                    break
            stderr_b = b''.join(chunks)
        except Exception:
            pass
        if r is not None:
            try:
                os.close(r)
            except OSError:
                pass
        if w is not None:
            try:
                os.close(w)
            except OSError:
                pass
        return stderr_b

    def _auto_detect_format(self, arr, height, width):
        """通过与 ADB 截图比对，自动确定 RGBA 或 BGRA"""
        import cv2
        import numpy as np
        do_flip = os.environ.get("NEMU_IPC_FLIP", "1") != "0"
        img_rgba = cv2.cvtColor(arr, cv2.COLOR_RGBA2BGR)
        img_bgra = cv2.cvtColor(arr, cv2.COLOR_BGRA2BGR)
        if do_flip:
            img_rgba = cv2.flip(img_rgba, 0)
            img_bgra = cv2.flip(img_bgra, 0)
        adb_img = self._ctrl.get_screenshot(force_method="adb")
        if adb_img is None or adb_img.size == 0:
            self._pixel_format = "rgba"
            return "rgba"
        if adb_img.shape[:2] != (height, width):
            adb_img = cv2.resize(adb_img, (width, height), interpolation=cv2.INTER_LINEAR)
        mse_rgba = np.mean((img_rgba.astype(np.float32) - adb_img.astype(np.float32)) ** 2)
        mse_bgra = np.mean((img_bgra.astype(np.float32) - adb_img.astype(np.float32)) ** 2)
        chosen = "rgba" if mse_rgba <= mse_bgra else "bgra"
        self._pixel_format = chosen
        print(f">>> [nemu_ipc] 已自动检测像素格式: {chosen} (MSE rgba={mse_rgba:.0f} bgra={mse_bgra:.0f})")
        return chosen

    def _debug_save(self, img_bgr, arr_raw, width, height, pixel_fmt, do_flip):
        """调试：保存 nemu_ipc 截图及对比用 ADB 截图"""
        import datetime
        debug_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nemu_ipc_debug")
        try:
            os.makedirs(debug_dir, exist_ok=True)
        except OSError:
            return
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        if self._debug_count >= 5:
            return
        self._debug_count += 1
        try:
            p_nemu = os.path.join(debug_dir, f"nemu_{ts}_fmt{pixel_fmt}_flip{int(do_flip)}.png")
            save_image_safe(p_nemu, img_bgr)
            bgr_mean = img_bgr.mean(axis=(0, 1))
            print(f">>> [nemu_ipc DEBUG] 已保存: {p_nemu}  shape={img_bgr.shape} BGR_mean={bgr_mean.round(1).tolist()}")
            adb_img = self._ctrl.get_screenshot(force_method="adb")
            if adb_img is not None and adb_img.size > 0:
                p_adb = os.path.join(debug_dir, f"adb_{ts}.png")
                save_image_safe(p_adb, adb_img)
                adb_mean = adb_img.mean(axis=(0, 1))
                print(f">>> [nemu_ipc DEBUG] 已保存: {p_adb}  BGR_mean={adb_mean.round(1).tolist()}")
        except Exception as e:
            print(f">>> [nemu_ipc DEBUG] 保存失败: {e}")

    def _check_keep_alive(self, mumu_root, instance_id):
        """检查 MuMu12 是否开启了'后台挂机时保活运行'"""
        try:
            import json
            vms_dir = os.path.join(mumu_root, "vms")
            if not os.path.isdir(vms_dir):
                return True
            target_name = f"MuMuPlayer-12.0-{instance_id}"
            config_file = os.path.join(vms_dir, target_name, "configs", "customer_config.json")
            if not os.path.isfile(config_file):
                alt_configs = [
                    os.path.join(vms_dir, "MuMuPlayer-12.0", "configs", "customer_config.json"),
                    os.path.join(vms_dir, f"MuMuPlayer-12.0-instance{instance_id}", "configs", "customer_config.json")
                ]
                for alt in alt_configs:
                    if os.path.isfile(alt):
                        config_file = alt
                        break
            if os.path.isfile(config_file):
                with open(config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    keptlive = data.get("customer", {}).get("app_keptlive", False)
                    if keptlive is True or str(keptlive).lower() == "true":
                        print("❌ [nemu_ipc] 检测到模拟器开启了'后台挂机时保活运行'，这会导致截图失败。")
                        print(">>> 请在 MuMu 模拟器设置 -> 运行设置 中关闭该选项后重试。")
                        return False
        except Exception:
            pass
        return True

    def get_screenshot(self):
        """MuMu12 nemu_ipc 截图（参考 ALAS nemu_ipc.py）"""
        import cv2
        import numpy as np
        import concurrent.futures
        try:
            if self._lib is None:
                folder, instance_id = self.find_folder_and_id()
                if folder is None or instance_id is None:
                    if self._logged != "fail":
                        self._logged = "fail"
                        print(">>> [nemu_ipc] ⚠️ 启动失败，未找到 MuMu12 或端口非 16xxx，回退到 ADB 截图")
                        print(">>> [nemu_ipc] ⚠️ 请尝试手动指定 MuMu 模拟器路径")
                    return None

                if not self._check_keep_alive(folder, instance_id):
                    self._logged = "fail"
                    return None

                for rel in ("shell/sdk/external_renderer_ipc.dll", "nx_device/12.0/shell/sdk/external_renderer_ipc.dll"):
                    dll_path = os.path.join(folder, rel)
                    if os.path.isfile(dll_path):
                        self._lib = _load_dll_safe(dll_path)
                        self._lib.nemu_connect.argtypes = [ctypes.c_wchar_p, ctypes.c_int]
                        self._lib.nemu_connect.restype = ctypes.c_int
                        self._lib.nemu_capture_display.argtypes = [
                            ctypes.c_int, ctypes.c_int, ctypes.c_int,
                            ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
                            ctypes.c_void_p
                        ]
                        self._lib.nemu_capture_display.restype = ctypes.c_int
                        self._folder = folder
                        self._nx_device = "nx_device" in rel
                        self._instance_id = instance_id
                        print(f">>> [nemu_ipc] 已加载 DLL，folder={folder!r}，instance_id={instance_id}")
                        break
                if self._lib is None:
                    if self._logged != "fail":
                        self._logged = "fail"
                        print(">>> [nemu_ipc] 未找到 external_renderer_ipc.dll，回退到 ADB 截图")
                    return None
            if self._connect_id == 0:
                folders_to_try = [os.path.abspath(self._folder)]
                if self._nx_device:
                    alt = os.path.join(self._folder, "nx_device", "12.0")
                    if os.path.isdir(alt):
                        folders_to_try.append(os.path.abspath(alt))
                connect_id = 0
                last_stderr = b""
                for folder_path in folders_to_try:
                    connect_id = self._lib.nemu_connect(folder_path, self._instance_id)
                    if connect_id > 0:
                        break
                    last_stderr = self._capture_stderr(
                        lambda f=folder_path: self._lib.nemu_connect(f, self._instance_id)
                    )
                if connect_id == 0:
                    err_msg = last_stderr.decode("utf-8", errors="replace").strip() if last_stderr else ""
                    hint = ""
                    if last_stderr:
                        sb = last_stderr
                        if b"error: 1783" in sb or b"error: 1745" in sb:
                            hint = " MuMu12 版本需 >= 3.8.13，请升级模拟器。"
                        elif b"error: 1722" in sb or b"error: 1726" in sb:
                            hint = " 模拟器进程可能已退出，请重启 MuMu。"
                        elif b"cannot find rpc connection" in sb:
                            hint = " 无法找到 RPC 连接，请确认模拟器已启动且保持前台。"
                    if self._logged != "fail":
                        self._logged = "fail"
                        reason = ">>> [nemu_ipc] nemu_connect 失败，回退到 ADB 截图。"
                        reason += hint or " MuMu 5.x 可能与 nemu_ipc 不兼容。"
                        if err_msg:
                            reason += f" stderr: {err_msg[:200]}"
                        print(reason)
                    return None
                self._connect_id = connect_id
                if self._logged != "ok":
                    self._logged = "ok"
                    print(">>> [nemu_ipc] 已启用，仅 MuMu 可用，速度极快")
            if self._executor is None:
                self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            executor = self._executor
            # 1. 获取分辨率
            w_ptr = ctypes.pointer(ctypes.c_int(0))
            h_ptr = ctypes.pointer(ctypes.c_int(0))
            future = executor.submit(
                self._lib.nemu_capture_display,
                self._connect_id, 0, 0, w_ptr, h_ptr, None
            )
            try:
                ret = future.result(timeout=0.5)
            except concurrent.futures.TimeoutError:
                future.cancel()
                _woa_debug_log("nemu_ipc get_resolution timeout")
                return None

            if ret > 0:
                self._connect_id = 0
                return None
            width, height = w_ptr.contents.value, h_ptr.contents.value
            if width <= 0 or height <= 0 or width > 7680 or height > 4320:
                self._connect_id = 0
                return None

            length = width * height * 4
            buf = (ctypes.c_ubyte * length)()
            future = executor.submit(
                self._lib.nemu_capture_display,
                self._connect_id, 0, length, w_ptr, h_ptr, ctypes.byref(buf)
            )
            try:
                ret = future.result(timeout=1.0)
            except concurrent.futures.TimeoutError:
                future.cancel()
                _woa_debug_log("nemu_ipc screenshot timeout")
                self._connect_id = 0
                return None

            if ret > 0:
                self._connect_id = 0
                return None
            arr = np.ctypeslib.as_array(buf).reshape((height, width, 4)).copy()
            fmt_env = os.environ.get("NEMU_IPC_PIXEL_FORMAT", "auto").lower()
            if fmt_env in ("rgba", "bgra"):
                pixel_fmt = fmt_env
            elif fmt_env == "auto" and self._pixel_format is not None:
                pixel_fmt = self._pixel_format
            elif fmt_env == "auto":
                pixel_fmt = self._auto_detect_format(arr, height, width)
            else:
                pixel_fmt = "rgba"
            if pixel_fmt == "bgra":
                img = cv2.cvtColor(arr, cv2.COLOR_BGRA2BGR)
            else:
                img = cv2.cvtColor(arr, cv2.COLOR_RGBA2BGR)
            do_flip = os.environ.get("NEMU_IPC_FLIP", "1") != "0"
            if do_flip:
                img = cv2.flip(img, 0)
            if NEMU_IPC_DEBUG:
                self._debug_save(img, arr, width, height, pixel_fmt, do_flip)
            return img
        except Exception as e:
            if self._logged != "fail":
                self._logged = "fail"
                print(f">>> [nemu_ipc] 异常: {e}，回退到 ADB 截图")
            return None

    def close(self):
        """清理资源"""
        if self._executor is not None:
            try:
                self._executor.shutdown(wait=False)
            except Exception:
                pass
            self._executor = None
        self._connect_id = 0
        self._lib = None
