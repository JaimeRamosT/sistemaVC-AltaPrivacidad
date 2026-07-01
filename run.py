#!/usr/bin/env python3
"""
Punto de entrada de la aplicación de escritorio.

Uso:
    python run.py

Variables de entorno útiles (ver app/config.py):
    TORVC_SERVER_URL     wss://<direccion>.onion/ws  (backend ya levantado)
    TORVC_SOCKS_HOST     host del proxy SOCKS5 de Tor (default 127.0.0.1)
    TORVC_SOCKS_PORT     puerto del proxy SOCKS5 de Tor (default 9050)
    TORVC_DEV_NO_TOR=1   SOLO para pruebas locales contra mock_server/, sin Tor
"""
import sys

from PySide6.QtWidgets import QApplication

from app.utils.logging_guard import configure_ephemeral_logging
from app.utils.qt_env_fix import fix_qt_plugin_path
from app.main_window import MainWindow  # importa cv2 transitivamente


def main() -> int:
    configure_ephemeral_logging()
    fix_qt_plugin_path()  # debe ir despues del import de arriba, antes de QApplication
    app = QApplication(sys.argv)
    app.setApplicationName("Videollamada Privada sobre Tor")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
