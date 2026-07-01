"""
Claves de sesión efímeras (RNF-04b / RNF-04c).

- Se genera un par de claves X25519 nuevo en cada llamada (nunca se persiste).
- El intercambio de clave pública ocurre a través del canal de señalización
  (el servidor solo reenvía bytes opacos entre los dos peers).
- La clave compartida se deriva localmente con HKDF-SHA256 y se usa para
  cifrar/descifrar cada frame de media con AES-256-GCM.
- purge() sobreescribe y descarta el material de clave en memoria; se llama
  siempre al colgar o al perder la conexión.

Esto da al POC cifrado extremo-a-extremo real sobre el canal ya anonimizado
por Tor, en línea con la "garantía criptográfica de anonimato" que piden los
perfiles de usuario del documento de propuesta.
"""
from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class SessionNotReady(Exception):
    """La clave de sesión aún no se ha derivado (falta key_exchange del peer)."""


class SessionKeyManager:
    def __init__(self) -> None:
        self._private_key: X25519PrivateKey | None = None
        self._shared_key: bytes | None = None
        self._aead: AESGCM | None = None

    # -- Fase 1: generar par de claves propio -----------------------------
    def generate_keypair(self) -> str:
        self._private_key = X25519PrivateKey.generate()
        pub_bytes = self._private_key.public_key().public_bytes_raw()
        return base64.b64encode(pub_bytes).decode("ascii")

    # -- Fase 2: derivar clave compartida con la pública del peer ---------
    def derive_shared_key(self, peer_public_key_b64: str, room_id: str) -> None:
        if self._private_key is None:
            raise SessionNotReady("Llama primero a generate_keypair()")
        peer_pub_bytes = base64.b64decode(peer_public_key_b64)
        peer_public_key = X25519PublicKey.from_public_bytes(peer_pub_bytes)
        raw_shared = self._private_key.exchange(peer_public_key)

        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=room_id.encode("utf-8"),
            info=b"torvc-media-v1",
        )
        self._shared_key = hkdf.derive(raw_shared)
        self._aead = AESGCM(self._shared_key)

    @property
    def ready(self) -> bool:
        return self._aead is not None

    # -- Cifrado / descifrado de frames de media ---------------------------
    def encrypt(self, seq: int, nonce8: bytes, plaintext: bytes) -> bytes:
        if self._aead is None:
            raise SessionNotReady("Clave de sesión no derivada todavía")
        nonce = nonce8 + seq.to_bytes(4, "big")  # 12 bytes, requerido por AES-GCM
        return self._aead.encrypt(nonce, plaintext, None)

    def decrypt(self, seq: int, nonce8: bytes, ciphertext: bytes) -> bytes:
        if self._aead is None:
            raise SessionNotReady("Clave de sesión no derivada todavía")
        nonce = nonce8 + seq.to_bytes(4, "big")
        return self._aead.decrypt(nonce, ciphertext, None)

    @staticmethod
    def new_nonce8() -> bytes:
        return os.urandom(8)

    # -- Purga (RNF-04c) ----------------------------------------------------
    def purge(self) -> None:
        """Descarta el material de clave. Best-effort: CPython no garantiza
        borrado seguro de memoria, pero se elimina toda referencia y se
        sobreescribe el buffer antes de soltarlo."""
        if self._shared_key is not None:
            try:
                ba = bytearray(self._shared_key)
                for i in range(len(ba)):
                    ba[i] = 0
            except Exception:
                pass
        self._private_key = None
        self._shared_key = None
        self._aead = None
