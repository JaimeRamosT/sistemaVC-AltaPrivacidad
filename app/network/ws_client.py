"""
Cliente WSS asíncrono, enrutado por el proxy SOCKS5 de Tor (RNF-01a/b),
ejecutándose en un QThread propio con su propio event loop de asyncio para
no bloquear la UI de PySide6.

Expone señales Qt (`connected`, `disconnected`, `signal_received`,
`media_received`, `error`) y métodos thread-safe (`send_signal`,
`send_media`, `stop`) que pueden llamarse desde el hilo de la UI.
"""
from __future__ import annotations

import asyncio
import queue
import threading
from typing import Optional

import aiohttp
from aiohttp_socks import ProxyConnector
from PySide6.QtCore import QThread, Signal

from .. import config
from . import protocol


class WSClient(QThread):
    connected = Signal()
    disconnected = Signal(str)          # razón
    signal_received = Signal(dict)      # mensaje JSON ya parseado
    media_received = Signal(object)     # protocol.MediaFrame
    error = Signal(str)

    def __init__(self, server_url: str | None = None, parent=None):
        super().__init__(parent)
        self._server_url = server_url or config.SERVER_WS_URL
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._outbox: "queue.Queue[tuple[str, bytes | str]]" = queue.Queue()
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------
    # API pública (llamable desde el hilo de UI)
    # ------------------------------------------------------------------
    def send_signal(self, msg: dict) -> None:
        self._outbox.put(("text", protocol.encode_signal(msg)))

    def send_media(self, frame_bytes: bytes) -> None:
        self._outbox.put(("binary", frame_bytes))

    def stop(self) -> None:
        self._stop_event.set()

    # ------------------------------------------------------------------
    # QThread
    # ------------------------------------------------------------------
    def run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._main())
        except Exception as exc:  # pragma: no cover - red en vivo
            self.error.emit(f"Fallo irrecuperable de red: {exc}")
        finally:
            self._loop.close()

    # ------------------------------------------------------------------
    # Lógica async
    # ------------------------------------------------------------------
    async def _main(self) -> None:
        connector = self._build_connector()
        timeout = aiohttp.ClientTimeout(total=None, sock_connect=20)
        try:
            async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
                async with session.ws_connect(self._server_url, heartbeat=15) as ws:
                    self._ws = ws
                    self.connected.emit()
                    sender = asyncio.create_task(self._sender_loop(ws))
                    receiver = asyncio.create_task(self._receiver_loop(ws))
                    stopper = asyncio.create_task(self._stop_watcher())
                    done, pending = await asyncio.wait(
                        {sender, receiver, stopper}, return_when=asyncio.FIRST_COMPLETED
                    )
                    for task in pending:
                        task.cancel()
        except Exception as exc:
            self.error.emit(f"No se pudo conectar al servidor (¿Tor levantado en {config.TOR_SOCKS_HOST}:{config.TOR_SOCKS_PORT}?): {exc}")
        finally:
            self._ws = None
            self.disconnected.emit("cerrado")

    def _build_connector(self):
        if config.DEV_DISABLE_TOR:
            return aiohttp.TCPConnector()
        proxy_url = f"socks5://{config.TOR_SOCKS_HOST}:{config.TOR_SOCKS_PORT}"
        return ProxyConnector.from_url(proxy_url)

    async def _stop_watcher(self) -> None:
        while not self._stop_event.is_set():
            await asyncio.sleep(0.1)

    async def _sender_loop(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        loop = asyncio.get_event_loop()
        while not self._stop_event.is_set():
            try:
                kind, payload = await loop.run_in_executor(None, self._outbox.get, True, 0.2)
            except queue.Empty:
                continue
            if kind == "text":
                await ws.send_str(payload)  # type: ignore[arg-type]
            else:
                await ws.send_bytes(payload)  # type: ignore[arg-type]

    async def _receiver_loop(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                try:
                    self.signal_received.emit(protocol.decode_signal(msg.data))
                except ValueError as exc:
                    self.error.emit(f"Mensaje de señalización inválido: {exc}")
            elif msg.type == aiohttp.WSMsgType.BINARY:
                try:
                    self.media_received.emit(protocol.MediaFrame.unpack(msg.data))
                except ValueError as exc:
                    self.error.emit(f"Frame de media inválido: {exc}")
            elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED):
                break
