"""
Llamada REST puntual al backend real (`POST /api/captcha/challenge`),
necesaria antes de poder autenticar la sesión de WebSocket (`AUTH_REQUEST`
exige un `captcha_token` vigente, ver `manager/internal/auth/service.go`).

Se reenvía por el mismo proxy SOCKS5 de Tor que usa el WebSocket de
señalización (WSClient) -- comparten la sesión/conector de aiohttp, así que
esto no es un módulo con su propio hilo/loop: se llama desde dentro del
event loop async que WSClient ya administra.
"""
from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

import aiohttp


def derive_http_base_url(server_ws_url: str) -> str:
    """wss://host/ws -> https://host ; ws://host/ws -> http://host"""
    parts = urlsplit(server_ws_url)
    scheme = "https" if parts.scheme == "wss" else "http"
    return urlunsplit((scheme, parts.netloc, "", "", ""))


async def fetch_captcha_token(session: aiohttp.ClientSession, server_ws_url: str) -> str:
    """Pide un captcha_token de un solo uso al backend real.

    Lanza RuntimeError con un mensaje legible si el backend responde con
    error o con un cuerpo inesperado.
    """
    base_url = derive_http_base_url(server_ws_url)
    url = f"{base_url}/api/captcha/challenge"
    async with session.post(url) as resp:
        if resp.status != 200:
            raise RuntimeError(f"el backend rechazó la solicitud de captcha (HTTP {resp.status})")
        data = await resp.json(content_type=None)
        token = data.get("captcha_token") if isinstance(data, dict) else None
        if not token:
            raise RuntimeError("respuesta de captcha sin 'captcha_token'")
        return token
