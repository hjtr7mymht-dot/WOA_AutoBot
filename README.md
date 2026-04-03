# WOA AutoBot

> 声明：此脚本完全免费。若你通过付费渠道获得，请立即退款并举报。
> 官方交流与反馈：QQ群 1067076460

WOA AutoBot 是一款面向 World of Airports 的 Windows 自动化辅助工具，目标是减少重复点击、提高挂机稳定性，并保留足够的可配置能力，方便不同模拟器和不同机场节奏下使用。

## 项目说明

- 本项目为二创重置项目，原项目链接为 https://github.com/nj-yzf/WOA_AutoBot
- 当前官方仓库为 https://github.com/hjtr7mymht-dot/WOA_AutoBot
- 项目开发过程中，模拟器连接与控制逻辑参考了 https://github.com/LmeSzinc/AzurLaneAutoScript 的部分设计思路

## 软件功能

- 自动扫描并连接安卓模拟器设备
- 支持 ADB 与 uiautomator2 两种触控方式
- 支持 ADB、nemu_ipc、uiautomator2、DroidCast_raw 多种截图方案
- 自动处理待机位、地勤、除冰、维修、进近、滑行、起飞等常见流程
- 自动领取地勤、自动购买车辆、自动延时塔台、自动调筛选
- 支持随机任务选择、随机思考时间、随机滑动耗时等防检测配置
- 支持方案自检与自动回退到可用的触控/截图组合
- 支持防卡死多次触发后的自动停机保护
- 支持紧凑小窗模式与多开模式
- 支持按实例隔离配置，多个窗口互不覆盖配置文件

## 最近更新

- 在线验证新增自动更新能力：打包版检测到 GitHub 仓库存在新版本且 version.json 提供更新包地址时，会自动下载 zip、退出当前程序并完成覆盖更新后重启
- 版本统一为 1.0.3
- 补充与官方构建一致的打包方法说明：使用仓库内 WOA_AutoBot.spec，通过 PyInstaller clean 构建，输出到 dist 目录
- 修复“延误飞机贿赂”在部分场景下可能二次点击导致贿赂未生效却继续推出的问题：现在改为单次点击后仅做状态校验，未确认激活时不再执行结束服务
- 防卡死机制新增“多次触发自动停止脚本”保护，避免异常界面下反复自救导致长时间空转
- 主界面窗口继续扩大到更宽更高的默认尺寸，尽量做到首屏完整显示，不需要再手动拖拽边框
- 挂机节奏区新增“运行与防检测快速开关”，常用开关可直接在主界面启停，时间参数仍保留在高级设置中调整
- 高级设置保留双列布局，去掉分页内滚轮滚动，避免误滚动
- 新增多开模式按钮，可直接拉起新的独立实例窗口
- 移除 minitouch 用户入口，统一保留更稳定的 ADB 与 uiautomator2 方案
- 增加官方仓库在线验证、多源回退与国内网络说明
- 在线验证已调整为“官方打包版严格模式、源码模式社区友好”

## 在线验证与社区二创说明

当前在线验证策略分为两种模式：

- 官方打包版：采用严格模式。首次使用会执行在线验证；后续仅在发现关键校验模块缺失时再次触发，并拒绝继续执行关键操作。
- 源码运行模式：默认不启用强制阻断，仅保留手动在线验证入口，不会因为在线验证机制阻碍开源社区学习、调试、修改和二创。

这意味着：

- 开源社区直接运行源码，不会被强制在线验证卡住
- 社区二创在保留源码形态时，不会被官方在线验证逻辑强制阻断
- 如果社区自行打包发布，可按自己的发布策略调整验证逻辑与目标仓库

## 自动更新说明

- 自动更新仅对打包版生效，源码运行模式默认不会自动覆盖当前工作区。
- 在线验证命中新版本后，如果仓库根目录的 [version.json](version.json) 提供了可下载的更新包地址，程序会自动下载更新包并在退出后自动替换当前目录文件。
- 当前默认更新包地址建议指向 GitHub Releases 中的 `WOA_AutoBot.zip`，这样更新包结构与本地 dist 产物保持一致。

要让自动更新正常工作，需要同时满足：

- 仓库中存在 [version.json](version.json)
- `version.json` 中的 `version` 高于当前本地版本
- `version.json` 中的 `package_urls` 能下载到完整的打包 zip
- zip 内部应包含和 [dist/WOA_AutoBot](dist/WOA_AutoBot) 相同的目录结构，至少要有 `WOA_AutoBot.exe` 和 `_internal`

推荐发布流程：

1. 本地更新版本号与代码。
2. 重新打包生成 [dist/WOA_AutoBot.zip](dist/WOA_AutoBot.zip)。
3. 将 zip 上传到 GitHub Releases，例如 `v1.0.3`。
4. 更新仓库内 [version.json](version.json) 的 `version` 和 `package_urls`。
5. 推送仓库后，旧版打包程序在在线验证时就会检测并自动更新。

标准化发布与发布说明模板见：[docs/GITHUB_RELEASE_PLAYBOOK.md](docs/GITHUB_RELEASE_PLAYBOOK.md)

## 多开模式说明

- 主界面提供“多开模式”按钮，点击后会启动新的独立实例窗口
- 当前默认最多支持 3 个实例同时运行
- 每个实例会使用独立配置文件，例如 config.json、config_2.json、config_3.json
- 多开时建议每个实例分别绑定不同模拟器窗口或不同设备端口

## 环境准备

1. 操作系统：Windows 10 或 Windows 11
2. 模拟器：推荐 MuMu 12
3. 游戏语言：必须为简体中文
4. 分辨率：建议横屏，脚本会自动适配常见横屏分辨率
5. 网络：官方在线验证默认按 GitHub Raw -> jsDelivr -> ghproxy 顺序回退

## 快速开始

1. 启动模拟器并进入机场主界面
2. 运行程序，点击智能扫描选择设备
3. 必要时进入高级设置调整触控方式、截图方式和防检测参数
4. 点击启动脚本开始运行
5. 如需同时挂多个实例，点击多开模式按钮再配置第二个窗口

## 打包说明

项目当前使用 PyInstaller 打包，仓库内包含 WOA_AutoBot.spec。

我采用的打包方式：

- 使用当前项目虚拟环境中的 Python
- 使用仓库根目录下的 [WOA_AutoBot.spec](WOA_AutoBot.spec)
- 执行 clean 构建，避免旧缓存影响结果
- 输出目录为 [dist](dist)
- EXE 版本信息来自 [version_info.txt](version_info.txt)

与我本次相同效果的打包步骤：

1. 进入项目根目录。
2. 激活虚拟环境，或直接使用虚拟环境解释器。
3. 执行下面这条命令：

```powershell
c:/Users/wsnbb/Desktop/WOA_AutoBot_By.RAY_/.venv/Scripts/python.exe -m PyInstaller -y --clean WOA_AutoBot.spec
```

如果你已经先激活了 `.venv`，也可以用这条等价命令：

```powershell
python -m PyInstaller -y --clean WOA_AutoBot.spec
```

打包完成后，产物位置与我这次相同：

- [dist/WOA_AutoBot](dist/WOA_AutoBot)
- [dist/WOA_AutoBot/WOA_AutoBot.exe](dist/WOA_AutoBot/WOA_AutoBot.exe)
- [dist/WOA_AutoBot.zip](dist/WOA_AutoBot.zip)

想要打出和我一致的效果，需要保持以下条件一致：

- 使用仓库自带的 [WOA_AutoBot.spec](WOA_AutoBot.spec)，不要临时改入口和 datas。
- 保持 [version_info.txt](version_info.txt) 中的版本号与程序版本一致。
- 构建前不要删掉 `icon`、`assets`、`adb_tools`、`platform-tools`、`config.json`，这些都已在 spec 中声明为打包资源。
- 尽量使用项目 `.venv` 环境中的依赖版本构建，避免系统 Python 依赖不一致。

## 使用建议

- 优先使用 MuMu 模拟器与 nemu_ipc 截图方案获取更好的速度
- 若点击异常，优先尝试切换 ADB 或 uiautomator2 触控方式
- 若在线验证失败，请先查看程序内的国内网络方案按钮说明
- 多开场景下请避免多个实例同时操作同一个模拟器窗口

## 免责声明

- 本项目仅供学习交流使用
- 使用自动化工具存在封禁、误点和资源损失风险，请自行承担后果
- 若遇到问题，请优先在官方反馈渠道或仓库 Issues 中反馈
