# Videollamada Privada 1-a-1 sobre Tor — Cliente de escritorio (POC)

Primera version (prueba de concepto) del **cliente de escritorio** descrito
en la propuesta de proyecto. Esta app asume que el **backend ya esta
levantado en otro espacio** (pool de contenedores Docker con direcciones
`.onion` v3, ver `Segunda iteracion: arquitectura basica`); aqui solo se
construye el lado del cliente que habla con ese servidor.

No implementa WebRTC ni UDP (descartados por RNF-02b): toda la media viaja
como frames binarios cifrados sobre un unico WebSocket Seguro (WSS/TCP), a
traves del proxy SOCKS5 de Tor.

## Que incluye este POC

- Cliente de escritorio de ventana unica (PySide6): Home -> Crear/Unirse a
  sala -> Llamada. (RF-01, RF-03a)
- Conexion WSS enrutada por el proxy SOCKS5 de Tor (RNF-01, RNF-02).
- Captura de camara -> redimension a 360p -> compresion WebP (<=40 KB/frame,
  12 FPS) (RNF-03b/e).
- Captura de microfono -> codec Opus a <=32 kbps (RNF-03d), con
  degradacion elegante si `opuslib`/`libopus` no estan disponibles (la
  llamada sigue solo con video).
- Cifrado de sesion extremo-a-extremo real: intercambio de claves X25519 vía
  el canal de señalizacion, derivacion HKDF-SHA256, cifrado AES-256-GCM de
  cada frame de media (RNF-04b/04c).
- Mute de microfono, apagado de camara, indicador de estado de conexion en
  tiempo real (RF-02).
- Sin logs, historial ni cache en disco: todo vive en memoria y se purga al
  colgar (RNF-04d).
- Servidor mock (`mock_server/`) para probar el flujo completo en un solo
  equipo, sin Tor, mientras se integra contra el backend real.
- `protocol/PROTOCOL.md`: especificacion completa del protocolo WSS que
  asume el cliente (a falta de la documentacion del backend real).

## Que NO incluye (fuera de alcance de este POC)

- El backend en si (pool de Docker + Tor + matchmaking): se asume ya
  desplegado "en otro espacio", conforme a la arquitectura del proyecto.
- Empaquetado final para distribucion (instalador / .exe / AppImage) o
  arranque desde Tails OS por USB (mencionado en el Perfil 1 de la
  propuesta) — el codigo es compatible con ese objetivo pero el empaquetado
  queda para una siguiente iteracion.
- Limitacion de sesiones a 30 min y sanitizacion de contenedores: eso lo
  ejecuta el backend (RNF-04e/RNF-04c); el cliente solo respeta y muestra
  esos limites.

## Instalacion (conda — recomendado)

El ambiente se maneja con **conda** (`environment.yml`), no con `venv`.
Casi todo (PySide6, opencv, aiohttp, python-sounddevice, opuslib —que ya
trae `libopus` como dependencia, sin instalarlo aparte con `apt`/`brew`—,
cryptography, pytest) se resuelve por conda-forge para Windows, macOS y
Linux por igual. La unica excepcion es `aiohttp-socks`: en conda-forge esta
desactualizado (0.8.4), asi que se instala por pip dentro del mismo
ambiente (es paquete puro Python, sin binarios, asi que no hay riesgo de
incompatibilidad).

Estos comandos son identicos en Linux, macOS y Windows (CMD, PowerShell o
la terminal de Anaconda):

```bash
conda env create -f environment.yml
conda activate torvc
python run.py
```

Para actualizar el ambiente despues de un cambio en `environment.yml`:

```bash
conda env update -f environment.yml --prune
```

### Alternativa con pip/venv

Si prefieres no usar conda, `requirements.txt` sigue funcionando igual que
antes (en ese caso sí necesitas instalar `libopus` a mano: `apt install
libopus0` en Linux, `brew install opus` en macOS; en Windows viene incluido
en el propio wheel de `opuslib`).

Linux / macOS / WSL (bash):

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows (PowerShell):

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Windows (CMD):

```bat
python -m venv .venv
.venv\Scripts\activate.bat
pip install -r requirements.txt
```

## Ejecutar contra el backend real

La app lee la URL del servidor y del proxy SOCKS5 de Tor desde variables de
entorno (ver `app/config.py`). La forma de fijarlas cambia segun la
terminal:

Linux / macOS / WSL (bash):

```bash
export TORVC_SERVER_URL="wss://<tu-direccion>.onion/ws"
export TORVC_SOCKS_HOST=127.0.0.1   # host del proxy SOCKS5 de Tor (Tor Browser o `tor` daemon)
export TORVC_SOCKS_PORT=9050
python run.py
```

Windows (PowerShell):

```powershell
$env:TORVC_SERVER_URL = "wss://<tu-direccion>.onion/ws"
$env:TORVC_SOCKS_HOST = "127.0.0.1"
$env:TORVC_SOCKS_PORT = "9050"
python run.py
```

Windows (CMD):

```bat
set TORVC_SERVER_URL=wss://<tu-direccion>.onion/ws
set TORVC_SOCKS_HOST=127.0.0.1
set TORVC_SOCKS_PORT=9050
python run.py
```

Tambien se puede fijar la URL del servidor desde la app: botón
"Configuracion de conexion" en la pantalla de inicio (solo vive en memoria
durante la sesion, no se guarda en disco) — esta es la opcion mas simple si
no quieres lidiar con variables de entorno.

## Probar de punta a punta SIN Tor (con el servidor mock)

Util para validar la UI y el pipeline de media mientras se conecta el
backend real. En una terminal (con el ambiente `torvc` activado):

```bash
python mock_server/server.py --host 127.0.0.1 --port 8765
```

En dos terminales distintas (dos instancias = los dos participantes).

Linux / macOS / WSL (bash), variables inline en la misma linea:

```bash
TORVC_DEV_NO_TOR=1 TORVC_SERVER_URL=ws://127.0.0.1:8765/ws python run.py
```

Windows (PowerShell) — no soporta `VAR=valor comando`, hay que fijarlas
antes:

```powershell
$env:TORVC_DEV_NO_TOR = "1"
$env:TORVC_SERVER_URL = "ws://127.0.0.1:8765/ws"
python run.py
```

Windows (CMD):

```bat
set TORVC_DEV_NO_TOR=1
set TORVC_SERVER_URL=ws://127.0.0.1:8765/ws
python run.py
```

Repite el bloque correspondiente en la otra terminal para el segundo
participante.

En la primera ventana: "Crear nueva sala" y copiar numero+contraseña. En la
segunda: "Unirse a una sala" y pegar esas credenciales.

## Estructura del proyecto

```
environment.yml            Ambiente conda (recomendado)
requirements.txt           Alternativa pip/venv
run.py                     Punto de entrada
app/
  config.py                 Parametros de conexion y de media (todo en memoria)
  call_controller.py         Orquestador: une red + cifrado + media + UI
  main_window.py              Ventana unica (QStackedWidget)
  network/
    ws_client.py              Cliente WSS por SOCKS5 (Tor), QThread + asyncio
    protocol.py                Serializacion de mensajes JSON y frames binarios
  security/
    ephemeral.py               X25519 + HKDF + AES-256-GCM, purga en memoria
  media/
    video_capture.py            Captura de camara + compresion WebP
    webp_codec.py                Codec WebP puro (testeable sin Qt)
    audio_io.py                   Captura/reproduccion con Opus
  screens/                     Pantallas de la UI (home, crear, unirse, llamada)
  utils/
    logging_guard.py             Logging solo a stdout, nunca a disco
    qt_env_fix.py                 Evita el conflicto de plugins Qt entre cv2 y PySide6
protocol/PROTOCOL.md         Especificacion del protocolo WSS
mock_server/server.py        Servidor de prueba local (sin Tor)
tests/                       Pruebas unitarias (protocolo, cripto, codec WebP)
```

## Pruebas

```bash
conda activate torvc
pytest tests/ -v
```

Las pruebas cubren: empaquetado/desempaquetado de frames binarios y
mensajes de señalizacion, el intercambio de claves X25519+HKDF y
cifrado/descifrado AES-GCM (incluyendo que dos salas distintas nunca deriven
la misma clave), y el pipeline WebP respetando el limite de 40 KB/frame.

Ademas se verifico manualmente un flujo de extremo a extremo real
(crear sala -> unirse -> intercambio de claves -> envio de un frame de video
cifrado -> descifrado correcto en el otro cliente) usando el codigo de
produccion (`WSClient`, `protocol`, `SessionKeyManager`) contra
`mock_server/server.py`.

**Limitacion conocida de este entorno de desarrollo:** no fue posible
lanzar visualmente la interfaz PySide6 (falta la libreria de sistema
`libEGL` en este sandbox sin privilegios de administrador, y no hay conda
instalado en el sandbox para probar `environment.yml` end-to-end). Esto no
afecta a un equipo de escritorio normal (Windows/macOS/Linux de escritorio
ya traen esa dependencia, y conda-forge la resuelve). Ya se confirmo
manualmente que la app arranca y corre en un equipo real (Windows con WSL).

## Solucion de problemas conocidos

**`qt.qpa.plugin: Could not find the Qt platform plugin "wayland"/"xcb" in ""`**
al correr `python run.py` (visto en WSL y en algunos setups de conda): la
causa es que `cv2` (OpenCV) trae su propio Qt empaquetado con un directorio
de plugins incompleto, y al importarse pisa la variable de entorno
`QT_QPA_PLATFORM_PLUGIN_PATH` para que apunte ahi en vez de a los plugins
completos de PySide6
([mas detalle](https://github.com/opencv/opencv-python/issues/729)). Ya
esta resuelto en el codigo (`app/utils/qt_env_fix.py`, llamado desde
`run.py` antes de crear la `QApplication`), asi que actualiza tu copia si
seguis viendo este error.

**`PackagesNotFoundError` al crear el ambiente conda:** revisa que el
paquete y version pedidos en `environment.yml` existan en conda-forge para
tu plataforma (`conda search -c conda-forge <paquete>`). Los paquetes puros
Python sin binarios (como `aiohttp-socks`) se resuelven mejor via `pip:`
dentro del propio `environment.yml` en vez de forzarlos por conda.

## Siguientes pasos sugeridos

1. Conectar `TORVC_SERVER_URL` a la direccion `.onion` real del backend y
   ajustar `app/network/protocol.py` si los nombres de campo difieren
   (ver `protocol/PROTOCOL.md`, seccion 5).
2. Probar la app real en una maquina con camara/microfono y Tor
   corriendo (`tor` daemon o Tor Browser con el proxy SOCKS5 activo).
3. Empaquetar con PyInstaller para distribucion de un solo archivo.
4. Evaluar correr el cliente desde Tails OS (Perfil 1 de la propuesta).
