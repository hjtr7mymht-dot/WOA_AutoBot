# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [
    ('assets', 'assets'),
    ('icon', 'icon'),
    ('adb_tools', 'adb_tools'),
    ('platform-tools', 'platform-tools'),
    ('config.json', '.'),
    ('version.json', '.'),
    # 核心模块（重构后）
    ('core', 'core'),
    # Bot 引擎 Mixin 模块
    ('bot', 'bot'),
]

binaries = []

# certifi 证书数据收集
tmp_ret = collect_all('certifi')
datas += tmp_ret[0]
binaries += tmp_ret[1]
hiddenimports = tmp_ret[2]

hiddenimports += [
    # tkinter 组件
    'tkinter', 'tkinter.scrolledtext', 'tkinter.filedialog', 'tkinter.messagebox',

    # PIL/Pillow
    'PIL', 'PIL._tkinter_finder',
    'PIL.Image', 'PIL.ImageTk', 'PIL.ImageDraw',

    # OpenCV / 图像识别
    'cv2', 'numpy',

    # ttkbootstrap 现代 UI
    'ttkbootstrap', 'ttkbootstrap.constants', 'ttkbootstrap.widgets',

    # 性能优化
    'orjson', 'cachetools',

    # ADB / 模拟器控制
    'uiautomator2', 'uiautomator2.core', 'uiautomator2cache', 'adbutils',

    # 网络 / XML / 编码
    'lxml', 'lxml.etree',
    'requests', 'urllib3', 'charset_normalizer',
    'idna', 'encodings',

    # SSL 证书
    'certifi', 'ssl',

    # 崩溃转储（Windows segfault 日志）
    'faulthandler',
]

a = Analysis(
    ['gui_launcher.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
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
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='WOA_AutoBot',
)
