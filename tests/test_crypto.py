import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.security.ephemeral import SessionKeyManager, SessionNotReady


def test_ecdh_hkdf_aesgcm_roundtrip():
    a = SessionKeyManager()
    b = SessionKeyManager()

    pub_a = a.generate_keypair()
    pub_b = b.generate_keypair()

    a.derive_shared_key(pub_b, room_id="room-1")
    b.derive_shared_key(pub_a, room_id="room-1")

    assert a.ready and b.ready

    nonce = SessionKeyManager.new_nonce8()
    plaintext = b"frame de video de prueba"
    ciphertext = a.encrypt(seq=7, nonce8=nonce, plaintext=plaintext)
    assert ciphertext != plaintext

    recovered = b.decrypt(seq=7, nonce8=nonce, ciphertext=ciphertext)
    assert recovered == plaintext


def test_different_rooms_derive_different_keys():
    a1, b1 = SessionKeyManager(), SessionKeyManager()
    pa, pb = a1.generate_keypair(), b1.generate_keypair()
    a1.derive_shared_key(pb, room_id="room-A")
    b1.derive_shared_key(pa, room_id="room-B")

    nonce = SessionKeyManager.new_nonce8()
    ct = a1.encrypt(1, nonce, b"secreto")
    try:
        b1.decrypt(1, nonce, ct)
        assert False, "no deberia poder descifrar con una clave derivada de otra sala"
    except Exception:
        pass


def test_encrypt_before_ready_raises():
    a = SessionKeyManager()
    try:
        a.encrypt(1, b"\x00" * 8, b"x")
        assert False
    except SessionNotReady:
        pass


def test_purge_clears_state():
    a = SessionKeyManager()
    b = SessionKeyManager()
    a.generate_keypair()
    a.derive_shared_key(b.generate_keypair(), room_id="r")
    assert a.ready
    a.purge()
    assert not a.ready
