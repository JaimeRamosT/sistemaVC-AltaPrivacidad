"""Pantalla para unirse a una sala existente con credenciales (RF-01b)."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QLineEdit, QPushButton, QHBoxLayout
)


class JoinRoomScreen(QWidget):
    join_requested = Signal(str, str)   # roomId, password
    cancel_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(60, 60, 60, 60)
        layout.setSpacing(14)

        title = QLabel("Unirse a una sala")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        layout.addWidget(title)

        layout.addWidget(QLabel("Número de sala"))
        self.room_id_input = QLineEdit()
        self.room_id_input.setPlaceholderText("Ej. 482913")
        layout.addWidget(self.room_id_input)

        layout.addWidget(QLabel("Contraseña"))
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.password_input)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #d9534f;")
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)

        layout.addStretch(1)
        row = QHBoxLayout()
        btn_cancel = QPushButton("Cancelar")
        btn_cancel.clicked.connect(self.cancel_requested.emit)
        btn_join = QPushButton("Unirse")
        btn_join.setDefault(True)
        btn_join.clicked.connect(self._emit_join)
        row.addWidget(btn_cancel)
        row.addWidget(btn_join)
        layout.addLayout(row)

    def _emit_join(self) -> None:
        room_id = self.room_id_input.text().strip()
        password = self.password_input.text()
        if not room_id or not password:
            self.error_label.setText("Completa número de sala y contraseña.")
            return
        self.error_label.setText("")
        self.join_requested.emit(room_id, password)

    def show_error(self, reason: str) -> None:
        mapping = {
            "invalid_credentials": "Número de sala o contraseña incorrectos.",
            "expired": "Las credenciales de esa sala ya expiraron (máx. 30 min).",
            "room_full": "Esa sala ya tiene dos participantes.",
        }
        self.error_label.setText(mapping.get(reason, f"No se pudo unir a la sala ({reason})."))
