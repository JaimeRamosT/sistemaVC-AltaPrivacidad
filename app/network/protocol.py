"""
Serialización del protocolo real del backend TorZoom (ver
`manager/protocol/messages.go` y `manager/internal/signaling/handler.go`
en el repo `Anonymized-video-calls-over-the-Tor-network`).

Este módulo es la ÚNICA parte del cliente que conoce el formato exacto de
los mensajes de señalización. Si el backend cambia nombres de campo, basta
con ajustar las funciones de aquí.

Diferencia clave frente al borrador original (`protocol/PROTOCOL.md`): el
backend real solo entiende un conjunto FIJO de tipos de mensaje (no hay un
"reenvía esto tal cual al otro peer" genérico como en `mock_server`). Por
eso el intercambio de clave de sesión (X25519) y el estado de mute ya NO
viajan por el WebSocket de señalización: viajan por la conexión TCP directa
al relay de media (ver `relay_client.py`), que sí es un pipe de bytes
transparente entre los dos clientes de una llamada.
"""
from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from enum import IntEnum
from typing import Any


# ---------------------------------------------------------------------------
# Mensajes de señalización (JSON / frames de texto), envelope {type, payload}
# ---------------------------------------------------------------------------

# Cliente -> Servidor
TYPE_AUTH_REQUEST = "AUTH_REQUEST"
TYPE_CALL_REQUEST = "CALL_REQUEST"
TYPE_CALL_ACCEPTED = "CALL_ACCEPTED"
TYPE_CALL_REJECTED = "CALL_REJECTED"
TYPE_CALL_ENDED = "CALL_ENDED"
TYPE_HEARTBEAT = "HEARTBEAT"

# Servidor -> Cliente
TYPE_AUTH_OK = "AUTH_OK"
TYPE_AUTH_FAIL = "AUTH_FAIL"
TYPE_INCOMING_CALL = "INCOMING_CALL"
TYPE_ROOM_ASSIGNED = "ROOM_ASSIGNED"
TYPE_CALL_BUSY = "CALL_BUSY"
TYPE_USER_OFFLINE = "USER_OFFLINE"
TYPE_CALL_CANCELED = "CALL_CANCELED"
TYPE_ERROR = "ERROR"
TYPE_HEARTBEAT_ACK = "HEARTBEAT_ACK"


def encode_signal(msg_type: str, payload: dict | None = None) -> str:
    """(type, payload) -> JSON compacto listo para enviar como frame de texto.

    El backend envuelve todo como {"type": ..., "payload": {...}}, a
    diferencia del formato plano del borrador original.
    """
    envelope: dict[str, Any] = {"type": msg_type}
    if payload is not None:
        envelope["payload"] = payload
    return json.dumps(envelope, separators=(",", ":"))


def decode_signal(raw: str) -> tuple[str, dict]:
    """JSON recibido -> (type, payload dict). Lanza ValueError si es inválido."""
    data = json.loads(raw)
    if not isinstance(data, dict) or "type" not in data:
        raise ValueError("Mensaje de señalización sin campo 'type'")
    payload = data.get("payload") or {}
    if not isinstance(payload, dict):
        raise ValueError("Campo 'payload' no es un objeto")
    return data["type"], payload


# -- Constructores de mensajes Cliente -> Servidor --------------------------

def auth_request_msg(user_id: str, captcha_token: str) -> tuple[str, dict]:
    return TYPE_AUTH_REQUEST, {"user_id": user_id, "captcha_token": captcha_token}


def call_request_msg(call_id: str, target_user_id: str, call_type: str = "video") -> tuple[str, dict]:
    return TYPE_CALL_REQUEST, {"call_id": call_id, "target_user_id": target_user_id, "call_type": call_type}


def call_accepted_msg(call_id: str) -> tuple[str, dict]:
    return TYPE_CALL_ACCEPTED, {"call_id": call_id}


def call_rejected_msg(call_id: str, reason: str = "") -> tuple[str, dict]:
    payload: dict[str, Any] = {"call_id": call_id}
    if reason:
        payload["reason"] = reason
    return TYPE_CALL_REJECTED, payload


def call_ended_msg(call_id: str) -> tuple[str, dict]:
    return TYPE_CALL_ENDED, {"call_id": call_id}


def heartbeat_msg(ts_ms: int) -> tuple[str, dict]:
    return TYPE_HEARTBEAT, {"ts": ts_ms}


# ---------------------------------------------------------------------------
# Frames binarios de media (sin cambios de formato: siguen siendo
# transporte-agnósticos, ahora viajan por relay_client.py en vez de por WS)
# ---------------------------------------------------------------------------

class MediaType(IntEnum):
    VIDEO = 0x01
    AUDIO = 0x02
    CONTROL = 0x03   # mute_state y similares (ver control_frame_payload)


# type(1) + seq(4) + ts_ms(8) + nonce(8) = 21 bytes de cabecera
_HEADER_FMT = ">BIQ8s"
_HEADER_SIZE = struct.calcsize(_HEADER_FMT)
assert _HEADER_SIZE == 21


@dataclass
class MediaFrame:
    media_type: MediaType
    seq: int
    ts_ms: int
    nonce8: bytes          # 8 bytes aleatorios, ver security/ephemeral.py
    ciphertext: bytes      # payload cifrado (incluye tag GCM al final)

    def pack(self) -> bytes:
        header = struct.pack(_HEADER_FMT, int(self.media_type), self.seq & 0xFFFFFFFF,
                              self.ts_ms & 0xFFFFFFFFFFFFFFFF, self.nonce8)
        return header + self.ciphertext

    @staticmethod
    def unpack(raw: bytes) -> "MediaFrame":
        if len(raw) < _HEADER_SIZE:
            raise ValueError("Frame binario demasiado corto")
        media_type, seq, ts_ms, nonce8 = struct.unpack(_HEADER_FMT, raw[:_HEADER_SIZE])
        ciphertext = raw[_HEADER_SIZE:]
        return MediaFrame(MediaType(media_type), seq, ts_ms, nonce8, ciphertext)


HEADER_SIZE = _HEADER_SIZE


def control_payload(audio_muted: bool, video_muted: bool) -> bytes:
    """Payload en claro (antes de cifrar) para un MediaFrame de tipo CONTROL.

    El estado de mute ya no se señaliza vía WebSocket (el backend real no
    tiene un mensaje genérico para reenviar datos de app entre peers), así
    que viaja cifrado dentro de un MediaFrame más por el canal de relay.
    """
    return json.dumps({"audio_muted": audio_muted, "video_muted": video_muted},
                       separators=(",", ":")).encode("utf-8")


def parse_control_payload(raw: bytes) -> tuple[bool, bool]:
    data = json.loads(raw.decode("utf-8"))
    return bool(data.get("audio_muted")), bool(data.get("video_muted"))


# ---------------------------------------------------------------------------
# Framing de longitud para el canal de relay (TCP crudo, sin límites de
# mensaje propios -- a diferencia de un frame binario de WebSocket, que ya
# viene delimitado por el transporte).
# ---------------------------------------------------------------------------

_LENGTH_FMT = ">I"
LENGTH_PREFIX_SIZE = struct.calcsize(_LENGTH_FMT)


def pack_length_prefixed(payload: bytes) -> bytes:
    return struct.pack(_LENGTH_FMT, len(payload)) + payload


def unpack_length_prefix(header: bytes) -> int:
    return struct.unpack(_LENGTH_FMT, header)[0]
