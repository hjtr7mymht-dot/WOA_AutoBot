# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('assets', 'assets'), ('icon', 'icon'), ('adb_tools', 'adb_tools'), ('platform-tools', 'platform-tools'), ('config.json', '.'), ('version.json', '.'), ('GUIDE.md', '.'), ('ANNOUNCEMENT.md', '.'), ('docs', 'docs'), ('icon/digits', 'icon/digits'), ('icon/digits/global', 'icon/digits/global'), ('icon/digits/task', 'icon/digits/task')]
binaries = []
hiddenimports = ['tkinter', 'tkinter.scrolledtext', 'tkinter.filedialog', 'tkinter.messagebox', 'tkinter.ttk', 'tkinter.constants', 'ttkbootstrap', 'ttkbootstrap.constants', 'ttkbootstrap.style', 'ttkbootstrap.widgets', 'ttkbootstrap.themes', 'PIL', 'PIL.Image', 'PIL.ImageTk', 'PIL.ImageDraw', 'PIL.ImageFont', 'PIL.ImageFilter', 'PIL.ImageOps', 'PIL._tkinter_finder', 'PIL._imagingtk', 'cv2', 'numpy', 'orjson', 'cachetools', 'uiautomator2', 'uiautomator2._funcs', 'adbutils', 'adbutils._adb', 'lxml', 'lxml.etree', 'requests', 'urllib3', 'pystray', 'certifi', 'ssl', 'adb_controller', 'simple_ocr', 'gui_launcher', 'main_adb', 'nemu_ipc', 'platform_utils', 'woa_debug', 'emulator_discovery', 'core', 'core.constants', 'core.platform', 'core.resources', 'core.debug', 'bot', 'bot.config', 'bot.tower', 'bot.filter']
tmp_ret = collect_all('tkinter')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('ttkbootstrap')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('certifi')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['gui_launcher.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
app = BUNDLE(
    coll,
    name='WOA_AutoBot.app',
    icon=None,
    bundle_identifier=None,
)
