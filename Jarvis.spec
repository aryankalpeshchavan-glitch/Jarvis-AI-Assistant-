# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['C:/Users/Aryan/OneDrive/Documents/Web Dev Projects/Jarvis/JarvisP1/main.py'],
    pathex=[],
    binaries=[],
    datas=[('C:/Users/Aryan/OneDrive/Documents/Web Dev Projects/Jarvis/JarvisP1/index.html', '.'), ('C:/Users/Aryan/OneDrive/Documents/Web Dev Projects/Jarvis/JarvisP1/assets', 'assets')],
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
    [],
    exclude_binaries=True,
    name='Jarvis',
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
    icon=['C:/Users/Aryan/OneDrive/Documents/Web Dev Projects/Jarvis/JarvisP1/assets/jarvis_icon.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Jarvis',
)
