"""
Pantalla de arranque: se muestra primero (antes de Home) mientras la app
levanta y espera el bootstrap de su propio proceso Tor (RF-03a). Si falla o
no se encuentra el binario vendorizado, ofrece reintentar o continuar en
modo "Tor externo" (equivalente al flujo manual documentado en el README).
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar, QPushButton
)


class TorBootstrapScreen(QWidget):
    retry_requested = Signal()
    skip_requested = Signal()   # continuar con Tor externo / configuracion manual

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(60, 80, 60, 80)
        layout.setSpacing(16)
        layout.addStretch(1)

        self.title = QLabel("Conectando a la red Tor…")
        self.title.setStyleSheet("font-size: 18px; font-weight: 600;")
        layout.addWidget(self.title)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        self.detail = QLabel("Iniciando…")
        self.detail.setStyleSheet("color: #888;")
        layout.addWidget(self.detail)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #d9534f;")
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)

        row = QHBoxLayout()
        self.btn_retry = QPushButton("Reintentar")
        self.btn_retry.clicked.connect(self.retry_requested.emit)
        self.btn_retry.hide()
        self.btn_skip = QPushButton("Usar un Tor externo (avanzado)")
        self.btn_skip.clicked.connect(self.skip_requested.emit)
        self.btn_skip.hide()
        row.addWidget(self.btn_retry)
        row.addWidget(self.btn_skip)
        layout.addLayout(row)

        layout.addStretch(2)

    def set_progress(self, pct: int, desc: str) -> None:
        self.progress.setValue(pct)
        self.detail.setText(desc or f"Bootstrapped {pct}%")
        self.error_label.setText("")
        self.btn_retry.hide()
        self.btn_skip.hide()

    def set_error(self, message: str) -> None:
        self.title.setText("No se pudo conectar a Tor")
        self.error_label.setText(message)
        self.btn_retry.show()
        self.btn_skip.show()

    def reset(self) -> None:
        self.title.setText("Conectando a la red Tor…")
        self.progress.setValue(0)
        self.detail.setText("Iniciando…")
        self.error_label.setText("")
        self.btn_retry.hide()
        self.btn_skip.hide()
