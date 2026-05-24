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

# ── 收集 ttkbootstrap 主题资源 ──
ttkbootstrap_datas = []
try:
    import ttkbootstrap
    ttkb_root = os.path.dirname(ttkbootstrap.__file__)
    themes_dir = os.path.join(ttkb_root, 'themes')
    if os.path.isdir(themes_dir):
        ttkbootstrap_datas = [(themes_dir, os.path.join('ttkbootstrap', 'themes'))]
except Exception:
    pass

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
        ('icon/digits', 'icon/digits'),
        ('icon/digits/global', 'icon/digits/global'),
        ('icon/digits/task', 'icon/digits/task'),
        ('docs', 'docs'),
    ] + ttkbootstrap_datas,
    hiddenimports=[
        # tkinter 全套
        'tkinter', 'tkinter.scrolledtext', 'tkinter.filedialog',
        'tkinter.messagebox', 'tkinter.ttk', 'tkinter.constants',
        # ttkbootstrap
        'ttkbootstrap', 'ttkbootstrap.constants', 'ttkbootstrap.style',
        'ttkbootstrap.widgets', 'ttkbootstrap.themes',
        # PIL 图像处理
        'PIL', 'PIL.Image', 'PIL.ImageTk', 'PIL.ImageDraw',
        'PIL.ImageFont', 'PIL.ImageFilter', 'PIL.ImageOps',
        'PIL._tkinter_finder', 'PIL._imagingtk',
        # cv2 / numpy
        'cv2', 'numpy',
        # JSON 加速
        'orjson',
        # 缓存工具
        'cachetools',
        # uiautomator2
        'uiautomator2', 'uiautomator2._funcs',
        'adbutils', 'adbutils._adb',
        # lxml
        'lxml', 'lxml.etree',
        # 网络请求与通知
        'requests', 'urllib3',
        'pystray',
        # SSL
        'certifi', 'ssl',
        # 项目内部模块
        'adb_controller', 'simple_ocr', 'gui_launcher',
        'main_adb', 'nemu_ipc', 'platform_utils',
        'woa_debug', 'emulator_discovery',
        'core', 'core.constants', 'core.platform',
        'core.resources', 'core.debug',
        'bot', 'bot.config', 'bot.tower', 'bot.filter',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'PyQt5', 'PyQt6', 'PySide2', 'PySide6',
        'matplotlib', 'scipy', 'pandas',
        'jupyter', 'notebook', 'ipykernel',
        'tensorflow', 'torch', 'keras',
        'wx', 'wxPython',
        'test', 'tests', 'unittest',
        'pydoc', 'doctest',
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
        'CFBundleVersion': '1.2.6',
        'CFBundleShortVersionString': '1.2.6',
        'CFBundlePackageType': 'APPL',
        'CFBundleInfoDictionaryVersion': '6.0',
        'LSMinimumSystemVersion': '11.0',
        'NSHighResolutionCapable': True,
        'NSRequiresAquaSystemAppearance': False,
        'NSPrincipalClass': 'NSApplication',
        'NSAppTransportSecurity': {
            'NSAllowsArbitraryLoads': True,
        },
        'LSApplicationCategoryType': 'public.app-category.utilities',
    },
)
