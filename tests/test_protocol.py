import time
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.network.protocol import (
    MediaFrame, MediaType, HEADER_SIZE,
    encode_signal, decode_signal,
    auth_request_msg, call_request_msg, call_accepted_msg, call_rejected_msg,
    call_ended_msg, heartbeat_msg,
    control_payload, parse_control_payload,
    pack_length_prefixed, unpack_length_prefix, LENGTH_PREFIX_SIZE,
    TYPE_AUTH_REQUEST, TYPE_CALL_REQUEST,
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


def test_media_frame_control_type():
    frame = MediaFrame(MediaType.CONTROL, 1, 0, b"\x00" * 8, b"ciphertext")
    parsed = MediaFrame.unpack(frame.pack())
    assert parsed.media_type == MediaType.CONTROL


def test_unpack_too_short_raises():
    try:
        MediaFrame.unpack(b"short")
        assert False, "debería haber lanzado ValueError"
    except ValueError:
        pass


def test_control_payload_roundtrip():
    raw = control_payload(True, False)
    audio_muted, video_muted = parse_control_payload(raw)
    assert audio_muted is True
    assert video_muted is False


def test_length_prefix_roundtrip():
    payload = b"algunos bytes de un MediaFrame empacado"
    framed = pack_length_prefixed(payload)
    assert len(framed) == LENGTH_PREFIX_SIZE + len(payload)
    length = unpack_length_prefix(framed[:LENGTH_PREFIX_SIZE])
    assert length == len(payload)
    assert framed[LENGTH_PREFIX_SIZE:] == payload


def test_signal_envelope_roundtrip():
    msg_type, payload = auth_request_msg("user123", "cap_abc")
    raw = encode_signal(msg_type, payload)
    decoded_type, decoded_payload = decode_signal(raw)
    assert decoded_type == TYPE_AUTH_REQUEST
    assert decoded_payload == {"user_id": "user123", "captcha_token": "cap_abc"}


def test_call_request_msg_fields():
    msg_type, payload = call_request_msg("call-1", "target-user", "video")
    assert msg_type == TYPE_CALL_REQUEST
    assert payload["call_id"] == "call-1"
    assert payload["target_user_id"] == "target-user"
    assert payload["call_type"] == "video"


def test_call_accepted_and_ended_msg_fields():
    _, accepted_payload = call_accepted_msg("call-1")
    assert accepted_payload == {"call_id": "call-1"}
    _, ended_payload = call_ended_msg("call-1")
    assert ended_payload == {"call_id": "call-1"}


def test_call_rejected_msg_optional_reason():
    _, payload = call_rejected_msg("call-1")
    assert payload == {"call_id": "call-1"}
    _, payload_with_reason = call_rejected_msg("call-1", "busy")
    assert payload_with_reason == {"call_id": "call-1", "reason": "busy"}


def test_heartbeat_msg_fields():
    _, payload = heartbeat_msg(1751385600123)
    assert payload == {"ts": 1751385600123}


def test_decode_signal_missing_type_raises():
    try:
        decode_signal('{"foo": "bar"}')
        assert False, "debería haber lanzado ValueError"
    except ValueError:
        pass


def test_decode_signal_without_payload():
    msg_type, payload = decode_signal('{"type":"AUTH_OK"}')
    assert msg_type == "AUTH_OK"
    assert payload == {}
