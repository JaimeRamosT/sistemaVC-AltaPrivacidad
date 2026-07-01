"""
OpenCV (cv2) empaqueta su propia copia de Qt con un directorio de plugins
incompleto (normalmente solo trae "libqxcb", sin "wayland"). Al importarse,
algunas builds de opencv fijan la variable de entorno
QT_QPA_PLATFORM_PLUGIN_PATH apuntando a ESE directorio, lo que hace que
PySide6 intente cargar los plugins de plataforma desde ahi en vez de los
suyos propios (que si traen wayland/xcb completos). Esto rompe el arranque
de la app con errores como:

    qt.qpa.plugin: Could not find the Qt platform plugin "wayland" in ""
    qt.qpa.plugin: Could not find the Qt platform plugin "xcb" in ""

Se ve tanto en Linux/WSL (con o sin Wayland) como en algunos setups con
conda. Referencia: https://github.com/opencv/opencv-python/issues/729

`fix_qt_plugin_path()` debe llamarse DESPUES de que cv2 se haya importado
(aunque sea transitivamente, como pasa via app.main_window ->
call_controller -> media.video_capture) y ANTES de crear la QApplication.
"""
from __future__ import annotations

import os


def fix_qt_plugin_path() -> None:
    os.environ.pop("QT_QPA_PLATFORM_PLUGIN_PATH", None)
    os.environ.pop("QT_PLUGIN_PATH", None)
