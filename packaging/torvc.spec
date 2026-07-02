# -*- mode: python ; coding: utf-8 -*-
"""
Spec de PyInstaller para empaquetar el cliente como un .exe autocontenido,
incluyendo el binario de Tor vendorizado (vendor/tor/windows/) para que la
app pueda lanzar su propio proceso Tor sin depender de nada instalado
aparte por el usuario (RF-03a).

Uso (desde la raiz del repo, con el ambiente conda `torvc` activado y
PyInstaller instalado -- `pip install pyinstaller`):

    pyinstaller packaging/torvc.spec --noconfirm

El .exe queda en dist/TorVC/TorVC.exe (modo onedir) o dist/TorVC.exe si se
cambia a onefile mas abajo. Antes de correr esto, populá
vendor/tor/windows/ con scripts/fetch_tor.ps1 (ver vendor/tor/README.md).

Nota: este spec no se puede probar desde un entorno Linux -- fue escrito
con cuidado siguiendo el patron estandar de PyInstaller para apps
PySide6 + OpenCV, pero es esperable iterar sobre imports faltantes la
primera vez que se corra en Windows real (ver README.md, seccion de
empaquetado).
"""
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

block_cipher = None

ROOT = Path(SPECPATH).resolve().parent  # packaging/ -> raiz del repo
VENDOR_TOR_WIN = ROOT / "vendor" / "tor" / "windows"

# --- Binario de Tor vendorizado (y sus DLLs/datos si el bundle los trae) ---
tor_binaries = []
if VENDOR_TOR_WIN.is_dir():
    for f in VENDOR_TOR_WIN.rglob("*"):
        if f.is_file():
            rel_dir = f.relative_to(ROOT).parent
            tor_binaries.append((str(f), str(rel_dir)))

if not tor_binaries:
    print(
        "ADVERTENCIA: vendor/tor/windows/ esta vacio. El .exe se generara "
        "sin Tor embebido (la app caera al modo 'Tor externo' en tiempo de "
        "ejecucion). Corre scripts/fetch_tor.ps1 antes de empaquetar para "
        "un build autocontenido."
    )

a = Analysis(
    [str(ROOT / "run.py")],
    pathex=[str(ROOT)],
    binaries=tor_binaries,
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)

# PySide6, cv2, sounddevice, aiohttp_socks y opuslib traen binarios/plugins
# propios que el analisis estatico de PyInstaller no siempre detecta solo.
for pkg in ("PySide6", "cv2", "sounddevice", "aiohttp_socks", "opuslib"):
    try:
        pkg_datas, pkg_binaries, pkg_hiddenimports = collect_all(pkg)
        a.datas += pkg_datas
        a.binaries += pkg_binaries
        a.hiddenimports += pkg_hiddenimports
    except Exception as exc:  # el paquete puede no estar instalado en dev
        print(f"collect_all('{pkg}') fallo (¿esta instalado?): {exc}")

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TorVC",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # console=True es util para depurar errores de arranque la primera vez
    # (con console=False y un crash temprano, Windows no muestra nada).
    console=False,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="TorVC",
)
