# WOA AutoBot

> 声明：此脚本完全免费。若你通过付费渠道获得，请立即退款并举报。
> 官方交流与反馈：QQ群 1067076460
> 作者网站：https://hjtr7mymht-dot.github.io/   （个人博客与最新动态）

WOA AutoBot 是一款面向 World of Airports 的自动化辅助工具，目标是减少重复点击、提高挂机稳定性，并保留足够的可配置能力，方便不同模拟器和不同机场节奏下使用。
**现已完整支持 macOS（Apple Silicon / Intel）与 Windows 双平台。**

## 项目说明

- 本项目为二创重置项目，原项目链接为 https://github.com/nj-yzf/WOA_AutoBot
- 当前官方仓库为 https://github.com/hjtr7mymht-dot/WOA_AutoBot
- 作者个人网站：https://hjtr7mymht-dot.github.io/
- 路线查找器：https://github.com/hjtr7mymht-dot/ARPA-FOR-WOA   （自动航路规划工具）
- 项目开发过程中，模拟器连接与控制逻辑参考了 https://github.com/LmeSzinc/AzurLaneAutoScript 的部分设计思路

## 软件功能

- 自动扫描并连接安卓模拟器设备（Windows / macOS）
- 支持 ADB 与 uiautomator2 两种触控方式
- 支持 ADB、nemu_ipc（仅 Windows）、uiautomator2、DroidCast_raw 多种截图方案
- 自动处理待机位、地勤、除冰、维修、进近、滑行、起飞等常见流程
- 自动领取地勤、自动购买车辆、自动延时塔台、自动调筛选
- 支持随机任务选择、随机思考时间、随机滑动耗时等防检测配置
- 支持按类别轮换处理飞机（喜爱、机队、其他玩家、活动飞机等，多选）
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

### v1.2.9 (2026-05-29)
- 📂 **新增右侧类别栏处理功能**：用户可自由选择处理哪些类别的飞机（喜爱/合约、机队、其他玩家、活动飞机），支持多选和按时间间隔自动轮换切换
- 🔄 **类别轮换处理**：每个已选类别处理指定时间后自动切换到下一个，右侧类别栏按钮自动切换

### v1.2.8 (2026-05-24)
- 🗺️ **新增路线查找器入口**：软件添加"路线查找"快捷按钮，直达 ARPA-FOR-WOA 自动航路规划工具
- 🔗 **帮助文档补充**：声明部分添加路线查找器仓库链接



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
