"""
Configuración de conexión (servidor .onion y proxy SOCKS5 de Tor).

Solo modifica valores en memoria (módulo app.config) para la sesión en
curso. No se escribe nada a disco (RNF-04d) — al cerrar la aplicación se
pierde y hay que volver a indicarlo o fijarlo por variable de entorno.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLineEdit, QSpinBox, QDialogButtonBox, QLabel
)

from .. import config


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configuración de conexión")
        layout = QVBoxLayout(self)

        note = QLabel(
            "Estos valores solo viven en memoria durante esta sesión "
            "(no se guardan en disco)."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(note)

        form = QFormLayout()
        self.server_url_input = QLineEdit(config.SERVER_WS_URL)
        self.server_url_input.setPlaceholderText("wss://xxxxxxxx.onion/ws")
        form.addRow("URL del servidor (WSS):", self.server_url_input)

        self.socks_host_input = QLineEdit(config.TOR_SOCKS_HOST)
        form.addRow("Host SOCKS5 de Tor:", self.socks_host_input)

        self.socks_port_input = QSpinBox()
        self.socks_port_input.setRange(1, 65535)
        self.socks_port_input.setValue(config.TOR_SOCKS_PORT)
        form.addRow("Puerto SOCKS5 de Tor:", self.socks_port_input)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._apply_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _apply_and_accept(self) -> None:
        config.SERVER_WS_URL = self.server_url_input.text().strip()
        config.TOR_SOCKS_HOST = self.socks_host_input.text().strip()
        config.TOR_SOCKS_PORT = self.socks_port_input.value()
        self.accept()
