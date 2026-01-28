# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['Server\\main.py'],
    pathex=[],
    binaries=[],
    datas=[('Server\\server_config.json', '.'), ('Server\\toast.py', '.'), ('Server\\utils.py', '.'), ('Server\\common.py', '.'), ('Server\\api.py', '.'), ('Server\\database.py', '.'), ('Server\\gui.py', '.'), ('background.png', '.')],
    hiddenimports=[],
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
    a.binaries,
    a.datas,
    [],
    name='CyberServer',
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
)
