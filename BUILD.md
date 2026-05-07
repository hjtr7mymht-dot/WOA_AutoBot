WOA AutoBot v1.2.0 打包指南
===========================

macOS DMG 打包 (在当前 Mac 上已完成)
------------------------------------
打包结果位于 dist/ 目录:
  - WOA_AutoBot_macOS.dmg (双击即可安装，推荐分发格式)

⭐ 推荐使用 DMG 构建脚本一键完成:
  bash build_dmg.sh

如需手动从源码重新打包:
  cd WOA_AutoBot
  uv run pyinstaller -y --clean WOA_AutoBot_mac.spec
  # 清理资源分叉（否则 codesign 失败）
  find dist/WOA_AutoBot.app -name "._*" -delete
  ditto --norsrc dist/WOA_AutoBot.app /tmp/WOA_clean.app
  rm -rf dist/WOA_AutoBot.app
  mv /tmp/WOA_clean.app dist/WOA_AutoBot.app
  xattr -rc dist/WOA_AutoBot.app
  codesign --remove-signature dist/WOA_AutoBot.app 2>/dev/null
  codesign --deep --force --sign - dist/WOA_AutoBot.app
  # 制作 DMG
  ditto -c -k --sequesterRsrc --keepParent dist/WOA_AutoBot.app dist/WOA_AutoBot_macOS.zip

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
