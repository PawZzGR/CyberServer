# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['AdminClient\\CyberClient_Admin.py'],
    pathex=[],
    binaries=[],
    datas=[('AdminClient\\sync_folders.json', '.'), ('AdminClient\\client_admin_mappings.json', '.'), ('AdminClient\\toast.py', '.'), ('AdminClient\\utils.py', '.'), ('AdminClient\\common.py', '.'), ('background.png', '.')],
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
    name='CyberClient_Admin',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    uac_admin=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
