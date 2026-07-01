#!/usr/bin/env python3
"""
Servidor de prueba LOCAL (sin Tor, sin Docker, sin direcciones .onion) que
implementa el protocolo descrito en protocol/PROTOCOL.md: gestion de salas,
relevo de senalizacion (incluido key_exchange, que el servidor nunca puede
leer porque son claves publicas efimeras) y relevo de frames binarios de
media entre los dos participantes de una sala.

Esto NO es el backend de produccion (pool de contenedores Docker + Tor
descrito en la arquitectura del proyecto). Es un doble minimalista para
poder probar el cliente de escritorio de punta a punta en un solo equipo
mientras el backend real (que ya corre "en otro espacio") se integra.

Uso:
    python mock_server/server.py --host 127.0.0.1 --port 8765

Luego, en dos terminales distintas:
    TORVC_DEV_NO_TOR=1 TORVC_SERVER_URL=ws://127.0.0.1:8765/ws python run.py
    TORVC_DEV_NO_TOR=1 TORVC_SERVER_URL=ws://127.0.0.1:8765/ws python run.py
"""
from __future__ import annotations

import argparse
import json
import logging
import random
import secrets
import string
import time
from dataclasses import dataclass

from aiohttp import web, WSMsgType

logging.basicConfig(level=logging.INFO, format="[mock-server] %(message)s")
log = logging.getLogger("mock_server")

ROOM_TTL_SECONDS = 30 * 60  # RNF-04e


@dataclass
class Room:
    room_id: str
    password: str
    expires_at: float
    creator_ws: web.WebSocketResponse
    peer_ws: "web.WebSocketResponse | None" = None


ROOMS: dict[str, Room] = {}


def _gen_room_id() -> str:
    while True:
        rid = "".join(random.choices(string.digits, k=6))
        if rid not in ROOMS:
            return rid


def _gen_password() -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "-".join("".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(2))


async def websocket_handler(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse(heartbeat=15)
    await ws.prepare(request)
    peer_addr = request.remote
    room: "Room | None" = None
    log.info("nueva conexion desde %s", peer_addr)

    async for msg in ws:
        if msg.type == WSMsgType.TEXT:
            try:
                data = json.loads(msg.data)
            except json.JSONDecodeError:
                continue
            mtype = data.get("type")

            if mtype == "create_room":
                room = Room(
                    room_id=_gen_room_id(),
                    password=_gen_password(),
                    expires_at=time.time() + ROOM_TTL_SECONDS,
                    creator_ws=ws,
                )
                ROOMS[room.room_id] = room
                await ws.send_json({
                    "type": "room_created",
                    "roomId": room.room_id,
                    "password": room.password,
                    "expiresAt": int(room.expires_at),
                })
                log.info("sala %s creada", room.room_id)

            elif mtype == "join_room":
                rid = data.get("roomId", "")
                pwd = data.get("password", "")
                candidate = ROOMS.get(rid)
                if candidate is None:
                    await ws.send_json({"type": "join_error", "reason": "invalid_credentials"})
                elif time.time() > candidate.expires_at:
                    await ws.send_json({"type": "join_error", "reason": "expired"})
                    ROOMS.pop(rid, None)
                elif candidate.password != pwd:
                    await ws.send_json({"type": "join_error", "reason": "invalid_credentials"})
                elif candidate.peer_ws is not None:
                    await ws.send_json({"type": "join_error", "reason": "room_full"})
                else:
                    candidate.peer_ws = ws
                    room = candidate
                    await ws.send_json({"type": "join_ok", "roomId": rid})
                    if not candidate.creator_ws.closed:
                        await candidate.creator_ws.send_json({"type": "peer_joined"})
                    log.info("peer se unio a sala %s", rid)

            elif mtype in ("key_exchange", "call_start", "call_end", "mute_state", "ping"):
                if mtype == "ping":
                    await ws.send_json({"type": "pong", "ts": data.get("ts")})
                    continue
                await _relay(room, ws, data)

        elif msg.type == WSMsgType.BINARY:
            await _relay_binary(room, ws, msg.data)

        elif msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE, WSMsgType.CLOSING):
            break

    # -- limpieza al desconectar (equivalente simplificado de RNF-04c) -----
    if room is not None:
        other = room.peer_ws if ws is room.creator_ws else room.creator_ws
        if other is not None and not other.closed:
            try:
                await other.send_json({"type": "peer_left"})
            except Exception:
                pass
        ROOMS.pop(room.room_id, None)
        log.info("sala %s cerrada y purgada", room.room_id)

    return ws


async def _relay(room, sender, data: dict) -> None:
    if room is None:
        return
    other = room.peer_ws if sender is room.creator_ws else room.creator_ws
    if other is not None and not other.closed:
        await other.send_json(data)


async def _relay_binary(room, sender, data: bytes) -> None:
    if room is None:
        return
    other = room.peer_ws if sender is room.creator_ws else room.creator_ws
    if other is not None and not other.closed:
        await other.send_bytes(data)


def build_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/ws", websocket_handler)
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    log.info("escuchando en ws://%s:%d/ws (SOLO pruebas locales, sin Tor)", args.host, args.port)
    web.run_app(build_app(), host=args.host, port=args.port, print=None)


if __name__ == "__main__":
    main()
