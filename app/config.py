"""
Configuración del cliente.

Nada de lo que hay aquí es secreto de usuario ni historial de llamadas
(RNF-04d): son solo parámetros de conexión. Pueden sobreescribirse por
variable de entorno o desde el diálogo de "Configuración" en la app,
y viven únicamente en memoria durante la ejecución.
"""
import os

# Dirección del backend (servidor .onion "ya levantado en otro espacio").
# Poner aquí la URL real que entregue el pool de contenedores, por ejemplo:
#   wss://abcd1234...onion/ws
SERVER_WS_URL = os.environ.get("TORVC_SERVER_URL", "wss://REEMPLAZAR-CON-TU-ONION.onion/ws")

# Proxy SOCKS5 local de Tor Browser / tor daemon (RNF-01b).
TOR_SOCKS_HOST = os.environ.get("TORVC_SOCKS_HOST", "127.0.0.1")
TOR_SOCKS_PORT = int(os.environ.get("TORVC_SOCKS_PORT", "9050"))

# Si True, se conecta directo sin proxy SOCKS5 (SOLO para pruebas locales
# contra mock_server/server.py). Nunca usar así contra un backend real.
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
ROOM_CREDENTIALS_TTL_SECONDS = 30 * 60  # RNF-04e (lo aplica el backend; el cliente solo lo muestra)
MAX_LATENCY_WARNING_MS = 3500           # RNF-03a, aviso visual si se supera

APP_NAME = "Videollamada Privada sobre Tor"
