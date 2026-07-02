#!/usr/bin/env python3
"""
Servidor de prueba LOCAL (sin Tor, sin Docker, sin direcciones .onion reales)
que simula el backend real de TorZoom (repo
`Anonymized-video-calls-over-the-Tor-network`: `manager/` + `tcp-relay/`, ver
`protocol/PROTOCOL.md`) lo suficiente como para que el cliente actual
(`app/network/protocol.py`, `app/network/ws_client.py`,
`app/network/relay_client.py`, `app/call_controller.py`) complete una llamada
de punta a punta contra `localhost`.

Corre dos servidores asyncio en el mismo proceso:

  1. HTTP + WebSocket de señalización (aiohttp), en `--host:--port`
     (default 127.0.0.1:8765):
       - `POST /api/captcha/challenge` -> `{"captcha_token": "cap_..."}`.
         Igual que el manager real en modo desarrollo (`CaptchaEnabled=false`
         en `auth.Service.ValidateCaptcha`), el valor no se valida de verdad
         mas que "no viene vacio".
       - `GET /ws`: mismo envelope `{"type", "payload"}` del backend real.
         Entiende `AUTH_REQUEST`, `CALL_REQUEST`, `CALL_ACCEPTED`,
         `CALL_ENDED` y `HEARTBEAT` -- ver `manager/internal/signaling/
         handler.go` para la logica que se replica aqui (con presencia y
         llamadas en memoria en vez de Redis, sin JWT ni rate limiting real).

  2. Relay TCP crudo de media, en `--host:--relay-port` (default
     127.0.0.1:9001): acepta 2 conexiones, valida solo el prefijo `tzr_` del
     token recibido (no el contenido -- zero-knowledge, igual que el real) y
     hace un bridge de bytes puro y bidireccional entre ambas hasta que una
     de las dos se cierra, igual que `tcp-relay/main.go`. A diferencia de
     ese binario (que corre en un contenedor desechable por llamada), este
     proceso vuelve a aceptar el siguiente par de conexiones al terminar
     cada sesion, para no tener que reiniciar el mock entre llamadas de
     prueba sucesivas.

Simplificaciones deliberadas frente al backend real (aceptables solo para
pruebas locales):
  - Todo el estado (presencia, llamadas en curso, "ocupado") vive en
    diccionarios en memoria de un unico proceso -- no hay Redis ni multiples
    instancias del manager.
  - No hay Docker ni Tor: siempre hay un unico relay en el puerto fijo
    indicado, no un contenedor efimero por llamada. El `onion_address` de
    `ROOM_ASSIGNED` es un placeholder que el cliente ignora en modo
    `TORVC_DEV_NO_TOR=1` (usa `127.0.0.1` + el `port` recibido, ver
    `call_controller._on_room_assigned`).
  - El captcha y la autenticacion no se validan de verdad, solo se exige que
    `user_id` y `captcha_token` no vengan vacios.

Uso (junto con el cliente en modo sin Tor):
    python mock_server/server.py --host 127.0.0.1 --port 8765 --relay-port 9001

En otra terminal, por cada participante de la llamada:
    TORVC_DEV_NO_TOR=1 TORVC_SERVER_URL=ws://127.0.0.1:8765/ws python run.py
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import secrets
import time
from dataclasses import dataclass

from aiohttp import web, WSMsgType

logging.basicConfig(level=logging.INFO, format="[mock-server] %(message)s")
log = logging.getLogger("mock_server")

RELAY_TOKEN_PREFIX = "tzr_"
RELAY_MAX_SESSION_SECONDS = 4 * 60 * 60  # igual que tcp-relay/main.go
FAKE_ONION_ADDRESS = "mock-relay-no-tor.local.onion"  # ignorado con TORVC_DEV_NO_TOR=1

# Puerto del relay de media anunciado en ROOM_ASSIGNED. Se fija una sola vez
# al arrancar (ver main()); no hay pool de puertos como en el orchestrator
# real porque este mock sirve un unico relay fijo.
RELAY_PORT = 9001


# ---------------------------------------------------------------------------
# Envelope {type, payload} -- igual formato que manager/protocol/messages.go
# ---------------------------------------------------------------------------

def _envelope(msg_type: str, payload: dict | None = None) -> dict:
    env: dict = {"type": msg_type}
    if payload is not None:
        env["payload"] = payload
    return env


def _decode(raw: str) -> tuple[str, dict]:
    data = json.loads(raw)
    if not isinstance(data, dict) or "type" not in data:
        raise ValueError("mensaje sin campo 'type'")
    payload = data.get("payload") or {}
    if not isinstance(payload, dict):
        raise ValueError("campo 'payload' no es un objeto")
    return data["type"], payload


def _now_ms() -> int:
    return int(time.time() * 1000)


async def send(ws: web.WebSocketResponse, msg_type: str, payload: dict | None = None) -> None:
    if ws.closed:
        return
    try:
        await ws.send_json(_envelope(msg_type, payload))
    except (ConnectionResetError, RuntimeError):
        pass


# ---------------------------------------------------------------------------
# Estado en memoria (equivalente simplificado de presence.Registry + Redis)
# ---------------------------------------------------------------------------

class ClientSession:
    __slots__ = ("ws", "user_id", "authed")

    def __init__(self, ws: web.WebSocketResponse):
        self.ws = ws
        self.user_id = ""
        self.authed = False


@dataclass
class CallRecord:
    call_id: str
    caller_id: str
    callee_id: str
    call_type: str
    state: str = "ringing"


PRESENCE: dict[str, web.WebSocketResponse] = {}   # user_id -> conexion online
BUSY: dict[str, str] = {}                          # user_id -> call_id activo
CALLS: dict[str, CallRecord] = {}                  # call_id -> registro de llamada


def _gen_relay_token() -> str:
    return RELAY_TOKEN_PREFIX + secrets.token_hex(16)


# ---------------------------------------------------------------------------
# Handlers de señalización (uno por tipo de mensaje Cliente -> Servidor)
# ---------------------------------------------------------------------------

async def handle_auth_request(session: ClientSession, payload: dict) -> None:
    user_id = payload.get("user_id", "")
    captcha_token = payload.get("captcha_token", "")
    if not user_id:
        await send(session.ws, "ERROR", {"code": "INVALID_PAYLOAD", "message": "user_id is required"})
        return
    if not captcha_token:
        await send(session.ws, "AUTH_FAIL", {"reason": "invalid_captcha"})
        return

    session.user_id = user_id
    session.authed = True
    PRESENCE[user_id] = session.ws
    log.info("cliente autenticado: %s", user_id)
    await send(session.ws, "AUTH_OK", {"user_id": user_id, "server_ts": _now_ms()})


async def handle_call_request(session: ClientSession, payload: dict) -> None:
    call_id = payload.get("call_id", "")
    target_user_id = payload.get("target_user_id", "")
    call_type = payload.get("call_type", "video")
    if not call_id or not target_user_id:
        await send(session.ws, "ERROR", {
            "code": "INVALID_PAYLOAD", "message": "call_id and target_user_id are required",
        })
        return

    if session.user_id in BUSY:
        await send(session.ws, "ERROR", {
            "code": "ALREADY_IN_CALL", "message": f"you are already in a call: {BUSY[session.user_id]}",
        })
        return

    target_ws = PRESENCE.get(target_user_id)
    if target_ws is None:
        await send(session.ws, "USER_OFFLINE", {"target_user_id": target_user_id, "call_id": call_id})
        return

    if target_user_id in BUSY:
        await send(session.ws, "CALL_BUSY", {"target_user_id": target_user_id, "call_id": call_id})
        return

    CALLS[call_id] = CallRecord(call_id, session.user_id, target_user_id, call_type)
    BUSY[session.user_id] = call_id
    log.info("llamada %s: %s -> %s (ringing)", call_id, session.user_id, target_user_id)

    await send(target_ws, "INCOMING_CALL", {
        "call_id": call_id, "caller_user_id": session.user_id, "call_type": call_type,
    })


async def handle_call_accepted(session: ClientSession, payload: dict) -> None:
    call_id = payload.get("call_id", "")
    call = CALLS.get(call_id)
    if call is None:
        await send(session.ws, "ERROR", {"code": "CALL_NOT_FOUND", "message": f"call {call_id} not found"})
        return
    if call.callee_id != session.user_id:
        await send(session.ws, "ERROR", {"code": "FORBIDDEN", "message": "you are not the callee for this call"})
        return
    if call.state != "ringing":
        await send(session.ws, "ERROR", {"code": "INVALID_STATE", "message": "call is not in ringing state"})
        return

    BUSY[session.user_id] = call_id
    call.state = "active"

    caller_token = _gen_relay_token()
    callee_token = _gen_relay_token()
    log.info("sala asignada para %s: puerto %d", call_id, RELAY_PORT)

    await send(session.ws, "ROOM_ASSIGNED", {
        "call_id": call_id, "onion_address": FAKE_ONION_ADDRESS, "port": RELAY_PORT,
        "role": "responder", "token": callee_token,
    })

    caller_ws = PRESENCE.get(call.caller_id)
    if caller_ws is not None:
        await send(caller_ws, "ROOM_ASSIGNED", {
            "call_id": call_id, "onion_address": FAKE_ONION_ADDRESS, "port": RELAY_PORT,
            "role": "initiator", "token": caller_token,
        })


async def handle_call_ended(session: ClientSession, payload: dict) -> None:
    call_id = payload.get("call_id", "")
    call = CALLS.pop(call_id, None)
    if call is None:
        return

    BUSY.pop(call.caller_id, None)
    BUSY.pop(call.callee_id, None)

    other_id = call.callee_id if session.user_id == call.caller_id else call.caller_id
    other_ws = PRESENCE.get(other_id)
    if other_ws is not None:
        await send(other_ws, "CALL_ENDED", {"call_id": call_id})
    log.info("llamada %s finalizada por %s", call_id, session.user_id)


async def handle_heartbeat(session: ClientSession, payload: dict) -> None:
    await send(session.ws, "HEARTBEAT_ACK", {
        "client_ts": payload.get("ts", 0), "server_ts": _now_ms(),
    })


DISPATCH = {
    "AUTH_REQUEST": handle_auth_request,
    "CALL_REQUEST": handle_call_request,
    "CALL_ACCEPTED": handle_call_accepted,
    "CALL_ENDED": handle_call_ended,
    "HEARTBEAT": handle_heartbeat,
}


# ---------------------------------------------------------------------------
# HTTP: captcha + upgrade a WebSocket
# ---------------------------------------------------------------------------

async def captcha_challenge(request: web.Request) -> web.Response:
    token = "cap_" + secrets.token_hex(16)
    return web.json_response({"captcha_token": token})


async def websocket_handler(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse(heartbeat=15)
    await ws.prepare(request)
    session = ClientSession(ws)
    log.info("nueva conexion desde %s", request.remote)

    async for msg in ws:
        if msg.type == WSMsgType.TEXT:
            try:
                msg_type, payload = _decode(msg.data)
            except ValueError as exc:
                await send(ws, "ERROR", {"code": "INVALID_PAYLOAD", "message": str(exc)})
                continue

            if not session.authed and msg_type != "AUTH_REQUEST":
                await send(ws, "ERROR", {"code": "UNAUTHENTICATED", "message": "must send AUTH_REQUEST first"})
                continue

            handler = DISPATCH.get(msg_type)
            if handler is None:
                await send(ws, "ERROR", {"code": "UNKNOWN_TYPE", "message": f"unknown message type: {msg_type}"})
                continue
            await handler(session, payload)

        elif msg.type == WSMsgType.BINARY:
            # El backend real no tiene un canal generico de reenvio de datos
            # de aplicacion: la media viaja por el relay TCP (ver mas abajo),
            # nunca por este WebSocket.
            log.warning("frame binario recibido por WS de señalizacion (ignorado): %s", session.user_id)

        elif msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE, WSMsgType.CLOSING):
            break

    if session.authed:
        PRESENCE.pop(session.user_id, None)
        log.info("cliente desconectado: %s", session.user_id)

    return ws


def build_app() -> web.Application:
    app = web.Application()
    app.router.add_post("/api/captcha/challenge", captcha_challenge)
    app.router.add_get("/ws", websocket_handler)
    return app


# ---------------------------------------------------------------------------
# Relay TCP de media -- equivalente minimo de tcp-relay/main.go
# ---------------------------------------------------------------------------

_pending_peer: tuple[asyncio.StreamReader, asyncio.StreamWriter] | None = None
_pending_lock = asyncio.Lock()


async def _handshake_token(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> bool:
    """Lee la linea de token (5s de deadline) y valida solo el prefijo,
    exactamente como `acceptWithToken` en tcp-relay/main.go: el relay no
    puede verificar el contenido, la identidad ya la validaron
    AUTH_REQUEST/CALL_ACCEPTED."""
    try:
        line = await asyncio.wait_for(reader.readline(), timeout=5)
    except asyncio.TimeoutError:
        return False
    token = line.decode("ascii", errors="ignore").strip()
    if not token.startswith(RELAY_TOKEN_PREFIX):
        return False
    writer.write(b"OK\n")
    await writer.drain()
    return True


async def _pump(src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
    try:
        while True:
            data = await src.read(65536)
            if not data:
                break
            dst.write(data)
            await dst.drain()
    except (ConnectionResetError, ConnectionAbortedError, OSError):
        pass
    finally:
        try:
            dst.write_eof()
        except (OSError, RuntimeError):
            pass


async def _bridge(
    reader_a: asyncio.StreamReader, writer_a: asyncio.StreamWriter,
    reader_b: asyncio.StreamReader, writer_b: asyncio.StreamWriter,
) -> None:
    """Bridge de bytes puro y bidireccional, sin inspeccionar ni bufferear
    contenido -- equivalente a `bridge()` en tcp-relay/main.go."""
    try:
        await asyncio.wait_for(
            asyncio.gather(_pump(reader_a, writer_b), _pump(reader_b, writer_a)),
            timeout=RELAY_MAX_SESSION_SECONDS,
        )
    except asyncio.TimeoutError:
        log.warning("sesion de relay alcanzo el limite de %ds, cerrando", RELAY_MAX_SESSION_SECONDS)
    finally:
        writer_a.close()
        writer_b.close()


async def _relay_connection_handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    global _pending_peer

    peer_addr = writer.get_extra_info("peername")
    if not await _handshake_token(reader, writer):
        log.warning("conexion de relay rechazada (token invalido) desde %s", peer_addr)
        writer.close()
        return

    async with _pending_lock:
        if _pending_peer is None:
            _pending_peer = (reader, writer)
            log.info("peer A conectado al relay desde %s, esperando peer B", peer_addr)
            return
        peer_reader, peer_writer = _pending_peer
        _pending_peer = None

    log.info("peer B conectado al relay desde %s, iniciando bridge", peer_addr)
    await _bridge(peer_reader, peer_writer, reader, writer)


async def run_relay_server(host: str, port: int) -> asyncio.base_events.Server:
    server = await asyncio.start_server(_relay_connection_handler, host, port)
    log.info("relay TCP de media escuchando en %s:%d (bridge puro, sin Tor)", host, port)
    return server


# ---------------------------------------------------------------------------
# Arranque
# ---------------------------------------------------------------------------

async def _run(args: argparse.Namespace) -> None:
    global RELAY_PORT
    RELAY_PORT = args.relay_port

    app = build_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, args.host, args.port)
    await site.start()
    log.info(
        "captcha REST + websocket de señalizacion en http://%s:%d (SOLO pruebas locales, sin Tor)",
        args.host, args.port,
    )

    relay_server = await run_relay_server(args.host, args.relay_port)
    try:
        async with relay_server:
            await relay_server.serve_forever()
    finally:
        await runner.cleanup()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765, help="puerto HTTP+WebSocket de señalizacion")
    parser.add_argument("--relay-port", type=int, default=9001, help="puerto TCP del relay de media")
    args = parser.parse_args()
    try:
        asyncio.run(_run(args))
    except KeyboardInterrupt:
        log.info("apagando mock server")


if __name__ == "__main__":
    main()
