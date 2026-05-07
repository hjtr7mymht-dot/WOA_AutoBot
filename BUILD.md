WOA AutoBot v1.2.0 打包指南
===========================

macOS 打包 (在当前 Mac 上已完成)
---------------------------------
打包结果位于 dist/ 目录:
  - WOA_AutoBot.app      (可直接双击运行, 217 MB)
  - WOA_AutoBot_macOS.zip (压缩后用于分享, 93 MB)

如需从源码重新打包:
  cd WOA_AutoBot
  uv run pyinstaller -y --clean WOA_AutoBot_mac.spec
  xattr -rc dist/WOA_AutoBot.app
  codesign --remove-signature dist/WOA_AutoBot.app
  codesign --deep --force --sign - dist/WOA_AutoBot.app
  ditto -c -k --sequesterRsrc --keepParent dist/WOA_AutoBot.app dist/WOA_AutoBot_macOS.zip

注意: 打包需使用 uv 管理的虚拟环境 (Python 3.14)。
系统自带 Python 可能缺少依赖。


Windows 打包 (需在 Windows 上执行)
-----------------------------------
1. 安装 Python 3.10+
2. 安装依赖: pip install -r requirements.txt
3. 安装 PyInstaller: pip install pyinstaller
4. 执行打包: pyinstaller -y --clean WOA_AutoBot.spec
5. 输出: dist/WOA_AutoBot/WOA_AutoBot.exe
6. 可用 ZIP 压缩后分享给其他用户

注意: Windows 版需要有 adb.exe 在 adb_tools/ 和 platform-tools/ 目录中。


用户使用说明
-----------
macOS 用户:
  1. 解压 WOA_AutoBot_macOS.zip
  2. 将 WOA_AutoBot.app 拖入「应用程序」文件夹
  3. 首次打开如提示「未识别的开发者」：
     系统设置 → 隐私与安全性 → 仍要打开
  4. 需要连接安卓模拟器或真机 (通过 adb)

Windows 用户:
  1. 解压后运行 WOA_AutoBot.exe
  2. 需要连接安卓模拟器或真机 (通过 adb)
