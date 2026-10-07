# -*- mode: python ; coding: utf-8 -*-
import sys
from PyInstaller.utils.hooks import collect_all

TESTS = ('numba.tests', 'numba.cuda.tests', 'llvmlite.tests', 'shapely.tests', 'geopandas.tests',
         'pyogrio.tests')

datas = [('data/tables', 'data/tables'), ('data/contours', 'data/contours'),
         ('a_propos.md', '.'), ('data/assets/logo_soleil.ico', 'data/assets'),
         ('data/assets/logo_soleil.png', 'data/assets')]
binaries = []
if sys.platform == 'win32':
    hiddenimports = ['webview.platforms.winforms', 'webview.platforms.edgechromium']
else:
    hiddenimports = ['webview.platforms.qt']
for paquet in ('pyproj', 'pyogrio', 'rasterio', 'geopandas', 'shapely', 'pvlib', 'numba',
               'llvmlite', 'folium', 'branca'):
    d, b, h = collect_all(paquet)
    datas += d
    binaries += b
    hiddenimports += [m for m in h if not m.startswith(TESTS)]


a = Analysis(
    ['interface.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[*TESTS, 'jedi', 'IPython', 'parso'],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='roofTool',
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
    icon='data/assets/logo_soleil.ico',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='roofTool',
)
