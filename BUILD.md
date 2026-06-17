WOA AutoBot v1.4.0 打包指南
===========================

Windows 打包
-----------
```powershell
# 安装 PyInstaller（首次打包需要）
.venv\Scripts\python.exe -m pip install PyInstaller

# 使用虚拟环境中的 PyInstaller 打包
.venv\Scripts\python.exe -m PyInstaller -y --clean WOA_AutoBot.spec

# 打包结果位于 dist/WOA_AutoBot/
# 运行: dist\WOA_AutoBot\WOA_AutoBot.exe
```

macOS DMG 打包
--------------
```bash
# 推荐使用 DMG 构建脚本一键完成
bash build_dmg.sh

# 或手动从源码打包
uv run pyinstaller -y --clean WOA_AutoBot_mac.spec
# 清理资源分叉
find dist/WOA_AutoBot.app -name "._*" -delete
ditto --norsrc dist/WOA_AutoBot.app /tmp/WOA_clean.app
rm -rf dist/WOA_AutoBot.app
mv /tmp/WOA_clean.app dist/WOA_AutoBot.app
xattr -rc dist/WOA_AutoBot.app
codesign --remove-signature dist/WOA_AutoBot.app 2>/dev/null
codesign --deep --force --sign - dist/WOA_AutoBot.app
# 制作 DMG
hdiutil create -volname "WOA AutoBot v1.4.0" -srcfolder dist/WOA_AutoBot.app -ov -format UDZO dist/WOA_AutoBot_macOS.dmg
```

注意
----
- Windows 版需要 `adb.exe` 在系统 PATH 或连接 MuMu 模拟器自动发现
- `adb_tools/` 与 `platform-tools/` 目录中的二进制为 macOS 通用格式，打包时会随 spec 一同复制
- `core/` 和 `bot/` 是纯 Python 包，PyInstaller 自动分析导入并编译进 exe；`icon/`、`assets/`、`config.json`、`version.json` 列为 spec datas 随包复制
