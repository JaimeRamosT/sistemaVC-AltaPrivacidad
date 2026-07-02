"""
Gestión de un proceso Tor propio, empaquetado junto a la app (RF-03a: "no
requerirá configuraciones de red complejas por parte del usuario").

En vez de depender de que la persona tenga Tor Browser o un daemon `tor`
corriendo por su cuenta, la app puede lanzar y controlar su propia
instancia de `tor` (binario oficial vendorizado en `vendor/tor/<plataforma>/`,
ver `vendor/tor/README.md` para cómo obtenerlo) con una configuración
mínima y efímera:

  - `DataDirectory` en un directorio temporal que se borra al cerrar la app
    (best-effort, en línea con el espíritu de RNF-04d de no dejar rastro).
  - `SocksPort` local dedicado (no comparte puerto con una Tor Browser
    externa que el usuario pueda tener abierta en simultáneo).
  - Sin `ControlPort`: el progreso de arranque se seguye parseando stdout
    ("Bootstrapped NN%"), no hace falta autenticación de control.

Si `config.USE_BUNDLED_TOR` es False (o `config.DEV_DISABLE_TOR` es True),
este manager no se usa y la app sigue el flujo anterior (Tor externo
gestionado por el usuario, o sin Tor en absoluto contra el mock server).
"""
from __future__ import annotations

import platform
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Signal

from .. import config

_BOOTSTRAP_RE = re.compile(r"Bootstrapped (\d{1,3})%(?:\s*\(([^)]*)\))?")


class TorProcessManager(QObject):
    bootstrap_progress = Signal(int, str)   # porcentaje (0-100), descripcion corta
    ready = Signal(str, int)                # host, puerto SOCKS5 local ya listo
    failed = Signal(str)                    # motivo, en texto para mostrar al usuario
    stopped = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._process: Optional[subprocess.Popen] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._data_dir: Optional[str] = None
        self._stopping = False
        self._emitted_ready = False

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------
    def start(self, port: Optional[int] = None) -> None:
        self._stopping = False
        self._emitted_ready = False
        port = port or config.MANAGED_TOR_SOCKS_PORT

        binary = self.find_tor_binary()
        if binary is None:
            self.failed.emit(
                "No se encontró el binario de Tor empaquetado (se esperaba "
                f"en vendor/tor/{self.platform_subdir()}/). Ver "
                "vendor/tor/README.md, o desactivá TORVC_USE_BUNDLED_TOR "
                "para usar un Tor externo (Tor Browser / daemon `tor`)."
            )
            return

        self._data_dir = tempfile.mkdtemp(prefix="torvc-tor-")
        torrc_path = Path(self._data_dir) / "torrc"
        torrc_path.write_text(
            "\n".join([
                f"SocksPort 127.0.0.1:{port}",
                f"DataDirectory {self._data_dir}",
                "Log notice stdout",
                "AvoidDiskWrites 1",
                "ClientOnly 1",
                "",
            ]),
            encoding="utf-8",
        )

        popen_kwargs = dict(
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        if platform.system() == "Windows":
            # Evita que se abra una ventana de consola para el proceso hijo.
            popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

        try:
            self._process = subprocess.Popen(
                [str(binary), "-f", str(torrc_path)], **popen_kwargs
            )
        except OSError as exc:
            self.failed.emit(f"No se pudo iniciar el proceso Tor: {exc}")
            self._cleanup_data_dir()
            return

        self._reader_thread = threading.Thread(
            target=self._read_output, args=(port,), daemon=True
        )
        self._reader_thread.start()

    def stop(self) -> None:
        self._stopping = True
        if self._process is not None and self._process.poll() is None:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
        self._process = None
        self._cleanup_data_dir()
        self.stopped.emit()

    # ------------------------------------------------------------------
    # Internos
    # ------------------------------------------------------------------
    def _read_output(self, port: int) -> None:
        assert self._process is not None and self._process.stdout is not None
        try:
            for line in self._process.stdout:
                if self._stopping:
                    break
                match = _BOOTSTRAP_RE.search(line)
                if not match:
                    continue
                pct = int(match.group(1))
                desc = (match.group(2) or "").strip()
                self.bootstrap_progress.emit(pct, desc)
                if pct >= 100 and not self._emitted_ready:
                    self._emitted_ready = True
                    self.ready.emit("127.0.0.1", port)
        finally:
            if not self._stopping and not self._emitted_ready:
                self.failed.emit(
                    "El proceso Tor terminó antes de completar el bootstrap "
                    "(revisa que el puerto SOCKS5 no esté ocupado por otra "
                    "instancia de Tor)."
                )

    def _cleanup_data_dir(self) -> None:
        if self._data_dir:
            shutil.rmtree(self._data_dir, ignore_errors=True)
            self._data_dir = None

    # ------------------------------------------------------------------
    # Resolución del binario vendorizado (dev y PyInstaller-frozen)
    # ------------------------------------------------------------------
    @staticmethod
    def platform_subdir() -> str:
        system = platform.system()
        if system == "Windows":
            return "windows"
        if system == "Darwin":
            return "macos"
        return "linux"

    @classmethod
    def vendor_dir(cls) -> Path:
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            base = Path(sys._MEIPASS)  # type: ignore[attr-defined]  # PyInstaller onefile
        else:
            # app/tor/tor_manager.py -> app/tor -> app -> raiz del repo
            base = Path(__file__).resolve().parent.parent.parent
        return base / "vendor" / "tor" / cls.platform_subdir()

    @classmethod
    def find_tor_binary(cls) -> Optional[Path]:
        exe_name = "tor.exe" if platform.system() == "Windows" else "tor"
        vendor_dir = cls.vendor_dir()
        if not vendor_dir.is_dir():
            return None
        direct = vendor_dir / exe_name
        if direct.is_file():
            return direct
        # el Tor Expert Bundle a veces anida el binario en una subcarpeta
        for found in vendor_dir.rglob(exe_name):
            return found
        return None
