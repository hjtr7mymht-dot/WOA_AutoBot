# WOA AutoBot

> 声明：此脚本完全免费。若你通过付费渠道获得，请立即退款并举报。
> 官方交流与反馈：QQ群 1067076460

WOA AutoBot 是一款面向 World of Airports 的自动化辅助工具，目标是减少重复点击、提高挂机稳定性，并保留足够的可配置能力，方便不同模拟器和不同机场节奏下使用。
**现已完整支持 macOS（Apple Silicon / Intel）与 Windows 双平台。**

## 项目说明

- 本项目为二创重置项目，原项目链接为 https://github.com/nj-yzf/WOA_AutoBot
- 当前官方仓库为 https://github.com/hjtr7mymht-dot/WOA_AutoBot
- 项目开发过程中，模拟器连接与控制逻辑参考了 https://github.com/LmeSzinc/AzurLaneAutoScript 的部分设计思路

## 软件功能

- 自动扫描并连接安卓模拟器设备（Windows / macOS）
- 支持 ADB 与 uiautomator2 两种触控方式
- 支持 ADB、nemu_ipc（仅 Windows）、uiautomator2、DroidCast_raw 多种截图方案
- 自动处理待机位、地勤、除冰、维修、进近、滑行、起飞等常见流程
- 自动领取地勤、自动购买车辆、自动延时塔台、自动调筛选
- 支持随机任务选择、随机思考时间、随机滑动耗时等防检测配置
- 支持方案自检与自动回退到可用的触控/截图组合
- 支持防卡死多次触发后的自动停机保护
- 支持同帧多图批匹配优化，降低高频识别路径 CPU 峰值
- 支持紧凑小窗模式与多开模式
- 支持按实例隔离配置，多个窗口互不覆盖配置文件

## 平台支持

| 平台 | 状态 | 说明 |
|------|------|------|
| **Windows 10/11** | ✅ 完整支持 | 推荐 MuMu12 模拟器，支持 nemu_ipc 高速截图 |
| **macOS (Intel)** | ✅ 完整支持 | 通过 `uv run python gui_launcher.py` 运行，或使用打包的 .app/.dmg |
| **macOS (Apple Silicon)** | ✅ 完整支持 | 原生 arm64 支持，已测试 M 系列芯片 |
| **Linux** | ⚠️ 基础兼容 | ADB 连接可用，部分截图方案需手动配置 |

### macOS 注意事项
- 需要安装 [Android Platform Tools](https://developer.android.com/studio/releases/platform-tools) 或将项目内 `adb_tools/adb` 加入 PATH
- nemu_ipc 截图方案为 MuMu 模拟器专属（仅 Windows），macOS 上自动回退到 ADB 截图
- 推荐使用 uiautomator2 截图方案获得更优性能
- 打包命令：`uv run pyinstaller -y --clean WOA_AutoBot_mac.spec`

## 快速开始

### macOS 用户
1. 下载 `WOA_AutoBot_macOS.dmg`，双击打开
2. 将 `WOA_AutoBot.app` 拖入 Applications 文件夹
3. 首次打开如提示"未识别的开发者"：**右键 → 打开 → 仍要打开**
4. 连接安卓模拟器或真机（需开启 ADB 调试）
5. 在设备下拉框选择目标设备，点击 **启动**

### Windows 用户
1. 解压后运行 `WOA_AutoBot.exe`
2. 连接 MuMu / 蓝蝶 / 雷电等安卓模拟器
3. 在设备下拉框选择目标设备，点击 **启动**

### 源码运行
```bash
# macOS/Linux
uv run python gui_launcher.py

# Windows
python gui_launcher.py
```

## 最近更新

### v1.2.2 (2026-05-09)
- 🧹 **全面代码重构**：核心模块解耦为 `core/`（跨平台工具/资源/常量）与 `bot/`（配置/塔台/筛选 Mixin）包
- 🔁 **消除重复代码**：`get_resource_path`、`FEATURE_GUARD_TOKEN`、字体常量等从多处定义统一到 `core/`
- 🪦 **清理死依赖**：移除未使用的 `pystray`、`PyAutoGUI`、`pyperclip` 依赖
- 🍎 **跨平台 UI 修复**：截图方案下拉框 macOS 自动移除不可用的 `nemu_ipc`；ADB 浏览对话框跨平台文件过滤器
- 🔧 **截图默认值智能切换**：Windows 默认 `nemu_ipc`，macOS 默认 `uiautomator2`
- 🧽 **清理孤立文件**：删除旧版 `WOA_AutoBot_v1.0.5.spec`、过期配置锁文件、中间构建缓存
- 📦 **打包配置增强**：spec 补充完整 `hiddenimports`，添加 `core/` 与 `bot/` 数据目录

### v1.2.1 (2026-05-08)
- 🗼 **塔台延时全面优化**：全开时一键全部续费，部分开启时逐控制器精准续费，不再逐轮检查
- ✅ **修复塔台延时确认失败**：重写弹窗确认逻辑，优先匹配单控制器/全部延时不混淆，增加截屏验证机制
- 🔌 **完全离线模式**：删除强制在线验证，所有功能在无网络时完整可用，不再卡"校验中"或阻断操作
- 🔘 **默认筛选模式修正**：状态异常时默认切至"全部勾选"而非"仅停机位"
- 🍎 **macOS 打包修复**：修复 SSL 证书加载、只读文件系统写入失败、GIL 线程崩溃等打包问题
- 📦 **提供 DMG 分发**：macOS 以 .dmg 镜像格式分发，双击即可安装

### v1.2.0 (2026-05-07)
- 🍎 **macOS 完整兼容**：原生支持 Apple Silicon & Intel，提供 .app 打包分发
- 🖥️ **UI 全面重构**：消灭大面积空白，所有开关集中在四个功能标签页
- 🚗 **修复车辆不足卡死**：未开启购买或绿币不足时不再卡任务
- 🗼 **塔台关闭筛选修复**：塔台关闭后不再错误锁定"仅停机位"
- 🔄 **小退后自动重检塔台**
- 📦 **源码打包分发**

## 在线验证与社区二创说明

当前在线验证策略分为两种模式：

- 官方打包版：采用严格模式。首次使用会执行在线验证；后续仅在发现关键校验模块缺失时再次触发，并拒绝继续执行关键操作。
- 源码运行模式：默认不启用强制阻断，仅保留手动在线验证入口，不会因为在线验证机制阻碍开源社区学习、调试、修改和二创。

这意味着：

- 开源社区直接运行源码，不会被强制在线验证卡住
- 社区二创在保留源码形态时，不会被官方在线验证逻辑强制阻断
- 如果社区自行打包发布，可按自己的发布策略调整验证逻辑与目标仓库

官方打包版额外完整性说明：

- 严格模式下会校验关键模块中的功能守卫标记，以及资助入口与资源目录是否存在。
- 若检测到删除或篡改，会触发在线校验阻断，避免发布包被静默改造后继续分发。

## 联网检测更新说明

- 程序每次启动都会自动进行一次联网版本检测（GitHub Raw -> jsDelivr -> ghproxy）。
- 检测到新版本时会直接弹窗提示，不会自动下载、覆盖或重启。
- 运行过程中不再执行自动更新逻辑，避免覆盖失败或误替换带来的风险。

## 自愿资助

如果你觉得这个项目有帮助，欢迎自愿资助作者买杯咖啡 ☕ 完全自愿，无任何功能限制。

<img width="320" height="320" alt="3cffd32d561e0f4c708243f713e042d2" src="https://github.com/user-attachments/assets/a6408d27-bade-4deb-875a-1a5017f3aeab" /> <img width="320" height="320" alt="5bb49dee87f012d69790f2a112406cbf" src="https://github.com/user-attachments/assets/44ff6717-300e-43d5-b6b5-faa332e6bcfd" />
