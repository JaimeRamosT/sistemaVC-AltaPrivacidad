import time
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.network.protocol import (
    MediaFrame, MediaType, HEADER_SIZE,
    encode_signal, decode_signal, create_room_msg, join_room_msg, key_exchange_msg,
)


def test_media_frame_roundtrip():
    frame = MediaFrame(
        media_type=MediaType.VIDEO,
        seq=42,
        ts_ms=int(time.time() * 1000),
        nonce8=b"12345678",
        ciphertext=b"payload-bytes-xyz",
    )
    raw = frame.pack()
    assert len(raw) - len(frame.ciphertext) == HEADER_SIZE == 21

    parsed = MediaFrame.unpack(raw)
    assert parsed.media_type == MediaType.VIDEO
    assert parsed.seq == 42
    assert parsed.ts_ms == frame.ts_ms
    assert parsed.nonce8 == b"12345678"
    assert parsed.ciphertext == b"payload-bytes-xyz"


def test_media_frame_audio_type():
    frame = MediaFrame(MediaType.AUDIO, 1, 0, b"\x00" * 8, b"opus-packet")
    parsed = MediaFrame.unpack(frame.pack())
    assert parsed.media_type == MediaType.AUDIO


def test_unpack_too_short_raises():
    try:
        MediaFrame.unpack(b"short")
        assert False, "debería haber lanzado ValueError"
    except ValueError:
        pass


def test_signal_roundtrip():
    msg = create_room_msg()
    raw = encode_signal(msg)
    assert decode_signal(raw) == msg


def test_join_room_msg_fields():
    msg = join_room_msg("482913", "k3f9-qz2p")
    assert msg["type"] == "join_room"
    assert msg["roomId"] == "482913"
    assert msg["password"] == "k3f9-qz2p"


def test_key_exchange_msg_fields():
    msg = key_exchange_msg("base64stuff==")
    assert msg["type"] == "key_exchange"
    assert msg["publicKey"] == "base64stuff=="


def test_decode_signal_missing_type_raises():
    try:
        decode_signal('{"foo": "bar"}')
        assert False, "debería haber lanzado ValueError"
    except ValueError:
        pass
