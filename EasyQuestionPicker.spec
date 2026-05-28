# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules


webview_datas = collect_data_files("webview")
webview_binaries = collect_dynamic_libs("webview")
webview_hiddenimports = [
    name for name in collect_submodules("webview") if "webview.platforms.android" not in name
]


a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=webview_binaries,
    datas=webview_datas,
    hiddenimports=webview_hiddenimports,
    hookspath=['E:\\PythonProjects\\EasyWorking\\.venv\\Lib\\site-packages\\playwright\\_impl\\__pyinstaller'],
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
    a.binaries,
    a.datas,
    [],
    name='EasyQuestionPicker',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir='.runtime',
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
