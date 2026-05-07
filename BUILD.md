WOA AutoBot 打包指南
====================

macOS 打包 (已在 Mac 上完成)
-----------------------------
结果位于 dist/ 目录:
  - WOA_AutoBot.app      (217 MB, 可直接运行)
  - WOA_AutoBot_macOS.zip (93 MB, 压缩后用于分享)

如需重新打包:
  cd WOA_AutoBot
  uv run pyinstaller -y --clean WOA_AutoBot_mac.spec
  ditto -c -k --sequesterRsrc --keepParent dist/WOA_AutoBot.app dist/WOA_AutoBot_macOS.zip


Windows 打包 (需在 Windows 上执行)
-----------------------------------
1. 安装 Python 3.10+
2. 安装依赖: pip install -r requirements.txt
3. 安装 PyInstaller: pip install pyinstaller
4. 执行打包: pyinstaller -y --clean WOA_AutoBot.spec
5. 输出: dist/WOA_AutoBot/WOA_AutoBot.exe
6. 可打包为 ZIP 分享给其他用户
