import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
from app import config
from app.media.webp_codec import encode_webp, decode_webp


def _synthetic_frame(h=360, w=640):
    x = np.linspace(0, 255, w, dtype=np.uint8)
    img = np.tile(x, (h, 1))
    frame = np.stack([img, np.roll(img, 100), np.roll(img, 200)], axis=-1).astype(np.uint8)
    noise = (np.random.rand(h, w, 3) * 40).astype(np.uint8)
    return np.clip(frame.astype(int) + noise, 0, 255).astype(np.uint8)


def test_encode_respects_max_frame_bytes():
    frame = _synthetic_frame()
    data = encode_webp(frame)
    assert len(data) <= config.VIDEO_MAX_FRAME_BYTES


def test_encode_decode_roundtrip_shape():
    frame = _synthetic_frame()
    data = encode_webp(frame)
    back = decode_webp(data)
    assert back.shape == frame.shape
    assert back.dtype == frame.dtype
