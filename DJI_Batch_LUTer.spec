# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['src\\DJI_Batch_LUTer.py'],
    pathex=[],
    binaries=[],
    datas=[('src/assets', 'src/assets')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['unittest', 'pydoc', 'PyQt6.QtWebEngineCore', 'PyQt6.QtWebEngineWidgets', 'PyQt6.QtPdf', 'PyQt6.QtMultimedia', 'PyQt6.QtQml', 'PyQt6.QtQuick', 'PyQt6.QtNetwork', 'PyQt6.QtSql', 'PyQt6.QtTest', 'PyQt6.QtXml', 'tkinter', 'matplotlib', 'numpy', 'sqlite3'],
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
    name='DJI_Batch_LUTer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['src\\assets\\icon.ico'],
)
