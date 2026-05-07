#!/bin/bash
# WOA AutoBot macOS DMG 构建脚本 v2
# 使用 Python 3.12 + dylib 修复 + .app + DMG
cd "$(dirname "$0")"
source .venv-312/bin/activate
echo ">>> [1] Build..."
rm -rf build dist
pyinstaller --onedir --windowed --name WOA_AutoBot --add-data "assets:assets" --add-data "icon:icon" --add-data "adb_tools:adb_tools" --add-data "platform-tools:platform-tools" --add-data "config.json:." --add-data "version.json:." --hidden-import tkinter --hidden-import PIL._tkinter_finder --hidden-import certifi --hidden-import ssl --collect-all certifi gui_launcher.py 2>&1 | tail -3
echo ">>> [2] Fix dylibs..."
INT="dist/WOA_AutoBot/_internal"
cp "$INT/libtiff.6.dylib" "$INT/PIL/libtiff.6.dylib" 2>/dev/null || true
echo ">>> [3] Create .app..."
rm -rf dist/WOA_AutoBot.app && mkdir -p dist/WOA_AutoBot.app/Contents/MacOS && cp -R dist/WOA_AutoBot/ dist/WOA_AutoBot.app/Contents/MacOS/WOA_AutoBot_app/
cp dist/WOA_AutoBot.app/Contents/MacOS/WOA_AutoBot_app/_internal/libtiff.6.dylib dist/WOA_AutoBot.app/Contents/MacOS/WOA_AutoBot_app/_internal/PIL/ 2>/dev/null || true
cat > dist/WOA_AutoBot.app/Contents/MacOS/WOA_AutoBot << 'EOF'
#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$DIR/WOA_AutoBot_app/WOA_AutoBot" "$@"
EOF
chmod +x dist/WOA_AutoBot.app/Contents/MacOS/WOA_AutoBot
cat > dist/WOA_AutoBot.app/Contents/Info.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleName</key><string>WOA AutoBot</string>
<key>CFBundleDisplayName</key><string>WOA AutoBot</string>
<key>CFBundleIdentifier</key><string>com.woa.autobot</string>
<key>CFBundleVersion</key><string>1.2.0</string>
<key>CFBundleShortVersionString</key><string>1.2.0</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleExecutable</key><string>WOA_AutoBot</string>
<key>LSMinimumSystemVersion</key><string>11.0</string>
<key>NSHighResolutionCapable</key><true/>
<key>NSRequiresAquaSystemAppearance</key><false/>
</dict></plist>
EOF
echo ">>> [4] Sign..."
codesign --remove-signature dist/WOA_AutoBot.app 2>/dev/null; codesign --deep --force --sign - dist/WOA_AutoBot.app 2>&1
echo ">>> [5] Create DMG..."
rm -f dist/WOA_AutoBot_macOS.dmg
TMP=$(mktemp -d) && cp -R dist/WOA_AutoBot.app "$TMP/" && ln -s /Applications "$TMP/Applications" && hdiutil create -volname "WOA AutoBot v1.2.0" -srcfolder "$TMP" -ov -format UDZO -size 600m dist/WOA_AutoBot_macOS.dmg 2>&1 && rm -rf "$TMP"
echo "=== ✅ DONE ==="
ls -lh dist/WOA_AutoBot_macOS.dmg