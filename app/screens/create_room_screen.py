"""Pantalla de creación de sala: muestra credenciales y espera al peer (RF-01a/c)."""
from __future__ import annotations

from PySide6.QtCore import Signal, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QApplication
)


class CreateRoomScreen(QWidget):
    cancel_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._expires_at = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(60, 60, 60, 60)
        layout.setSpacing(14)

        self.status_label = QLabel("Creando sala…")
        self.status_label.setStyleSheet("font-size: 18px; font-weight: 600;")
        layout.addWidget(self.status_label)

        layout.addWidget(QLabel("Número de sala:"))
        row1 = QHBoxLayout()
        self.room_id_field = QLineEdit()
        self.room_id_field.setReadOnly(True)
        btn_copy_id = QPushButton("Copiar")
        btn_copy_id.clicked.connect(lambda: self._copy(self.room_id_field.text()))
        row1.addWidget(self.room_id_field)
        row1.addWidget(btn_copy_id)
        layout.addLayout(row1)

        layout.addWidget(QLabel("Contraseña:"))
        row2 = QHBoxLayout()
        self.password_field = QLineEdit()
        self.password_field.setReadOnly(True)
        btn_copy_pw = QPushButton("Copiar")
        btn_copy_pw.clicked.connect(lambda: self._copy(self.password_field.text()))
        row2.addWidget(self.password_field)
        row2.addWidget(btn_copy_pw)
        layout.addLayout(row2)

        self.expiry_label = QLabel("")
        self.expiry_label.setStyleSheet("color: #999;")
        layout.addWidget(self.expiry_label)

        hint = QLabel(
            "Comparte estas credenciales con la otra persona por un canal "
            "externo seguro (no por este mismo chat/red)."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888; font-size: 12px;")
        layout.addWidget(hint)

        self.warning_label = QLabel("")
        self.warning_label.setStyleSheet("color: #d9534f; font-size: 12px;")
        self.warning_label.setWordWrap(True)
        layout.addWidget(self.warning_label)

        layout.addStretch(1)
        btn_cancel = QPushButton("Cancelar")
        btn_cancel.clicked.connect(self.cancel_requested.emit)
        layout.addWidget(btn_cancel)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)

    def show_credentials(self, room_id: str, password: str, expires_at) -> None:
        self.status_label.setText("Sala creada. Esperando a la otra persona…")
        self.room_id_field.setText(room_id)
        self.password_field.setText(password)
        self._expires_at = expires_at
        self._tick()

    def show_warning(self, text: str) -> None:
        self.warning_label.setText(text)

    def _tick(self) -> None:
        if self._expires_at is None:
            self.expiry_label.setText("")
            return
        import time
        remaining = int(self._expires_at) - int(time.time())
        if remaining <= 0:
            self.expiry_label.setText("Credenciales expiradas (RNF-04e).")
        else:
            mins, secs = divmod(remaining, 60)
            self.expiry_label.setText(f"Válidas por {mins:02d}:{secs:02d} más.")

    @staticmethod
    def _copy(text: str) -> None:
        QApplication.clipboard().setText(text)
