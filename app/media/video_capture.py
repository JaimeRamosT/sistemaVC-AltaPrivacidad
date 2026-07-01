"""
Captura de cámara web en un QThread dedicado (para no bloquear la UI),
redimensiona a 360p y comprime a WebP a la tasa objetivo (RNF-03b/e).
"""
from __future__ import annotations

import time

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

from .. import config
from .webp_codec import encode_webp

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None


def numpy_to_qimage(frame_rgb) -> QImage:
    h, w, ch = frame_rgb.shape
    bytes_per_line = ch * w
    # .copy() evita que Qt lea un buffer de numpy que puede reciclarse
    return QImage(frame_rgb.copy().data, w, h, bytes_per_line, QImage.Format.Format_RGB888)


class VideoCaptureWorker(QThread):
    frame_encoded = Signal(bytes)     # WebP listo para cifrar + enviar
    preview_ready = Signal(QImage)    # vista previa local
    camera_error = Signal(str)

    def __init__(self, camera_index: int = 0, parent=None):
        super().__init__(parent)
        self._camera_index = camera_index
        self._running = False
        self._camera_enabled = True   # RF-02b

    def set_camera_enabled(self, enabled: bool) -> None:
        self._camera_enabled = enabled

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:
        if cv2 is None:
            self.camera_error.emit("OpenCV no está instalado; no se puede capturar video.")
            return
        cap = cv2.VideoCapture(self._camera_index)
        if not cap.isOpened():
            self.camera_error.emit("No se pudo abrir la cámara web (índice %d)." % self._camera_index)
            return
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.VIDEO_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.VIDEO_HEIGHT)

        self._running = True
        frame_interval = 1.0 / config.VIDEO_FPS
        try:
            while self._running:
                t0 = time.time()
                ok, frame_bgr = cap.read()
                if not ok:
                    continue
                if self._camera_enabled:
                    frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
                    frame_rgb = cv2.resize(frame_rgb, (config.VIDEO_WIDTH, config.VIDEO_HEIGHT))
                    try:
                        webp_bytes = encode_webp(frame_rgb)
                        self.frame_encoded.emit(webp_bytes)
                    except Exception as exc:  # no tumbar el hilo por un frame malo
                        self.camera_error.emit(f"Error codificando frame: {exc}")
                    self.preview_ready.emit(numpy_to_qimage(frame_rgb))
                elapsed = time.time() - t0
                sleep_for = frame_interval - elapsed
                if sleep_for > 0:
                    time.sleep(sleep_for)
        finally:
            cap.release()
