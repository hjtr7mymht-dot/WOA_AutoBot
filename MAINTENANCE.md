WOA AutoBot v2.0 维护手册
========================

> 适用版本：v2.0+（分层架构）。v1.x 维护请参考项目根目录 BUILD.md。

## 一、架构不可撼动的基础（Architectural Invariants）

以下特性已固化为代码，**任何后续 PR 不得破坏**：

### 1.1 异常分类体系

```
ADBError (ADB_000)              # 所有 ADB 异常的基类
├── ADBConnectionError (ADB_001) # 设备未连接/未授权 → GUI 弹窗提示
├── ADBDisconnectedError (ADB_002) # 运行时断连 → 自动重连
├── ADBCommandError (ADB_003)    # 单条命令失败 → 记录日志跳过
├── ScreenshotError (ADB_004)    # 截图失败 → 重试3次→FatalError
├── MatchTimeoutError (ADB_005)  # 匹配超时 → 跳过当前任务
└── FatalError (ADB_999)         # 致命错误 → 停止Bot
```

**规则**：新增异常必须继承 `ADBError` 并定义唯一的 `error_code`。

### 1.2 ADB 控制器核心特性

| 特性 | 位置 | 说明 |
|------|------|------|
| `asyncio.Lock` 串行化 | `_cmd_lock` | 同一时间仅一个 adb 命令执行 |
| 心跳检测 | `_heartbeat()` | 每30s发 `echo ping`，断连自动检测 |
| 异步上下文管理 | `__aenter__/__aexit__` | `async with ADBController(...) as adb:` |
| 截图重试 | `SCREENSHOT_MAX_RETRIES=3` | 失败自动重试，指数退避 |
| 分辨率缓存 | `get_resolution()` | 一次查询，全程复用 |
| 锁文件清理 | `_lock_file` | close() 自动删除 instance_*.lock |
| 安全：无 shell=True | `_run_adb()` | 所有 subprocess 使用列表传参 |

### 1.3 CV 匹配器核心特性

| 特性 | 位置 | 说明 |
|------|------|------|
| LRU 模板缓存 | `LRUTemplateCache(64)` | 防止长期运行内存泄漏 |
| 强制 ROI 搜索 | `match()` | 必须传入 roi 参数，禁止全屏搜索 |
| 双环采样器 | `RingSampler` | 外环(16px)+内环(6px)+中间环(11px) |
| 四层降级策略 | `match_button_state()` | 精确→多尺度→低对比度→像素回退 |
| 自适应亮度校准 | `_calibration` | 高置信度时自动学习 on/off 亮度 |
| 性能基准 | `benchmark()` | 统计单帧匹配耗时 |
| 可选 SQDIFF | `MatchMethod.SQDIFF` | 比 CCOEFF 快 ~30% |

### 1.4 分辨率适配

- **16:9 设备**：直接拉伸到 1600×900
- **非16:9 设备**（手机全面屏等）：中心等比缩放 + 黑边填充
- 归一化坐标 (0.0~1.0) 内部统一，含偏移补偿

## 二、性能故障排查（Performance Troubleshooting）

### 症状：单帧处理 > 1.0s

```
排查步骤：
1. 检查截图方式
   → Windows: 确认使用 nemu_ipc（MuMu模拟器）而非 ADB screencap
   → 日志中查找 "[ADB]" 确认截图耗时

2. 检查模板匹配尺度
   → UI_SCALES = [0.88, 0.92, 0.96, 1.0, 1.04, 1.08, 1.12] (7个尺度)
   → 如超过200ms，可缩减为 [0.94, 1.0, 1.06] (3个尺度)

3. 检查 ROI 大小
   → pending按钮使用 64×64 ROI (margin=32)
   → 其他按钮使用 48×48 ROI (margin=24)
   → ROI越大越慢，但太小会漏匹配

4. 切换匹配方法
   → matcher.match_method = MatchMethod.SQDIFF  # 提速30%
```

### 症状：ADB 频繁断连

```
1. 检查心跳日志：grep "心跳" 查看失败频率
2. 使用 USB 2.0/3.0 直连（避免 USB Hub）
3. 运行 adb kill-server && adb start-server 重置
4. 如使用 MuMu，升级至最新版（12.3+ 修复了 IPC 稳定性）
```

### 症状：低对比度按钮反复切换

```
已自动处理：LOW_CONTRAST_TEMPLATES 中的5个模板
  huoji(22), 2D(31), filter_pending(31), 3D(37), love(38)
这些模板自动降低置信度阈值至 0.35。

如果仍有问题：
1. 检查 icon/ 目录模板是否完整
2. 确认设备分辨率与模板分辨率（1600×900）兼容
3. 在 matcher.py 中将对应模板加入 LOW_CONTRAST_TEMPLATES
```

## 三、依赖管理（Dependency Management）

### 3.1 Python 版本锁定

```
当前锁定: Python 3.10.x
升级条件:
  1. 运行 tox 或完整测试套件（16 tests）
  2. 验证所有 typing imports (TypedDict, Protocol, Literal)
  3. 确认 customtkinter / pydantic 兼容

禁止行为:
  - 使用 Python 3.11+ 的 Self, TypeGuard 等新特性
  - 使用 match/case (3.10 支持但不稳定)
```

### 3.2 关键依赖版本

| 包 | 最低版本 | 说明 |
|----|----------|------|
| `opencv-python` | 4.8.0 | 若升级后 DLL 加载失败，回退到此版本 |
| `customtkinter` | 5.2.0 | GUI 框架，向后兼容性较好 |
| `pydantic` | 2.0 | 配置管理，v2 API 与 v1 不兼容 |
| `adbutils` | 2.12.0 | ADB Python 封装 |

### 3.3 OpenCV DLL 故障（Windows 常见）

```
症状: ImportError: DLL load failed while importing cv2
解决:
  1. pip uninstall opencv-python opencv-python-headless
  2. pip install opencv-python==4.8.0.74
  3. 或安装 Visual C++ Redistributable 2015-2022
```

## 四、测试与质量门禁

### 4.1 运行测试

```bash
# 全部测试
python -m unittest discover -s tests -v

# 单个模块
python -m unittest tests.test_adb_controller -v
python -m unittest tests.test_matcher -v
```

### 4.2 合并前检查清单

- [ ] `python -m py_compile` 通过所有 src/*.py
- [ ] `python -m unittest discover -s tests` 全部通过 (16/16)
- [ ] `_arch_verify.py` 检查 23/23 通过
- [ ] GUI 能正常弹出窗口（`python -m src.presentation.gui.app`）
- [ ] 无新增 `time.sleep`（必须用 `await asyncio.sleep`）
- [ ] 无新增 `print()`（必须用 `logger` + `BotSignal`）

## 五、项目结构速查

```
src/
├── domain/models.py              # NormalizedPoint, FilterMode, Airport...
├── domain/tasks/
│   ├── base_task.py              # BaseTask 抽象基类
│   ├── deice_task.py             # 除冰任务 (DeiceRegions dataclass)
│   └── filter_task.py            # 筛选任务 (AircraftCategory Enum)
├── infrastructure/adb/controller.py  # ADBController (asyncio.Lock+心跳)
├── infrastructure/cv/matcher.py      # MultiScaleTemplateMatcher (四层降级)
├── application/config.py             # AppSettings (Pydantic Settings)
├── application/services.py           # BotOrchestrator (指数退避+stats)
├── presentation/gui/app.py           # WOAApp (CustomTkinter + 紧急停止)
tests/
├── test_adb_controller.py        # 6 tests
└── test_matcher.py               # 10 tests
_arch_verify.py                   # 架构核查脚本 (23 checks)
BUILD.md                          # 打包指南
MAINTENANCE.md                    # 本文档
```

## 六、日志与监控

- **GUI 日志**：限制 500 行，超出自动清理旧日志
- **ADB 心跳**：每 30s 自动检测，失败记入 logger
- **统计指标**：任务成功率、连续失败次数、匹配耗时 (ms)
- **错误码**：每个异常携带 `error_code`，GUI 可据此显示不同提示
