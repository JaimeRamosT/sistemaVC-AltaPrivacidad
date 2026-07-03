"""
Orquestador central de una llamada: conecta la señalización (WSClient), el
canal de media (RelayClient), el cifrado de sesión (SessionKeyManager) y los
pipelines de media (video/audio) con la UI. Las pantallas de PySide6 solo
hablan con este controlador; no tocan la red ni los codecs directamente.

Mapeo del modelo de "sala con código+contraseña" (la UX original, pensada
para `mock_server`) sobre el modelo real del backend TorZoom, que autentica
usuarios por `user_id` y hace que un usuario "llame" a otro por su
`user_id` (no hay concepto de "sala" en el backend):

  - Quien crea la sala se autentica ante el backend usando como `user_id`
    un hash determinístico de `room_id:password` (calculable por cualquiera
    que conozca ambos datos, exactamente como antes solo quien tuviera el
    código+contraseña podía unirse). Mientras espera, ese `user_id` queda
    "online" y "llamable".
  - Quien se une genera un `user_id` propio aleatorio y desechable, y le
    pide al backend `CALL_REQUEST` contra ese mismo hash -- el equivalente
    a "tocar timbre" en la sala.
  - Al recibir `INCOMING_CALL`, el creador acepta automáticamente (no hay
    paso de "aceptar" explícito, igual que antes el creador nunca aprobaba
    manualmente al peer que hacía `join_room`).
  - Tras `ROOM_ASSIGNED`, ambos abren una conexión al relay de media
    (`RelayClient`). Como el backend no reenvía mensajes de aplicación
    arbitrarios entre los dos peers de una llamada, el intercambio de clave
    de sesión (X25519) y el estado de mute viajan por esa conexión al
    relay en vez de por el WebSocket de señalización (ver
    `network/relay_client.py` y `network/protocol.py`).
"""
from __future__ import annotations

import base64
import hashlib
import random
import secrets
import string
import time
import uuid
from enum import Enum, auto

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage

from . import config
from .network.ws_client import WSClient
from .network.relay_client import RelayClient
from .network import protocol
from .security.ephemeral import SessionKeyManager
from .media.video_capture import VideoCaptureWorker
from .media.webp_codec import decode_webp
from .media.video_capture import numpy_to_qimage
from .media.audio_io import AudioCaptureWorker, AudioPlaybackWorker, audio_available


class CallStatus(Enum):
    IDLE = auto()
    CONECTANDO = auto()          # abriendo el WebSocket / autenticando / esperando sala
    ESPERANDO_PEER = auto()      # sala creada, esperando al segundo usuario
    NEGOCIANDO_CLAVES = auto()   # ROOM_ASSIGNED recibido, conectando al relay + intercambiando claves
    EN_LLAMADA = auto()
    DESCONECTADO = auto()


class CallController(QObject):
    status_changed = Signal(object)          # CallStatus
    room_created = Signal(str, str, object)  # roomId, password, expiresAt
    join_result = Signal(bool, str)          # ok, mensaje/razón
    peer_joined = Signal()
    peer_left = Signal()
    peer_mute_changed = Signal(bool, bool)   # audio_muted, video_muted
    local_frame_ready = Signal(QImage)
    remote_frame_ready = Signal(QImage)
    error_occurred = Signal(str)
    call_ended = Signal(str)                 # motivo

    def __init__(self, server_url: str | None = None, parent=None):
        super().__init__(parent)
        self._server_url = server_url
        self._ws: WSClient | None = None
        self._relay: RelayClient | None = None
        self._session = SessionKeyManager()
        self._video_worker: VideoCaptureWorker | None = None
        self._audio_capture: AudioCaptureWorker | None = None
        self._audio_playback: AudioPlaybackWorker | None = None

        self._room_id: str | None = None
        self._password: str | None = None
        self._call_id: str | None = None
        self._is_creator = False
        self._video_seq = 0
        self._audio_seq = 0
        self._control_seq = 0
        self._mic_muted = False
        self._camera_off = False

        self._status = CallStatus.IDLE

    # ------------------------------------------------------------------
    # API pública para las pantallas
    # ------------------------------------------------------------------
    def create_room(self) -> None:
        self._is_creator = True
        self._room_id = _gen_room_id()
        self._password = _gen_password()
        own_user_id = _room_user_id(self._room_id, self._password)
        self._connect_ws(own_user_id)

    def join_room(self, room_id: str, password: str) -> None:
        self._is_creator = False
        self._room_id = room_id
        self._password = password
        own_user_id = str(uuid.uuid4())
        self._connect_ws(own_user_id)

    def set_mic_muted(self, muted: bool) -> None:
        self._mic_muted = muted
        if self._audio_capture is not None:
            self._audio_capture.set_mic_enabled(not muted)
        self._broadcast_mute_state()

    def set_camera_off(self, off: bool) -> None:
        self._camera_off = off
        if self._video_worker is not None:
            self._video_worker.set_camera_enabled(not off)
        self._broadcast_mute_state()

    def hangup(self) -> None:
        if self._ws is not None and self._call_id:
            try:
                self._ws.send_signal(*protocol.call_ended_msg(self._call_id))
            except Exception:
                pass
        self._teardown(reason="colgado_por_usuario")

    # ------------------------------------------------------------------
    # Internos: señalización (WSClient)
    # ------------------------------------------------------------------
    def _set_status(self, status: CallStatus) -> None:
        self._status = status
        self.status_changed.emit(status)

    def _connect_ws(self, own_user_id: str) -> None:
        self._set_status(CallStatus.CONECTANDO)
        self._ws = WSClient(own_user_id, self._server_url)
        self._ws.connected.connect(self._on_ws_connected)
        self._ws.auth_failed.connect(self._on_auth_failed)
        self._ws.disconnected.connect(self._on_ws_disconnected)
        self._ws.error.connect(self._on_ws_error)
        self._ws.signal_received.connect(self._on_signal)
        self._ws.start()

    def _on_ws_connected(self) -> None:
        """AUTH_OK recibido: la sesión de señalización ya está lista."""
        if self._is_creator:
            self._set_status(CallStatus.ESPERANDO_PEER)
            expires_at = int(time.time()) + config.ROOM_CREDENTIALS_TTL_SECONDS
            self.room_created.emit(self._room_id or "", self._password or "", expires_at)
        else:
            target = _room_user_id(self._room_id or "", self._password or "")
            self._call_id = str(uuid.uuid4())
            self._ws.send_signal(*protocol.call_request_msg(self._call_id, target, "video"))

    def _on_auth_failed(self, reason: str) -> None:
        if self._is_creator:
            self.error_occurred.emit(f"No se pudo autenticar ante el servidor ({reason}).")
        else:
            self.join_result.emit(False, "auth_failed")
        self._set_status(CallStatus.DESCONECTADO)

    def _on_ws_disconnected(self, reason: str) -> None:
        if self._status != CallStatus.IDLE:
            self._set_status(CallStatus.DESCONECTADO)

    def _on_ws_error(self, message: str) -> None:
        self.error_occurred.emit(message)

    def _on_signal(self, msg_type: str, payload: dict) -> None:
        if msg_type == protocol.TYPE_INCOMING_CALL:
            self._on_incoming_call(payload)
        elif msg_type == protocol.TYPE_ROOM_ASSIGNED:
            self._on_room_assigned(payload)
        elif msg_type == protocol.TYPE_USER_OFFLINE:
            self.join_result.emit(False, "room_not_found")
            self._teardown(reason="sala_no_encontrada")
        elif msg_type == protocol.TYPE_CALL_BUSY:
            self.join_result.emit(False, "room_full")
            self._teardown(reason="sala_ocupada")
        elif msg_type == protocol.TYPE_CALL_CANCELED:
            self.peer_left.emit()
            self._teardown(reason="llamada_cancelada")
        elif msg_type == protocol.TYPE_CALL_ENDED:
            self._teardown(reason="el_otro_usuario_colgo")
        elif msg_type == protocol.TYPE_ERROR:
            self.error_occurred.emit(payload.get("message", "Error del servidor"))
        # CALL_REJECTED no debería ocurrir nunca (el creador siempre acepta
        # automáticamente), pero si el backend lo enviara, se ignora en vez
        # de romper el flujo.

    def _on_incoming_call(self, payload: dict) -> None:
        if self._status != CallStatus.ESPERANDO_PEER or self._ws is None:
            return  # estado inesperado (p.ej. segunda llamada mientras ya hay una activa): ignorar
        self._call_id = payload.get("call_id", "")
        self.peer_joined.emit()
        self._set_status(CallStatus.NEGOCIANDO_CLAVES)
        self._ws.send_signal(*protocol.call_accepted_msg(self._call_id))

    def _on_room_assigned(self, payload: dict) -> None:
        if not self._is_creator:
            self.join_result.emit(True, "")
        self._set_status(CallStatus.NEGOCIANDO_CLAVES)

        own_pubkey_raw = base64.b64decode(self._session.generate_keypair())

        port = int(payload.get("port", 0))
        token = payload.get("token", "")
        if config.DEV_DISABLE_TOR:
            # Sin Tor real no hay direcciones .onion que resolver: el
            # orchestrator publica el puerto del relay directo en el host.
            host = "127.0.0.1"
        else:
            host = payload.get("onion_address", "")

        self._relay = RelayClient(host, port, token, own_pubkey_raw)
        self._relay.peer_pubkey_received.connect(self._on_peer_pubkey)
        self._relay.connected.connect(self._begin_media)
        self._relay.media_received.connect(self._on_media)
        self._relay.error.connect(self.error_occurred.emit)
        self._relay.disconnected.connect(self._on_relay_disconnected)
        self._relay.start()

    def _on_relay_disconnected(self, reason: str) -> None:
        # RelayClient siempre emite disconnected al terminar, tanto si
        # llegó a EN_LLAMADA y se cayó después como si nunca logró
        # conectar (p.ej. timeout de Tor construyendo el circuito, o el
        # propio relay dando de baja el contenedor por falta de actividad).
        # Sin este segundo caso, un fallo de conexión al relay dejaba la
        # llamada trabada para siempre en "Estableciendo canal seguro..."
        # -- el usuario ya vio el error via error_occurred, pero la app
        # nunca se recuperaba ni volvía sola al menú.
        if self._status == CallStatus.EN_LLAMADA:
            self._teardown(reason="conexion_con_el_otro_usuario_perdida")
        elif self._status == CallStatus.NEGOCIANDO_CLAVES:
            self._teardown(reason="no_se_pudo_conectar_al_relay")

    # ------------------------------------------------------------------
    # Internos: clave de sesión + media (RelayClient)
    # ------------------------------------------------------------------
    def _on_peer_pubkey(self, peer_pub_raw: bytes) -> None:
        peer_pub_b64 = base64.b64encode(peer_pub_raw).decode("ascii")
        self._session.derive_shared_key(peer_pub_b64, self._room_id or "")

    def _begin_media(self) -> None:
        self._set_status(CallStatus.EN_LLAMADA)

        self._video_worker = VideoCaptureWorker()
        self._video_worker.frame_encoded.connect(self._on_local_video_frame)
        self._video_worker.preview_ready.connect(self.local_frame_ready.emit)
        self._video_worker.camera_error.connect(self.error_occurred.emit)
        self._video_worker.start()

        if audio_available():
            self._audio_capture = AudioCaptureWorker()
            self._audio_capture.frame_encoded.connect(self._on_local_audio_frame)
            self._audio_capture.audio_error.connect(self.error_occurred.emit)
            self._audio_capture.start()

            self._audio_playback = AudioPlaybackWorker()
            self._audio_playback.audio_error.connect(self.error_occurred.emit)
            self._audio_playback.start()
        else:
            self.error_occurred.emit("Audio no disponible en este equipo: la llamada continúa solo con video.")

    def _on_local_video_frame(self, webp_bytes: bytes) -> None:
        if not self._session.ready or self._relay is None:
            return
        self._video_seq += 1
        nonce8 = SessionKeyManager.new_nonce8()
        ciphertext = self._session.encrypt(self._video_seq, nonce8, webp_bytes)
        frame = protocol.MediaFrame(protocol.MediaType.VIDEO, self._video_seq, _now_ms(), nonce8, ciphertext)
        self._relay.send_media(frame.pack())

    def _on_local_audio_frame(self, opus_bytes: bytes) -> None:
        if not self._session.ready or self._relay is None:
            return
        self._audio_seq += 1
        nonce8 = SessionKeyManager.new_nonce8()
        ciphertext = self._session.encrypt(self._audio_seq, nonce8, opus_bytes)
        frame = protocol.MediaFrame(protocol.MediaType.AUDIO, self._audio_seq, _now_ms(), nonce8, ciphertext)
        self._relay.send_media(frame.pack())

    def _on_media(self, frame: protocol.MediaFrame) -> None:
        if not self._session.ready:
            return
        try:
            plaintext = self._session.decrypt(frame.seq, frame.nonce8, frame.ciphertext)
        except Exception:
            return  # frame corrupto o clave desincronizada: se descarta (no hay retransmisión, RNF-02b)

        if frame.media_type == protocol.MediaType.VIDEO:
            try:
                frame_rgb = decode_webp(plaintext)
                self.remote_frame_ready.emit(numpy_to_qimage(frame_rgb))
            except Exception:
                pass
        elif frame.media_type == protocol.MediaType.AUDIO and self._audio_playback is not None:
            self._audio_playback.push_packet(plaintext)
        elif frame.media_type == protocol.MediaType.CONTROL:
            try:
                audio_muted, video_muted = protocol.parse_control_payload(plaintext)
                self.peer_mute_changed.emit(audio_muted, video_muted)
            except Exception:
                pass

    def _broadcast_mute_state(self) -> None:
        if self._relay is None or not self._session.ready or self._status != CallStatus.EN_LLAMADA:
            return
        self._control_seq += 1
        nonce8 = SessionKeyManager.new_nonce8()
        plaintext = protocol.control_payload(self._mic_muted, self._camera_off)
        ciphertext = self._session.encrypt(self._control_seq, nonce8, plaintext)
        frame = protocol.MediaFrame(protocol.MediaType.CONTROL, self._control_seq, _now_ms(), nonce8, ciphertext)
        self._relay.send_media(frame.pack())

    # ------------------------------------------------------------------
    def _teardown(self, reason: str) -> None:
        if self._status == CallStatus.IDLE:
            return  # ya se limpió (p.ej. CALL_ENDED y caída del relay casi simultáneos)

        if self._video_worker is not None:
            self._video_worker.stop()
            self._video_worker.wait(1000)
            self._video_worker = None
        if self._audio_capture is not None:
            self._audio_capture.stop()
            self._audio_capture = None
        if self._audio_playback is not None:
            self._audio_playback.stop()
            self._audio_playback = None

        self._session.purge()  # RNF-04b/04c: nunca dejar claves en memoria tras colgar

        if self._relay is not None:
            self._relay.stop()
            self._relay.wait(1000)
            self._relay = None

        if self._ws is not None:
            self._ws.stop()
            self._ws.wait(1000)
            self._ws = None

        self._video_seq = 0
        self._audio_seq = 0
        self._control_seq = 0
        self._call_id = None
        self._room_id = None
        self._password = None
        self._set_status(CallStatus.IDLE)
        self.call_ended.emit(reason)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _room_user_id(room_id: str, password: str) -> str:
    """Identificador determinístico y opaco derivado del código+contraseña
    de la sala: cualquiera que los conozca puede calcularlo, exactamente
    como antes solo quien tuviera ambos datos podía unirse. El backend real
    solo entiende "user_id" (no "salas"), así que este hash hace de sala."""
    return hashlib.sha256(f"{room_id}:{password}".encode("utf-8")).hexdigest()


def _gen_room_id() -> str:
    return "".join(random.choices(string.digits, k=6))


def _gen_password() -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "-".join("".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(2))
