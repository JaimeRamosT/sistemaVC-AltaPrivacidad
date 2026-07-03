"""
Cliente TCP crudo hacia el relay de media (tcp-relay, NO el WebSocket de
señalización). Ejecuta su propio QThread + event loop de asyncio, en el
mismo patrón que WSClient, para no bloquear la UI de PySide6.

Tras recibir ROOM_ASSIGNED del manager, cada extremo de la llamada abre una
conexión TCP separada directamente al relay zero-knowledge
(`tcp-relay/main.go`): un contenedor efímero que solo hace un `io.Copy`
bidireccional entre los dos peers de una llamada, sin inspeccionar ni un
byte del contenido.

Handshake con el relay (ver tcp-relay/main.go:118-148):
  1. Conectar por TCP -- vía SOCKS5 de Tor al `onion_address:port`, o
     directo a `host:port` en modo `TORVC_DEV_NO_TOR` (pruebas locales
     contra el docker-compose del backend, sin Tor real).
  2. Enviar el token recibido en ROOM_ASSIGNED + "\n" en un único write
     (el relay hace una sola lectura de hasta 128 bytes con 5s de deadline,
     así que todo el token debe salir en un solo paquete de aplicación).
  3. Esperar la línea de respuesta "OK\n" del relay.
  4. A partir de ahí el relay es un pipe de bytes puro: cualquier framing
     es responsabilidad exclusiva de los dos clientes.

Como el backend real no ofrece un canal de señalización genérico para
reenviar datos de aplicación entre los dos peers de una llamada (a
diferencia de `mock_server`, que reenviaba cualquier JSON tal cual), tanto
el intercambio de clave de sesión (X25519, 32 bytes crudos, sin cifrar --
es material público) como los MediaFrame (video/audio/control, ya
cifrados con la clave derivada) viajan por esta conexión al relay:

  - Los primeros 32 bytes que cada lado escribe/lee son la clave pública
    X25519 en crudo (tamaño fijo, no necesita framing).
  - A partir de ahí, cada MediaFrame.pack() va precedido por un largo de
    4 bytes big-endian (protocol.pack_length_prefixed), necesario porque
    una conexión TCP cruda no tiene noción de límites de mensaje como sí
    los tiene un frame binario de WebSocket.
"""
from __future__ import annotations

import asyncio
import queue
import struct
import threading
from typing import Optional

from PySide6.QtCore import QThread, Signal

from .. import config
from . import protocol


class RelayClient(QThread):
    connected = Signal()                 # token aceptado + intercambio de pubkey listo
    peer_pubkey_received = Signal(bytes)  # 32 bytes, clave pública X25519 del peer
    disconnected = Signal(str)           # razón
    media_received = Signal(object)      # protocol.MediaFrame
    error = Signal(str)

    def __init__(self, host: str, port: int, token: str, own_pubkey: bytes, parent=None):
        super().__init__(parent)
        self._host = host
        self._port = port
        self._token = token
        self._own_pubkey = own_pubkey
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._main_task: Optional["asyncio.Task"] = None
        self._outbox: "queue.Queue[bytes]" = queue.Queue()
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------
    # API pública (llamable desde el hilo de UI)
    # ------------------------------------------------------------------
    def send_media(self, frame_bytes: bytes) -> None:
        self._outbox.put(frame_bytes)

    def stop(self) -> None:
        # Ver el comentario equivalente en ws_client.WSClient.stop(): la
        # bandera sola no interrumpe un await bloqueado (p.ej. dentro de
        # proxy.connect() con hasta 90s de timeout construyendo el circuito
        # Tor), y sin eso el hilo real puede seguir vivo mucho después de
        # que _teardown() suelte la referencia al QThread -- provocando el
        # "QThread: Destroyed while thread is still running" fatal de Qt.
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
            self.error.emit(f"Fallo irrecuperable en la conexión al relay: {exc}")
        finally:
            self._loop.close()

    # ------------------------------------------------------------------
    # Lógica async
    # ------------------------------------------------------------------
    async def _main(self) -> None:
        writer = None
        try:
            reader, writer = await self._open_connection()

            # -- 1. Handshake de token con el relay --------------------
            writer.write((self._token + "\n").encode("ascii"))
            await writer.drain()
            ack = await asyncio.wait_for(reader.readline(), timeout=10)
            if ack.strip() != b"OK":
                raise ConnectionError(f"el relay rechazó el token (respuesta: {ack!r})")

            # -- 2. Handshake de clave pública X25519 (32 bytes crudos) --
            # Timeout generoso: el otro extremo puede tardar en completar
            # su propio circuito Tor hasta este mismo relay antes de llegar
            # a este punto -- no es solo esperar bytes ya en tránsito.
            writer.write(self._own_pubkey)
            await writer.drain()
            peer_pub = await asyncio.wait_for(reader.readexactly(32), timeout=60)
            self.peer_pubkey_received.emit(peer_pub)

            self.connected.emit()

            sender = asyncio.create_task(self._sender_loop(writer))
            receiver = asyncio.create_task(self._receiver_loop(reader))
            stopper = asyncio.create_task(self._stop_watcher())
            tasks = {sender, receiver, stopper}
            done: set = set()
            try:
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            finally:
                # Ver el comentario equivalente en WSClient._main(): si
                # stop() cancela _main_task justo mientras esperamos aquí,
                # la cancelación interrumpe asyncio.wait() sin pasar por el
                # cleanup normal -- este finally es lo único que corre, y
                # sin él las tareas quedan sin cancelar ni esperar.
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
            for task in done:
                exc = task.exception() if not task.cancelled() else None
                if exc is not None and not isinstance(
                    exc, (asyncio.IncompleteReadError, ConnectionError, OSError)
                ):
                    raise exc
        except Exception as exc:
            self.error.emit(f"No se pudo conectar al relay ({self._host}:{self._port}): {exc}")
        finally:
            if writer is not None:
                writer.close()
            self.disconnected.emit("cerrado")

    async def _open_connection(self):
        if config.DEV_DISABLE_TOR:
            return await asyncio.open_connection(self._host, self._port)
        from python_socks.async_.asyncio import Proxy

        proxy = Proxy.from_url(f"socks5://{config.TOR_SOCKS_HOST}:{config.TOR_SOCKS_PORT}")
        # 90s: construir el circuito hasta un hidden service puede tardar
        # bastante más que un connect() a un destino clearnet.
        sock = await proxy.connect(dest_host=self._host, dest_port=self._port, timeout=90)
        return await asyncio.open_connection(sock=sock)

    async def _stop_watcher(self) -> None:
        while not self._stop_event.is_set():
            await asyncio.sleep(0.1)

    async def _sender_loop(self, writer: asyncio.StreamWriter) -> None:
        loop = asyncio.get_event_loop()
        while not self._stop_event.is_set():
            try:
                frame_bytes = await loop.run_in_executor(None, self._outbox.get, True, 0.2)
            except queue.Empty:
                continue
            writer.write(protocol.pack_length_prefixed(frame_bytes))
            await writer.drain()

    async def _receiver_loop(self, reader: asyncio.StreamReader) -> None:
        while not self._stop_event.is_set():
            header = await reader.readexactly(protocol.LENGTH_PREFIX_SIZE)
            length = protocol.unpack_length_prefix(header)
            payload = await reader.readexactly(length)
            try:
                self.media_received.emit(protocol.MediaFrame.unpack(payload))
            except (ValueError, struct.error) as exc:
                self.error.emit(f"Frame de media inválido desde el relay: {exc}")
