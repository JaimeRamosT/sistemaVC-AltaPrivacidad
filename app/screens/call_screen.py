"""
Pantalla de llamada activa (RF-02): video local/remoto, mute de mic,
apagado de cámara, indicador de estado de conexión en tiempo real.
"""
from __future__ import annotations

from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy
)

from ..call_controller import CallStatus

_STATUS_TEXT = {
    CallStatus.IDLE: ("Inactivo", "#999"),
    CallStatus.CONECTANDO: ("Conectando…", "#e0a800"),
    CallStatus.ESPERANDO_PEER: ("Esperando a la otra persona…", "#e0a800"),
    CallStatus.NEGOCIANDO_CLAVES: ("Estableciendo canal seguro…", "#e0a800"),
    CallStatus.EN_LLAMADA: ("En llamada", "#28a745"),
    CallStatus.DESCONECTADO: ("Desconectado", "#d9534f"),
}


class VideoPane(QLabel):
    def __init__(self, placeholder: str, parent=None):
        super().__init__(parent)
        self._placeholder = placeholder
        self.setMinimumSize(320, 180)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background-color: #111; color: #666; border-radius: 6px;")
        self.setText(placeholder)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def show_frame(self, image: QImage) -> None:
        pix = QPixmap.fromImage(image).scaled(
            self.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        )
        self.setPixmap(pix)

    def clear_frame(self) -> None:
        self.setPixmap(QPixmap())
        self.setText(self._placeholder)


class CallScreen(QWidget):
    hangup_requested = Signal()
    mic_toggled = Signal(bool)      # True = muteado
    camera_toggled = Signal(bool)   # True = apagada

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mic_muted = False
        self._camera_off = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(12)

        status_row = QHBoxLayout()
        self.status_dot = QLabel("●")
        self.status_dot.setStyleSheet("color: #999; font-size: 16px;")
        self.status_text = QLabel("Inactivo")
        status_row.addWidget(self.status_dot)
        status_row.addWidget(self.status_text)
        status_row.addStretch(1)
        self.room_label = QLabel("")
        self.room_label.setStyleSheet("color: #888;")
        status_row.addWidget(self.room_label)
        outer.addLayout(status_row)

        videos_row = QHBoxLayout()
        self.remote_pane = VideoPane("Esperando video remoto…")
        self.local_pane = VideoPane("Tu cámara")
        videos_row.addWidget(self.remote_pane, 3)
        videos_row.addWidget(self.local_pane, 1)
        outer.addLayout(videos_row, 1)

        controls = QHBoxLayout()
        controls.addStretch(1)
        self.btn_mic = QPushButton("Silenciar micrófono")
        self.btn_mic.setCheckable(True)
        self.btn_mic.clicked.connect(self._on_mic_clicked)

        self.btn_camera = QPushButton("Apagar cámara")
        self.btn_camera.setCheckable(True)
        self.btn_camera.clicked.connect(self._on_camera_clicked)

        self.btn_hangup = QPushButton("Colgar")
        self.btn_hangup.setStyleSheet("background-color: #d9534f; color: white; font-weight: 600;")
        self.btn_hangup.clicked.connect(self.hangup_requested.emit)

        controls.addWidget(self.btn_mic)
        controls.addWidget(self.btn_camera)
        controls.addWidget(self.btn_hangup)
        controls.addStretch(1)
        outer.addLayout(controls)

        self.warning_label = QLabel("")
        self.warning_label.setStyleSheet("color: #e0a800; font-size: 11px;")
        self.warning_label.setWordWrap(True)
        outer.addWidget(self.warning_label)

    # -- actualizado por MainWindow según señales del CallController -------
    def set_room_id(self, room_id: str) -> None:
        self.room_label.setText(f"Sala {room_id}")

    def set_status(self, status: CallStatus) -> None:
        text, color = _STATUS_TEXT.get(status, ("—", "#999"))
        self.status_text.setText(text)
        self.status_dot.setStyleSheet(f"color: {color}; font-size: 16px;")

    def show_local_frame(self, image: QImage) -> None:
        if not self._camera_off:
            self.local_pane.show_frame(image)

    def show_remote_frame(self, image: QImage) -> None:
        self.remote_pane.show_frame(image)

    def reset_remote(self) -> None:
        self.remote_pane.clear_frame()

    def show_warning(self, text: str) -> None:
        self.warning_label.setText(text)

    def reset_controls(self) -> None:
        self._mic_muted = False
        self._camera_off = False
        self.btn_mic.setChecked(False)
        self.btn_mic.setText("Silenciar micrófono")
        self.btn_camera.setChecked(False)
        self.btn_camera.setText("Apagar cámara")
        self.local_pane.clear_frame()
        self.remote_pane.clear_frame()
        self.warning_label.setText("")

    def _on_mic_clicked(self) -> None:
        self._mic_muted = self.btn_mic.isChecked()
        self.btn_mic.setText("Activar micrófono" if self._mic_muted else "Silenciar micrófono")
        self.mic_toggled.emit(self._mic_muted)

    def _on_camera_clicked(self) -> None:
        self._camera_off = self.btn_camera.isChecked()
        self.btn_camera.setText("Encender cámara" if self._camera_off else "Apagar cámara")
        if self._camera_off:
            self.local_pane.clear_frame()
        self.camera_toggled.emit(self._camera_off)
