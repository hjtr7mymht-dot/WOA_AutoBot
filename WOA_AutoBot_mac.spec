# -*- mode: python ; coding: utf-8 -*-
"""
WOA AutoBot macOS 打包配置
用法: cd /path/to/WOA_AutoBot && uv run pyinstaller -y --clean WOA_AutoBot_mac.spec
"""
import os
import sys

# spec 执行时所在目录
_dir = os.getcwd()
ADB = 'adb'  # macOS 平台

block_cipher = None

a = Analysis(
    ['gui_launcher.py'],
    pathex=[_dir],
    binaries=[],
    datas=[
        ('assets', 'assets'),
        ('icon', 'icon'),
        ('adb_tools', 'adb_tools'),
        ('platform-tools', 'platform-tools'),
        ('config.json', '.'),
        ('version.json', '.'),
    ],
    hiddenimports=[
        'tkinter', 'tkinter.scrolledtext', 'tkinter.filedialog', 'tkinter.messagebox',
        'PIL', 'PIL._tkinter_finder',
        'cv2', 'numpy',
        'orjson', 'cachetools',
        'uiautomator2', 'adbutils',
        'lxml', 'lxml.etree',
        'requests', 'pystray',
        'PIL.Image', 'PIL.ImageTk', 'PIL.ImageDraw',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'PyQt5', 'PyQt6', 'PySide2', 'PySide6',
        'matplotlib', 'scipy', 'pandas',
        'jupyter', 'notebook', 'ipykernel',
        'tensorflow', 'torch', 'keras',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure, cipher=block_cipher)

adb_data = ('adb_tools/' + ADB, os.path.join('adb_tools', ADB), 'DATA')
plat_data = ('platform-tools/' + ADB, os.path.join('platform-tools', ADB), 'DATA')
all_extra_datas = [adb_data, plat_data]

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas + all_extra_datas,
    exclude_binaries=True,
    name='WOA_AutoBot',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas + all_extra_datas,
    strip=False,
    upx=False,
    name='WOA_AutoBot',
)

app = BUNDLE(
    coll,
    name='WOA_AutoBot.app',
    icon=None,
    bundle_identifier='com.woa.autobot',
    info_plist={
        'CFBundleName': 'WOA AutoBot',
        'CFBundleDisplayName': 'WOA AutoBot',
        'CFBundleVersion': '1.2.0',
        'CFBundleShortVersionString': '1.2.0',
        'NSHighResolutionCapable': True,
        'NSRequiresAquaSystemAppearance': False,
    },
)
