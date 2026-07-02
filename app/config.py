"""
Configuración del cliente.

Nada de lo que hay aquí es secreto de usuario ni historial de llamadas
(RNF-04d): son solo parámetros de conexión. Pueden sobreescribirse por
variable de entorno o desde el diálogo de "Configuración" en la app,
y viven únicamente en memoria durante la ejecución.
"""
import os

# Dirección del backend TorZoom (manager/nginx, ver
# Anonymized-video-calls-over-the-Tor-network/README.md). Es el endpoint de
# señalización WebSocket -- de aquí se deriva también la URL REST del
# captcha (ws://host/ws -> http://host/api/captcha/challenge, ver
# network/http_client.py).
#
# OJO: es "ws://", NO "wss://" -- Nginx solo escucha HTTP plano en el puerto
# 80 (ver nginx/nginx.conf del backend, sin bloque ssl). La confidencialidad
# del transporte la da el circuito Tor en sí (el .onion ya es
# extremo-a-extremo cifrado y autenticado), no una capa de TLS de
# aplicación encima. Usar "wss://" contra este backend falla: aiohttp
# intenta un handshake TLS contra un socket que solo habla HTTP/WS plano.
# Ejemplos:
#   ws://abcd1234...onion/ws           (producción, vía Tor)
#   ws://127.0.0.1:8888/ws             (dev local, TORVC_DEV_NO_TOR=1,
#                                        apuntando al docker-compose del
#                                        backend con CAPTCHA_ENABLED=false)
SERVER_WS_URL = os.environ.get("TORVC_SERVER_URL", "ws://REEMPLAZAR-CON-TU-ONION.onion/ws")

# Proxy SOCKS5 de Tor (RNF-01b). Por defecto la app lanza y controla su
# propio proceso Tor (ver app/tor/tor_manager.py y USE_BUNDLED_TOR abajo),
# en cuyo caso estos valores se actualizan solos una vez que Tor termina de
# arrancar (MANAGED_TOR_SOCKS_PORT). Si USE_BUNDLED_TOR=0, estos son los
# que se usan para conectarse a un Tor externo que vos mismo administres:
#   - Tor Browser (mas facil para probar): SOCKS5 en 127.0.0.1:9150
#   - tor.exe / daemon "tor" standalone:    SOCKS5 en 127.0.0.1:9050 (default)
TOR_SOCKS_HOST = os.environ.get("TORVC_SOCKS_HOST", "127.0.0.1")
TOR_SOCKS_PORT = int(os.environ.get("TORVC_SOCKS_PORT", "9050"))

# Si True (default), la app lanza su propio proceso Tor empaquetado en vez
# de depender de que el usuario tenga Tor Browser o un daemon `tor` corriendo
# aparte (RF-03a: "no requerira configuraciones de red complejas"). Requiere
# el binario vendorizado en vendor/tor/<plataforma>/ -- ver vendor/tor/README.md.
# Si no se encuentra el binario o falla el arranque, la pantalla de inicio
# ofrece seguir en modo Tor externo (equivalente a poner esto en 0).
USE_BUNDLED_TOR = os.environ.get("TORVC_USE_BUNDLED_TOR", "1") == "1"

# Puerto SOCKS5 local dedicado para el Tor gestionado por la app. Deliberadamente
# distinto de 9050/9150 para no chocar con una Tor Browser o daemon externos
# que el usuario pueda tener corriendo en simultaneo.
MANAGED_TOR_SOCKS_PORT = int(os.environ.get("TORVC_MANAGED_TOR_PORT", "19050"))

# Si True, se conecta directo sin proxy SOCKS5 (SOLO para pruebas locales
# contra mock_server/server.py). Nunca usar así contra un backend real.
# Tiene prioridad sobre USE_BUNDLED_TOR: en este modo no se lanza ningun
# proceso Tor, ni propio ni externo.
DEV_DISABLE_TOR = os.environ.get("TORVC_DEV_NO_TOR", "0") == "1"

# --- Parámetros de media (RNF-03) ---
VIDEO_WIDTH = 640
VIDEO_HEIGHT = 360          # 360p
VIDEO_FPS = 12
VIDEO_MAX_FRAME_BYTES = 40 * 1024   # <= 40 KB/frame
VIDEO_WEBP_QUALITY_START = 60       # se ajusta dinámicamente para respetar el límite de bytes

AUDIO_SAMPLE_RATE = 48000   # requerido por Opus
AUDIO_CHANNELS = 1
AUDIO_FRAME_MS = 20         # tamaño de trama Opus estándar
AUDIO_BITRATE = 32000       # <= 32 kbps (RNF-03d)

# --- Límites de sesión ---
# RNF-04e. El backend real (TorZoom) no tiene concepto de "sala" ni de TTL
# de sala -- la señalización es por user_id, no por código+contraseña (ver
# call_controller._room_user_id). Este valor es puramente cosmético: solo
# controla la cuenta regresiva que se muestra en CreateRoomScreen; no hay
# ninguna aplicación real de expiración del lado del servidor.
ROOM_CREDENTIALS_TTL_SECONDS = 30 * 60
MAX_LATENCY_WARNING_MS = 3500           # RNF-03a, aviso visual si se supera

APP_NAME = "Videollamada Privada sobre Tor"
