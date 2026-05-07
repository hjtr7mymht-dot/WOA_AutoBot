# -*- mode: python ; coding: utf-8 -*-
"""
WOA AutoBot Windows 打包配置
用法: pyinstaller -y --clean WOA_AutoBot.spec
"""
import os

_dir = os.getcwd()
ADB = 'adb.exe'

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
    excludes=[],
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
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version='version_info.txt',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas + all_extra_datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='WOA_AutoBot',
)
