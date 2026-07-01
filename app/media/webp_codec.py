"""
Codificación/decodificación de frames de video como WebP (RNF-03e).

Módulo puro (sin Qt) para que sea fácil de testear de forma aislada.
"""
from __future__ import annotations

import io

import numpy as np
from PIL import Image

from .. import config


def encode_webp(frame_rgb: np.ndarray) -> bytes:
    """Comprime un frame RGB a WebP, bajando calidad si excede el límite de
    bytes por frame (RNF-03b: video liviano para no saturar el circuito Tor)."""
    img = Image.fromarray(frame_rgb)
    quality = config.VIDEO_WEBP_QUALITY_START
    data = b""
    while True:
        buf = io.BytesIO()
        img.save(buf, format="WEBP", quality=quality, method=4)
        data = buf.getvalue()
        if len(data) <= config.VIDEO_MAX_FRAME_BYTES or quality <= 10:
            return data
        quality -= 10


def decode_webp(data: bytes) -> np.ndarray:
    img = Image.open(io.BytesIO(data)).convert("RGB")
    return np.array(img)
