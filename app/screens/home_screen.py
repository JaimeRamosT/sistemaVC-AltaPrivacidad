"""Pantalla inicial: crear sala o unirse a una (RF-01a/b)."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QFrame
)


class HomeScreen(QWidget):
    create_room_requested = Signal()
    join_room_requested = Signal()
    settings_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(60, 60, 60, 60)
        layout.setSpacing(18)
        layout.addStretch(1)

        title = QLabel("Videollamada Privada sobre Tor")
        title.setStyleSheet("font-size: 22px; font-weight: 600;")
        subtitle = QLabel("Comunicación 1 a 1, sin cuentas, sin metadatos, sin rastro local.")
        subtitle.setStyleSheet("color: #888;")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep)

        btn_create = QPushButton("Crear nueva sala")
        btn_create.setMinimumHeight(44)
        btn_create.clicked.connect(self.create_room_requested.emit)

        btn_join = QPushButton("Unirse a una sala")
        btn_join.setMinimumHeight(44)
        btn_join.clicked.connect(self.join_room_requested.emit)

        btn_settings = QPushButton("Configuración de conexión (servidor / proxy Tor)")
        btn_settings.setFlat(True)
        btn_settings.clicked.connect(self.settings_requested.emit)

        layout.addWidget(btn_create)
        layout.addWidget(btn_join)
        layout.addSpacing(10)
        layout.addWidget(btn_settings)
        layout.addStretch(2)

        note = QLabel(
            "Esta versión (POC) no guarda historial, cuentas ni caché en disco.\n"
            "Todo el tráfico sale exclusivamente por el proxy SOCKS5 de Tor."
        )
        note.setStyleSheet("color: #999; font-size: 11px;")
        note.setWordWrap(True)
        layout.addWidget(note)
