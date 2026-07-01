"""
Orquestador central de una llamada: conecta la señal/red (WSClient), el
cifrado de sesión (SessionKeyManager) y los pipelines de media (video/audio)
con la UI. Las pantallas de PySide6 solo hablan con este controlador; no
tocan la red ni los codecs directamente.
"""
from __future__ import annotations

import time
from enum import Enum, auto

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage

from .network.ws_client import WSClient
from .network import protocol
from .security.ephemeral import SessionKeyManager
from .media.video_capture import VideoCaptureWorker
from .media.webp_codec import decode_webp
from .media.video_capture import numpy_to_qimage
from .media.audio_io import AudioCaptureWorker, AudioPlaybackWorker, audio_available


class CallStatus(Enum):
    IDLE = auto()
    CONECTANDO = auto()          # abriendo el WebSocket / esperando sala
    ESPERANDO_PEER = auto()      # sala creada, esperando al segundo usuario
    NEGOCIANDO_CLAVES = auto()   # join_ok recibido, intercambiando claves
    EN_LLAMADA = auto()
    DESCONECTADO = auto()


class CallController(QObject):
    status_changed = Signal(object)          # CallStatus
    room_created = Signal(str, str, object)  # roomId, password, expiresAt
    join_result = Signal(bool, str)          # ok, mensaje
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
        self._session = SessionKeyManager()
        self._video_worker: VideoCaptureWorker | None = None
        self._audio_capture: AudioCaptureWorker | None = None
        self._audio_playback: AudioPlaybackWorker | None = None

        self._room_id: str | None = None
        self._is_creator = False
        self._sent_own_key = False
        self._received_peer_key = False
        self._video_seq = 0
        self._audio_seq = 0
        self._mic_muted = False
        self._camera_off = False

        self._status = CallStatus.IDLE

    # ------------------------------------------------------------------
    # API pública para las pantallas
    # ------------------------------------------------------------------
    def create_room(self) -> None:
        self._is_creator = True
        self._connect_and_then(lambda: self._ws.send_signal(protocol.create_room_msg()))

    def join_room(self, room_id: str, password: str) -> None:
        self._is_creator = False
        self._room_id = room_id
        self._connect_and_then(
            lambda: self._ws.send_signal(protocol.join_room_msg(room_id, password))
        )

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
        if self._ws is not None:
            try:
                self._ws.send_signal(protocol.call_end_msg())
            except Exception:
                pass
        self._teardown(reason="colgado_por_usuario")

    # ------------------------------------------------------------------
    # Internos
    # ------------------------------------------------------------------
    def _set_status(self, status: CallStatus) -> None:
        self._status = status
        self.status_changed.emit(status)

    def _connect_and_then(self, on_connected) -> None:
        self._set_status(CallStatus.CONECTANDO)
        self._ws = WSClient(self._server_url)
        self._ws.connected.connect(on_connected)
        self._ws.disconnected.connect(self._on_ws_disconnected)
        self._ws.error.connect(self._on_ws_error)
        self._ws.signal_received.connect(self._on_signal)
        self._ws.media_received.connect(self._on_media)
        self._ws.start()

    def _on_ws_disconnected(self, reason: str) -> None:
        if self._status != CallStatus.IDLE:
            self._set_status(CallStatus.DESCONECTADO)

    def _on_ws_error(self, message: str) -> None:
        self.error_occurred.emit(message)

    def _on_signal(self, msg: dict) -> None:
        mtype = msg.get("type")

        if mtype == "room_created":
            self._room_id = msg.get("roomId")
            self._set_status(CallStatus.ESPERANDO_PEER)
            self.room_created.emit(msg.get("roomId", ""), msg.get("password", ""), msg.get("expiresAt"))

        elif mtype == "join_ok":
            self._room_id = msg.get("roomId", self._room_id)
            self._set_status(CallStatus.NEGOCIANDO_CLAVES)
            self.join_result.emit(True, "")
            self._start_key_exchange()

        elif mtype == "join_error":
            self.join_result.emit(False, msg.get("reason", "desconocido"))
            self._set_status(CallStatus.DESCONECTADO)

        elif mtype == "peer_joined":
            self.peer_joined.emit()
            self._set_status(CallStatus.NEGOCIANDO_CLAVES)
            self._start_key_exchange()

        elif mtype == "peer_left":
            self.peer_left.emit()
            self._teardown(reason="el_otro_usuario_salio")

        elif mtype == "key_exchange":
            self._received_peer_key = True
            self._session.derive_shared_key(msg.get("publicKey", ""), self._room_id or "")
            self._maybe_start_call()

        elif mtype == "call_end":
            self._teardown(reason="el_otro_usuario_colgo")

        elif mtype == "mute_state":
            self.peer_mute_changed.emit(bool(msg.get("audio")), bool(msg.get("video")))

        elif mtype == "error":
            self.error_occurred.emit(msg.get("message", "Error del servidor"))

    def _start_key_exchange(self) -> None:
        if self._sent_own_key or self._ws is None:
            return
        pub_b64 = self._session.generate_keypair()
        self._ws.send_signal(protocol.key_exchange_msg(pub_b64))
        self._sent_own_key = True
        self._maybe_start_call()

    def _maybe_start_call(self) -> None:
        if self._session.ready and self._status != CallStatus.EN_LLAMADA:
            self._begin_media()

    def _begin_media(self) -> None:
        self._set_status(CallStatus.EN_LLAMADA)
        if self._ws is not None:
            self._ws.send_signal(protocol.call_start_msg())

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
        if not self._session.ready or self._ws is None:
            return
        self._video_seq += 1
        nonce8 = SessionKeyManager.new_nonce8()
        ciphertext = self._session.encrypt(self._video_seq, nonce8, webp_bytes)
        frame = protocol.MediaFrame(protocol.MediaType.VIDEO, self._video_seq, _now_ms(), nonce8, ciphertext)
        self._ws.send_media(frame.pack())

    def _on_local_audio_frame(self, opus_bytes: bytes) -> None:
        if not self._session.ready or self._ws is None:
            return
        self._audio_seq += 1
        nonce8 = SessionKeyManager.new_nonce8()
        ciphertext = self._session.encrypt(self._audio_seq, nonce8, opus_bytes)
        frame = protocol.MediaFrame(protocol.MediaType.AUDIO, self._audio_seq, _now_ms(), nonce8, ciphertext)
        self._ws.send_media(frame.pack())

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

    def _broadcast_mute_state(self) -> None:
        if self._ws is not None and self._status == CallStatus.EN_LLAMADA:
            self._ws.send_signal(protocol.mute_state_msg(self._mic_muted, self._camera_off))

    def _teardown(self, reason: str) -> None:
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

        if self._ws is not None:
            self._ws.stop()
            self._ws.wait(1000)
            self._ws = None

        self._sent_own_key = False
        self._received_peer_key = False
        self._video_seq = 0
        self._audio_seq = 0
        self._room_id = None
        self._set_status(CallStatus.IDLE)
        self.call_ended.emit(reason)


def _now_ms() -> int:
    return int(time.time() * 1000)
