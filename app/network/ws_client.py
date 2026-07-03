"""
Cliente WSS asíncrono de señalización, enrutado por el proxy SOCKS5 de Tor
(RNF-01a/b), ejecutándose en un QThread propio con su propio event loop de
asyncio para no bloquear la UI de PySide6.

Ya NO transporta media (eso ahora va por relay_client.py, ver ese módulo
para la justificación): este cliente solo habla el protocolo de
señalización JSON del backend real (`manager/protocol/messages.go`).

También se encarga internamente de todo el "handshake de sesión" antes de
que el resto de la app pueda considerarse "conectado":
  1. Pide un `captcha_token` de un solo uso vía REST (`http_client.py`).
  2. Abre el WebSocket y envía `AUTH_REQUEST {user_id, captcha_token}`.
  3. Espera `AUTH_OK` (emite `connected`) o `AUTH_FAIL` (emite `auth_failed`).
  4. Mientras la sesión sigue viva, envía `HEARTBEAT` periódicamente: el
     backend cierra la conexión si no recibe ningún mensaje de aplicación
     en 45s (el ping/pong propio del protocolo WebSocket, que aiohttp ya
     hace solo con `heartbeat=15`, no cuenta para ese temporizador porque
     el servidor solo reinicia el deadline al recibir un mensaje de datos,
     no un frame de control).

Expone señales Qt (`connected`, `auth_failed`, `disconnected`,
`signal_received`, `error`) y métodos thread-safe (`send_signal`, `stop`)
llamables desde el hilo de la UI.
"""
from __future__ import annotations

import asyncio
import queue
import threading
import time
from typing import Optional

import aiohttp
from aiohttp_socks import ProxyConnector
from PySide6.QtCore import QThread, Signal

from .. import config
from . import protocol
from .http_client import fetch_captcha_token

HEARTBEAT_INTERVAL_SECONDS = 20
AUTH_TIMEOUT_SECONDS = 20


class WSClient(QThread):
    connected = Signal()                # AUTH_OK recibido -- sesión lista para usarse
    auth_failed = Signal(str)           # razón devuelta por AUTH_FAIL
    disconnected = Signal(str)          # razón
    signal_received = Signal(str, dict)  # (msg_type, payload) ya decodificado
    error = Signal(str)

    def __init__(self, user_id: str, server_url: str | None = None, parent=None):
        super().__init__(parent)
        self._user_id = user_id
        self._server_url = server_url or config.SERVER_WS_URL
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._main_task: Optional["asyncio.Task"] = None
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._outbox: "queue.Queue[str]" = queue.Queue()
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------
    # API pública (llamable desde el hilo de UI)
    # ------------------------------------------------------------------
    def send_signal(self, msg_type: str, payload: dict | None = None) -> None:
        self._outbox.put(protocol.encode_signal(msg_type, payload))

    def stop(self) -> None:
        # _stop_event por sí solo NO alcanza: solo lo revisan los bucles que
        # corren DESPUÉS de que la sesión ya está establecida. Si stop() se
        # llama mientras _main() sigue bloqueado en el captcha o el
        # handshake del WebSocket (hasta 90s contra un circuito Tor lento),
        # la bandera nunca se revisa y el hilo real de Python sigue vivo
        # mucho después de que _teardown() suelte la referencia al QThread
        # -- eso es exactamente lo que provoca el "QThread: Destroyed while
        # thread is still running" (fatal en Qt). Cancelar la tarea de
        # asyncio interrumpe cualquier await en curso, sin importar en qué
        # fase esté.
        self._stop_event.set()
        loop, task = self._loop, self._main_task
        if loop is None or task is None or loop.is_closed():
            return  # el hilo ya terminó por su cuenta -- nada que cancelar
        try:
            loop.call_soon_threadsafe(task.cancel)
        except RuntimeError:
            pass  # se cerró justo entre el chequeo de arriba y esta llamada

    # ------------------------------------------------------------------
    # QThread
    # ------------------------------------------------------------------
    def run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._main_task = self._loop.create_task(self._main())
            self._loop.run_until_complete(self._main_task)
        except asyncio.CancelledError:
            pass  # stop() pedido mientras _main() seguía conectando/corriendo
        except Exception as exc:  # pragma: no cover - red en vivo
            self.error.emit(f"Fallo irrecuperable de red: {exc}")
        finally:
            self._loop.close()

    # ------------------------------------------------------------------
    # Lógica async
    # ------------------------------------------------------------------
    async def _main(self) -> None:
        connector = self._build_connector()
        # sock_connect cubre también la construcción del circuito Tor hasta
        # el hidden service (no solo un connect() TCP normal): con 20s se
        # observan ProxyTimeoutError frecuentes contra un .onion real,
        # sobre todo si el descriptor recién se publicó o la red está
        # cargada. 90s da margen realista sin ocultar un fallo genuino.
        timeout = aiohttp.ClientTimeout(total=None, sock_connect=90)
        try:
            async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
                captcha_token = await fetch_captcha_token(session, self._server_url)
                async with session.ws_connect(self._server_url, heartbeat=15) as ws:
                    self._ws = ws
                    await ws.send_str(protocol.encode_signal(
                        *protocol.auth_request_msg(self._user_id, captcha_token)
                    ))
                    ok, reason = await self._await_auth_result(ws)
                    if not ok:
                        self.auth_failed.emit(reason)
                        return

                    self.connected.emit()
                    sender = asyncio.create_task(self._sender_loop(ws))
                    receiver = asyncio.create_task(self._receiver_loop(ws))
                    heartbeat = asyncio.create_task(self._heartbeat_loop())
                    stopper = asyncio.create_task(self._stop_watcher())
                    tasks = {sender, receiver, heartbeat, stopper}
                    try:
                        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    finally:
                        # En un cierre normal, esto solo cancela las que
                        # sigan pendientes. Pero si stop() cancela
                        # _main_task mientras justo esperábamos aquí, la
                        # cancelación interrumpe el propio asyncio.wait()
                        # de arriba sin pasar por ningún cleanup -- este
                        # finally es lo único que sigue ejecutándose, y sin
                        # él las cuatro tareas quedarían sin cancelar ni
                        # esperar (el típico "Task was destroyed but it is
                        # pending!").
                        for task in tasks:
                            if not task.done():
                                task.cancel()
                        await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as exc:
            self.error.emit(
                f"No se pudo conectar al servidor (¿Tor levantado en "
                f"{config.TOR_SOCKS_HOST}:{config.TOR_SOCKS_PORT}?): {exc}"
            )
        finally:
            self._ws = None
            self.disconnected.emit("cerrado")

    async def _await_auth_result(self, ws: aiohttp.ClientWebSocketResponse) -> tuple[bool, str]:
        """Consume mensajes hasta ver AUTH_OK/AUTH_FAIL, o hasta agotar el timeout.

        Nota: se usa `wait_for` en vez de `asyncio.timeout` (este último
        requiere Python >= 3.11; el proyecto fija Python 3.10 en
        environment.yml).
        """
        deadline = time.monotonic() + AUTH_TIMEOUT_SECONDS
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False, "timeout_esperando_auth"
                msg = await asyncio.wait_for(ws.receive(), timeout=remaining)
                if msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED,
                                 aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSING):
                    return False, "conexion_cerrada_antes_de_autenticar"
                if msg.type != aiohttp.WSMsgType.TEXT:
                    continue
                try:
                    msg_type, payload = protocol.decode_signal(msg.data)
                except ValueError:
                    continue
                if msg_type == protocol.TYPE_AUTH_OK:
                    return True, ""
                if msg_type == protocol.TYPE_AUTH_FAIL:
                    return False, payload.get("reason", "desconocido")
        except asyncio.TimeoutError:
            return False, "timeout_esperando_auth"

    def _build_connector(self):
        if config.DEV_DISABLE_TOR:
            return aiohttp.TCPConnector()
        proxy_url = f"socks5://{config.TOR_SOCKS_HOST}:{config.TOR_SOCKS_PORT}"
        return ProxyConnector.from_url(proxy_url)

    async def _stop_watcher(self) -> None:
        while not self._stop_event.is_set():
            await asyncio.sleep(0.1)

    async def _heartbeat_loop(self) -> None:
        while not self._stop_event.is_set():
            await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
            if self._ws is not None and not self._ws.closed:
                await self._ws.send_str(protocol.encode_signal(
                    *protocol.heartbeat_msg(int(time.time() * 1000))
                ))

    async def _sender_loop(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        loop = asyncio.get_event_loop()
        while not self._stop_event.is_set():
            try:
                raw = await loop.run_in_executor(None, self._outbox.get, True, 0.2)
            except queue.Empty:
                continue
            await ws.send_str(raw)

    async def _receiver_loop(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                try:
                    msg_type, payload = protocol.decode_signal(msg.data)
                except ValueError as exc:
                    self.error.emit(f"Mensaje de señalización inválido: {exc}")
                    continue
                if msg_type == protocol.TYPE_HEARTBEAT_ACK:
                    continue  # solo mantiene viva la sesión, nada que hacer
                self.signal_received.emit(msg_type, payload)
            elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED):
                break
