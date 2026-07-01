"""
RNF-04d: "La aplicación de escritorio cliente no guardará ningún tipo de
log, historial de llamadas, credenciales ni caché en el disco local una vez
cerrada la sesión."

Este módulo centraliza esa garantía:
  - El logging de Python se configura EXCLUSIVAMENTE con salida a stdout
    (nunca FileHandler / RotatingFileHandler).
  - No se usa QSettings ni ningún mecanismo de persistencia de Qt en toda la
    aplicación (grep del código: no debería aparecer QSettings).
  - Las credenciales de sala y las claves de sesión viven solo en atributos
    de objetos Python en memoria (ver call_controller.py / ephemeral.py) y
    se purgan al colgar.
"""
from __future__ import annotations

import logging
import sys


def configure_ephemeral_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))
    root.addHandler(handler)
    root.setLevel(level)

    # Aviso explícito por si alguna dependencia intenta escribir logs a disco.
    logging.getLogger(__name__).info(
        "Logging configurado solo en memoria/stdout (RNF-04d): no se escriben "
        "logs, historial ni caché en disco."
    )
