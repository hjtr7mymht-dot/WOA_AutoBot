#!/bin/bash
# WOA AutoBot macOS DMG 构建脚本 v3
# 使用当前 venv (.venv-1) + ditto 清理 + 手动 .app + DMG
set -e
cd "$(dirname "$0")"

PYINST=.venv-1/bin/pyinstaller
PY=.venv-1/bin/python
APP_NAME="WOA_AutoBot"
DMG_VOL="WOA AutoBot v1.5.0"

echo ">>> [1/6] PyInstaller 打包..."
rm -rf build dist
$PYINST --clean -y --onedir --windowed --name $APP_NAME \
  --add-data "assets:assets" \
  --add-data "icon:icon" \
  --add-data "adb_tools:adb_tools" \
  --add-data "platform-tools:platform-tools" \
  --add-data "config.json:." \
  --add-data "version.json:." \
  --add-data "GUIDE.md:." \
  --add-data "ANNOUNCEMENT.md:." \
  --add-data "docs:docs" \
  --add-data "icon/digits:icon/digits" \
  --add-data "icon/digits/global:icon/digits/global" \
  --add-data "icon/digits/task:icon/digits/task" \
  --hidden-import tkinter \
  --hidden-import tkinter.scrolledtext \
  --hidden-import tkinter.filedialog \
  --hidden-import tkinter.messagebox \
  --hidden-import tkinter.ttk \
  --hidden-import tkinter.constants \
  --hidden-import ttkbootstrap \
  --hidden-import ttkbootstrap.constants \
  --hidden-import ttkbootstrap.style \
  --hidden-import ttkbootstrap.widgets \
  --hidden-import ttkbootstrap.themes \
  --hidden-import PIL \
  --hidden-import PIL.Image \
  --hidden-import PIL.ImageTk \
  --hidden-import PIL.ImageDraw \
  --hidden-import PIL.ImageFont \
  --hidden-import PIL.ImageFilter \
  --hidden-import PIL.ImageOps \
  --hidden-import PIL._tkinter_finder \
  --hidden-import PIL._imagingtk \
  --hidden-import cv2 \
  --hidden-import numpy \
  --hidden-import orjson \
  --hidden-import cachetools \
  --hidden-import uiautomator2 \
  --hidden-import uiautomator2._funcs \
  --hidden-import adbutils \
  --hidden-import adbutils._adb \
  --hidden-import lxml \
  --hidden-import lxml.etree \
  --hidden-import requests \
  --hidden-import urllib3 \
  --hidden-import pystray \
  --hidden-import certifi \
  --hidden-import ssl \
  --hidden-import adb_controller \
  --hidden-import simple_ocr \
  --hidden-import gui_launcher \
  --hidden-import main_adb \
  --hidden-import nemu_ipc \
  --hidden-import platform_utils \
  --hidden-import woa_debug \
  --hidden-import emulator_discovery \
  --hidden-import core \
  --hidden-import core.constants \
  --hidden-import core.platform \
  --hidden-import core.resources \
  --hidden-import core.debug \
  --hidden-import bot \
  --hidden-import bot.config \
  --hidden-import bot.tower \
  --hidden-import bot.filter \
  --collect-all tkinter \
  --collect-all ttkbootstrap \
  --collect-all certifi \
  gui_launcher.py 2>&1 | tail -3

echo ">>> [2/6] 清理 PyInstaller 自动生成的 .app..."
rm -rf dist/$APP_NAME.app

echo ">>> [3/6] 手动构建 .app..."
APP="dist/$APP_NAME.app"
mkdir -p "$APP/Contents/MacOS"
cp -R dist/$APP_NAME/ "$APP/Contents/MacOS/${APP_NAME}_app/"

# Launcher 启动脚本
cat > "$APP/Contents/MacOS/$APP_NAME" << LAUNCHER
#!/bin/bash
DIR="\$(cd "\$(dirname "\$0")" && pwd)"
exec "\$DIR/${APP_NAME}_app/$APP_NAME" "\$@"
LAUNCHER
chmod +x "$APP/Contents/MacOS/$APP_NAME"
chmod +x "$APP/Contents/MacOS/${APP_NAME}_app/$APP_NAME"

# Info.plist
cat > "$APP/Contents/Info.plist" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleName</key><string>WOA AutoBot</string>
<key>CFBundleDisplayName</key><string>WOA AutoBot</string>
<key>CFBundleIdentifier</key><string>com.woa.autobot</string>
<key>CFBundleVersion</key><string>1.5.0</string>
<key>CFBundleShortVersionString</key><string>1.5.0</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleExecutable</key><string>$APP_NAME</string>
<key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
<key>LSMinimumSystemVersion</key><string>11.0</string>
<key>NSHighResolutionCapable</key><true/>
<key>NSRequiresAquaSystemAppearance</key><false/>
<key>NSPrincipalClass</key><string>NSApplication</string>
<key>NSAppTransportSecurity</key><dict><key>NSAllowsArbitraryLoads</key><true/></dict>
</dict></plist>
PLIST

echo ">>> [4/6] 修复 adb 权限..."
find "$APP" -path "*/adb_tools/adb" -type f -exec chmod +x {} \; 2>/dev/null || true
find "$APP" -path "*/platform-tools/adb" -type f -exec chmod +x {} \; 2>/dev/null || true

echo ">>> [5/6] 清理资源分叉并签名..."
# 用 ditto 剥离资源分叉（解决 macOS 26 codesign "resource fork" 错误）
TMP_APP="/tmp/woa_clean_$$.app"
ditto --norsrc "$APP" "$TMP_APP" 2>/dev/null || true
if [ -d "$TMP_APP" ]; then
    rm -rf "$APP"
    mv "$TMP_APP" "$APP"
fi
xattr -cr "$APP" 2>/dev/null || true
# ad-hoc 签名（失败不阻塞，未签名也可右键打开）
codesign --force --sign - "$APP" 2>/dev/null || echo "   ⚠️ 签名失败（右键仍可打开）"

echo ">>> [6/6] 创建 DMG..."
rm -f dist/${APP_NAME}_macOS.dmg
TMP_DMG=$(mktemp -d)
cp -R "$APP" "$TMP_DMG/"
ln -s /Applications "$TMP_DMG/Applications"
hdiutil create -volname "$DMG_VOL" -srcfolder "$TMP_DMG" -ov -format UDZO -size 800m dist/${APP_NAME}_macOS.dmg 2>&1 | tail -3
rm -rf "$TMP_DMG"

echo ""
echo "═══════════════════════════════════════"
echo "  ✅ 构建完成"
echo "  📦 dist/${APP_NAME}_macOS.dmg"
echo "  📊 $(ls -lh dist/${APP_NAME}_macOS.dmg | awk '{print $5}')"
echo "═══════════════════════════════════════"
echo ""
echo "  使用方式："
echo "    open dist/${APP_NAME}_macOS.dmg"
echo "    拖入「应用程序」→ 右键 → 打开"
echo ""