"""
Serialización del protocolo descrito en protocol/PROTOCOL.md.

Este módulo es la ÚNICA parte del cliente que conoce el formato exacto de
los mensajes. Si el backend real usa nombres de campo distintos, basta con
ajustar las funciones de aquí.
"""
from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from enum import IntEnum
from typing import Any


# ---------------------------------------------------------------------------
# Mensajes de señalización (JSON / frames de texto)
# ---------------------------------------------------------------------------

def encode_signal(msg: dict[str, Any]) -> str:
    """dict -> JSON compacto listo para enviar como frame de texto."""
    return json.dumps(msg, separators=(",", ":"))


def decode_signal(raw: str) -> dict[str, Any]:
    """JSON recibido -> dict. Lanza ValueError si el mensaje es inválido."""
    data = json.loads(raw)
    if not isinstance(data, dict) or "type" not in data:
        raise ValueError("Mensaje de señalización sin campo 'type'")
    return data


def create_room_msg() -> dict:
    return {"type": "create_room"}


def join_room_msg(room_id: str, password: str) -> dict:
    return {"type": "join_room", "roomId": room_id, "password": password}


def key_exchange_msg(public_key_b64: str) -> dict:
    return {"type": "key_exchange", "publicKey": public_key_b64}


def call_start_msg() -> dict:
    return {"type": "call_start"}


def call_end_msg() -> dict:
    return {"type": "call_end"}


def mute_state_msg(audio_muted: bool, video_muted: bool) -> dict:
    return {"type": "mute_state", "audio": audio_muted, "video": video_muted}


def ping_msg(ts_ms: int) -> dict:
    return {"type": "ping", "ts": ts_ms}


def pong_msg(ts_ms: int) -> dict:
    return {"type": "pong", "ts": ts_ms}


# ---------------------------------------------------------------------------
# Frames binarios de media
# ---------------------------------------------------------------------------

class MediaType(IntEnum):
    VIDEO = 0x01
    AUDIO = 0x02


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
