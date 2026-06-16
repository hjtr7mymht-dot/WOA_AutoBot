WOA AutoBot v1.4.0 打包指南
===========================

环境要求
--------
- Python 3.14+
- Windows: PowerShell 5.1+, 虚拟环境 `.venv`
- macOS: bash, `uv` 包管理器

Windows 打包
-----------
```powershell
# 使用虚拟环境中的 PyInstaller（推荐）
.venv\Scripts\python.exe -m PyInstaller -y --clean WOA_AutoBot.spec

# 打包结果
#   dist/WOA_AutoBot/          （完整分发目录，~290 MB）
#   dist/WOA_AutoBot/WOA_AutoBot.exe  （主程序，~8 MB）
#   build/WOA_AutoBot/         （构建缓存，可删除）
```
- 入口脚本: `gui_launcher.py`（spec 中指定）
- `core/` 包通过 import 分析自动收集，无需手动列在 datas
- `bot/` 包当前未被入口脚本导入，不会打包（其功能已内联至 main_adb.py）
- 已知无害警告: `Hidden import "tzdata" not found!"` — zoneinfo 的可选依赖，不影响运行

macOS DMG 打包
--------------
```bash
# 推荐使用 DMG 构建脚本一键完成
bash build_dmg.sh

# 或手动从源码打包
uv run pyinstaller -y --clean WOA_AutoBot_mac.spec
# 清理资源分叉 + 重新签名
find dist/WOA_AutoBot.app -name "._*" -delete
ditto --norsrc dist/WOA_AutoBot.app /tmp/WOA_clean.app
rm -rf dist/WOA_AutoBot.app
mv /tmp/WOA_clean.app dist/WOA_AutoBot.app
xattr -rc dist/WOA_AutoBot.app
codesign --remove-signature dist/WOA_AutoBot.app 2>/dev/null
codesign --deep --force --sign - dist/WOA_AutoBot.app
# 制作 DMG
hdiutil create -volname "WOA AutoBot v1.4.0" \
  -srcfolder dist/WOA_AutoBot.app -ov -format UDZO \
  dist/WOA_AutoBot_macOS.dmg
```

spec 文件说明
-------------
- `WOA_AutoBot.spec` — Windows 打包，COLLECT 模式输出文件夹
- `WOA_AutoBot_mac.spec` — macOS 打包，BUNDLE 模式输出 .app
- datas 显式包含: `assets/`, `icon/`, `adb_tools/`, `platform-tools/`, `config.json`, `version.json`
- hiddenimports: `tkinter`, `PIL._tkinter_finder`, `certifi`, `ssl`
- 二进制依赖自动收集: numpy, cv2 (opencv), lxml, PIL, adbutils, uiautomator2

注意
----
- Windows 版需要 `adb.exe` 在系统 PATH 或连接 MuMu 模拟器自动发现
- `adb_tools/` 与 `platform-tools/` 目录中的二进制为 macOS 通用格式（Mach-O），Windows 打包时一同复制但不会使用
