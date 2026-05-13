#!/bin/bash
# WOA AutoBot macOS DMG 构建脚本 v3
# 使用 Python 3.12 (venv-312-fresh) + ditto 清理 + 手动 .app + DMG
set -e
cd "$(dirname "$0")"

PYINST=.venv-312-fresh/bin/pyinstaller
PY=.venv-312-fresh/bin/python
APP_NAME="WOA_AutoBot"
DMG_VOL="WOA AutoBot v1.2.6"

echo ">>> [1/6] PyInstaller 打包..."
rm -rf build dist
$PYINST --clean -y --onedir --windowed --name $APP_NAME \
  --add-data "assets:assets" \
  --add-data "icon:icon" \
  --add-data "adb_tools:adb_tools" \
  --add-data "platform-tools:platform-tools" \
  --add-data "config.json:." \
  --add-data "version.json:." \
  --hidden-import tkinter \
  --hidden-import PIL._tkinter_finder \
  --hidden-import certifi \
  --hidden-import ssl \
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
<key>CFBundleVersion</key><string>1.2.3</string>
<key>CFBundleShortVersionString</key><string>1.2.3</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleExecutable</key><string>$APP_NAME</string>
<key>LSMinimumSystemVersion</key><string>11.0</string>
<key>NSHighResolutionCapable</key><true/>
<key>NSRequiresAquaSystemAppearance</key><false/>
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