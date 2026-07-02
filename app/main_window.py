"""
Ventana única de la aplicación (RF-03a): un QStackedWidget navega entre
Tor (arranque) -> Home -> Crear sala / Unirse a sala -> Llamada, sin abrir
ventanas adicionales ni requerir configuración de red por parte del
usuario común.
"""
from __future__ import annotations

from PySide6.QtWidgets import QMainWindow, QStackedWidget

from . import config
from .call_controller import CallController, CallStatus
from .tor.tor_manager import TorProcessManager
from .screens.tor_bootstrap_screen import TorBootstrapScreen
from .screens.home_screen import HomeScreen
from .screens.create_room_screen import CreateRoomScreen
from .screens.join_room_screen import JoinRoomScreen
from .screens.call_screen import CallScreen
from .screens.settings_dialog import SettingsDialog


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(config.APP_NAME)
        self.resize(1000, 640)

        self._controller: CallController | None = None
        self._tor_manager: TorProcessManager | None = None

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.tor_screen = TorBootstrapScreen()
        self.home_screen = HomeScreen()
        self.create_room_screen = CreateRoomScreen()
        self.join_room_screen = JoinRoomScreen()
        self.call_screen = CallScreen()

        for w in (self.tor_screen, self.home_screen, self.create_room_screen,
                  self.join_room_screen, self.call_screen):
            self.stack.addWidget(w)

        self.tor_screen.retry_requested.connect(self._start_bundled_tor)
        self.tor_screen.skip_requested.connect(self._skip_bundled_tor)

        self.home_screen.create_room_requested.connect(self._start_create_room)
        self.home_screen.join_room_requested.connect(self._show_join_screen)
        self.home_screen.settings_requested.connect(self._open_settings)

        self.create_room_screen.cancel_requested.connect(self._cancel_and_go_home)
        self.join_room_screen.cancel_requested.connect(self._cancel_and_go_home)
        self.join_room_screen.join_requested.connect(self._start_join_room)

        self.call_screen.hangup_requested.connect(self._hangup)
        self.call_screen.mic_toggled.connect(self._on_mic_toggled)
        self.call_screen.camera_toggled.connect(self._on_camera_toggled)

        self._bootstrap_initial_screen()

    # ------------------------------------------------------------------
    # Arranque: Tor propio (por defecto), Tor externo, o sin Tor (mock)
    # ------------------------------------------------------------------
    def _bootstrap_initial_screen(self) -> None:
        if config.DEV_DISABLE_TOR:
            # Modo de pruebas locales contra mock_server/, sin Tor en absoluto.
            self._go_home()
        elif config.USE_BUNDLED_TOR:
            self.stack.setCurrentWidget(self.tor_screen)
            self._start_bundled_tor()
        else:
            # Tor externo administrado por el usuario (Tor Browser / daemon `tor`),
            # tal como se documenta en el README.
            self._go_home()

    def _start_bundled_tor(self) -> None:
        self.tor_screen.reset()
        self.stack.setCurrentWidget(self.tor_screen)

        if self._tor_manager is not None:
            self._tor_manager.stop()

        manager = TorProcessManager(self)
        manager.bootstrap_progress.connect(self.tor_screen.set_progress)
        manager.ready.connect(self._on_tor_ready)
        manager.failed.connect(self._on_tor_failed)
        self._tor_manager = manager
        manager.start()

    def _on_tor_ready(self, host: str, port: int) -> None:
        config.TOR_SOCKS_HOST = host
        config.TOR_SOCKS_PORT = port
        self._go_home()

    def _on_tor_failed(self, reason: str) -> None:
        self.tor_screen.set_error(reason)

    def _skip_bundled_tor(self) -> None:
        # El usuario elige seguir con un Tor externo (Tor Browser / daemon)
        # en vez de reintentar el proceso Tor propio.
        if self._tor_manager is not None:
            self._tor_manager.stop()
            self._tor_manager = None
        config.USE_BUNDLED_TOR = False
        self._go_home()

    # ------------------------------------------------------------------
    def _open_settings(self) -> None:
        SettingsDialog(self).exec()

    def _go_home(self) -> None:
        self.stack.setCurrentWidget(self.home_screen)

    def _show_join_screen(self) -> None:
        self.join_room_screen.error_label.setText("")
        self.stack.setCurrentWidget(self.join_room_screen)

    def _new_controller(self) -> CallController:
        if self._controller is not None:
            self._disconnect_controller()
        controller = CallController()
        controller.status_changed.connect(self._on_status_changed)
        controller.room_created.connect(self._on_room_created)
        controller.join_result.connect(self._on_join_result)
        controller.peer_joined.connect(self._on_peer_joined)
        controller.peer_left.connect(self._on_peer_left)
        controller.local_frame_ready.connect(self.call_screen.show_local_frame)
        controller.remote_frame_ready.connect(self.call_screen.show_remote_frame)
        controller.error_occurred.connect(self._on_error)
        controller.call_ended.connect(self._on_call_ended)
        self._controller = controller
        return controller

    def _disconnect_controller(self) -> None:
        try:
            self._controller.disconnect()
        except Exception:
            pass

    # -- Crear sala ------------------------------------------------------
    def _start_create_room(self) -> None:
        self.create_room_screen.status_label.setText("Creando sala…")
        self.create_room_screen.room_id_field.clear()
        self.create_room_screen.password_field.clear()
        self.create_room_screen.warning_label.setText("")
        self.stack.setCurrentWidget(self.create_room_screen)
        controller = self._new_controller()
        controller.create_room()

    def _on_room_created(self, room_id: str, password: str, expires_at) -> None:
        self.create_room_screen.show_credentials(room_id, password, expires_at)
        self.call_screen.set_room_id(room_id)

    # -- Unirse a sala -----------------------------------------------------
    def _start_join_room(self, room_id: str, password: str) -> None:
        controller = self._new_controller()
        controller.join_room(room_id, password)

    def _on_join_result(self, ok: bool, reason: str) -> None:
        if not ok:
            self.join_room_screen.show_error(reason)

    # -- Eventos comunes de sala/llamada -----------------------------------
    def _on_peer_joined(self) -> None:
        self.call_screen.set_room_id(self._controller._room_id or "")
        self.call_screen.reset_controls()
        self.stack.setCurrentWidget(self.call_screen)

    def _on_peer_left(self) -> None:
        self.call_screen.reset_remote()
        self.call_screen.show_warning("La otra persona salió de la llamada.")

    def _on_status_changed(self, status: CallStatus) -> None:
        self.call_screen.set_status(status)
        if status == CallStatus.EN_LLAMADA:
            self.stack.setCurrentWidget(self.call_screen)

    def _on_error(self, message: str) -> None:
        current = self.stack.currentWidget()
        if hasattr(current, "show_warning"):
            current.show_warning(message)
        else:
            self.call_screen.show_warning(message)

    def _on_call_ended(self, reason: str) -> None:
        self.call_screen.reset_controls()
        self._go_home()

    # -- Controles durante la llamada --------------------------------------
    def _on_mic_toggled(self, muted: bool) -> None:
        if self._controller is not None:
            self._controller.set_mic_muted(muted)

    def _on_camera_toggled(self, off: bool) -> None:
        if self._controller is not None:
            self._controller.set_camera_off(off)

    def _hangup(self) -> None:
        if self._controller is not None:
            self._controller.hangup()
        else:
            self._go_home()

    def _cancel_and_go_home(self) -> None:
        if self._controller is not None:
            self._controller.hangup()
        self._go_home()

    def closeEvent(self, event) -> None:
        if self._controller is not None:
            self._controller.hangup()
        if self._tor_manager is not None:
            self._tor_manager.stop()
        super().closeEvent(event)
