# Videollamada Privada 1-a-1 sobre Tor — Cliente de escritorio (POC)

Cliente de escritorio que habla con el backend real **TorZoom**
(repo [`Anonymized-video-calls-over-the-Tor-network`](https://github.com/fransdns/Anonymized-video-calls-over-the-Tor-network),
manager + tcp-relay + Nginx + Tor). La integración contra ese backend real
ya está hecha y verificada de punta a punta, incluso con Tor real (no solo
en modo desarrollo) — ver la sección "Ejecutar contra el backend real".

No implementa WebRTC ni UDP (descartados por RNF-02b). A diferencia del
diseño original del POC, la media **no** viaja por el mismo WebSocket de
señalización: el backend real usa dos conexiones separadas por Tor —
1. **Señalización** (JSON, envelope `{type, payload}`): WebSocket a
   `ws://<onion-de-señalización>/ws`.
2. **Media** (frames binarios cifrados, video/audio/control): conexión TCP
   aparte al relay asignado en `ROOM_ASSIGNED`, con su propio handshake de
   token + intercambio de clave X25519.

Ver `protocol/PROTOCOL.md` para la especificación completa del protocolo
real (reescrita a partir de la integración; reemplaza el borrador original
pensado para `mock_server`).

## Que incluye este POC

- Cliente de escritorio de ventana unica (PySide6): Tor -> Home ->
  Crear/Unirse a sala -> Llamada. (RF-01, RF-03a)
- **La app lanza y controla su propio proceso Tor** al arrancar (binario
  vendorizado, ver mas abajo) — el usuario no necesita instalar ni correr
  Tor Browser o un daemon `tor` aparte. Con fallback a un Tor externo si el
  binario no esta disponible o falla el arranque.
- Conexion WSS enrutada por el proxy SOCKS5 de Tor (RNF-01, RNF-02).
- Captura de camara -> redimension a 360p -> compresion WebP (<=40 KB/frame,
  12 FPS) (RNF-03b/e).
- Captura de microfono -> codec Opus a <=32 kbps (RNF-03d), con
  degradacion elegante si `opuslib`/`libopus` no estan disponibles (la
  llamada sigue solo con video).
- Cifrado de sesion extremo-a-extremo real: intercambio de claves X25519
  sobre la propia conexion al relay (32 bytes crudos, antes del primer
  frame de media), derivacion HKDF-SHA256, cifrado AES-256-GCM de cada
  frame de media (RNF-04b/04c).
- Mute de microfono, apagado de camara, indicador de estado de conexion en
  tiempo real (RF-02) — viaja como un frame de media mas (tipo `CONTROL`),
  cifrado igual que video/audio.
- Sin logs, historial ni cache en disco: todo vive en memoria y se purga al
  colgar (RNF-04d), incluido el `DataDirectory` efimero del Tor propio.
- `mock_server/`: simula el backend real (auth por captcha, señalización
  con envelope `{type,payload}`, y un relay TCP propio) para probar el
  flujo completo en un solo equipo sin Tor ni Docker.
- `protocol/PROTOCOL.md`: especificacion completa del protocolo real
  (señalización + canal de relay) contra el que habla este cliente.
- Empaquetado como `.exe` autocontenido con PyInstaller, incluyendo el
  binario de Tor (ver seccion "Empaquetar como .exe" mas abajo).

## Que NO incluye (fuera de alcance de este POC)

- El backend en si (manager Go + tcp-relay + Redis + Nginx + Tor): vive en
  el repo separado `Anonymized-video-calls-over-the-Tor-network`.
- **El binario de Tor en si**: no se versiona en el repo (ver
  `vendor/tor/README.md`); hay que descargarlo una vez con
  `scripts/fetch_tor.ps1` / `.sh` antes de correr en modo "Tor propio" o de
  empaquetar el `.exe`.
- Arranque desde Tails OS por USB (mencionado en el Perfil 1 de la
  propuesta) — el codigo es compatible con ese objetivo pero no se probo
  ahi todavia.
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

## Tor propio integrado en la app (RF-03a)

Por defecto (`TORVC_USE_BUNDLED_TOR=1`, que ya viene activado), al abrir la
app lo primero que se ve es una pantalla "Conectando a la red Tor…" con una
barra de progreso: la app lanza su propio proceso `tor` (binario
vendorizado, ver abajo) con una configuracion minima y efimera —
`DataDirectory` en un directorio temporal que se borra al cerrar la app, y
un `SocksPort` propio en `127.0.0.1:19050` (puerto distinto de 9050/9150
para no chocar con una Tor Browser que tengas abierta aparte). Cuando
termina de conectar a la red Tor (`Bootstrapped 100%`), pasa sola a la
pantalla de inicio.

Este comportamiento esta implementado en `app/tor/tor_manager.py`
(`TorProcessManager`) y se orquesta desde `app/main_window.py`.

### Obtener el binario de Tor (paso previo obligatorio)

La app **no trae el binario de Tor incluido en el repo** (ver
`vendor/tor/README.md` para el porque). Hay que descargarlo una vez:

Windows (PowerShell):
```powershell
powershell -ExecutionPolicy Bypass -File scripts\fetch_tor.ps1
```

Linux / macOS (bash):
```bash
./scripts/fetch_tor.sh
```

Esto descarga el Tor Expert Bundle oficial mas reciente de
`dist.torproject.org` y lo deja en `vendor/tor/<windows|linux|macos>/`.
Si preferís bajarlo manualmente (por ejemplo desde
https://www.torproject.org/download/tor/), extraé el `.tar.gz` en esa
misma carpeta de forma que quede `vendor/tor/windows/tor/tor.exe` (o el
equivalente en Linux/macOS). Ver `vendor/tor/README.md` para mas detalle,
incluida la recomendacion de verificar tambien la firma PGP oficial (los
scripts solo validan el checksum SHA256).

### Si el binario no esta o falla el arranque

La pantalla de arranque no bloquea el uso de la app: ofrece "Reintentar" y
"Usar un Tor externo (avanzado)". Esta segunda opcion vuelve al flujo
manual documentado en la seccion siguiente (Tor Browser o `tor` daemon
corriendo aparte) — equivalente a poner `TORVC_USE_BUNDLED_TOR=0`.

## Ejecutar contra el backend real (Anonymized-video-calls-over-the-Tor-network)

El backend real (manager Go + tcp-relay + Redis + Nginx, todo detrás de
Tor) vive en el repo
[`Anonymized-video-calls-over-the-Tor-network`](https://github.com/fransdns/Anonymized-video-calls-over-the-Tor-network).
Esta app ya está integrada contra su protocolo real (ver
`protocol/PROTOCOL.md`) y fue verificada de punta a punta contra él,
incluso con Tor real (señalización + relay + intercambio de un frame de
video cifrado, viajando ambos por circuitos Tor reales).

Hay dos formas de correr contra ese backend, según si tenés Tor real
levantado o no:

### Opción A — Sin Tor real (desarrollo/pruebas rápidas)

Útil si solo querés probar la integración sin levantar Tor. El
orchestrator del backend publica el puerto de cada relay directo en el
host, así que el cliente puede hablarle en texto plano sin pasar por
ningún proxy:

```powershell
# En Anonymized-video-calls-over-the-Tor-network:
docker compose up -d

# En torvc, dos terminales (una por participante):
$env:TORVC_DEV_NO_TOR = "1"
$env:TORVC_SERVER_URL = "ws://127.0.0.1:8888/ws"
python run.py
```

Ver la sección "Cliente de referencia (torvc)" del README de ese repo para
más detalle (incluye por qué las direcciones `.onion` son placeholders en
este modo, y por qué eso no importa acá).

### Opción B — Con Tor real, de punta a punta

**1. Configurar el backend con Tor real.** Seguí la sección "Probar contra
el .onion real" del README del backend: ahí se explica cómo generar el
`torrc`, arrancar Tor, leer las direcciones `.onion` generadas, y
configurar `ONION_ADDRESS_POOL` en el backend. Un mismo daemon `tor.exe`
puede alojar los hidden services del backend **y** servir de proxy SOCKS5
para este cliente (útil para probar todo en una sola máquina; en un
despliegue real cada participante tendría su propio Tor).

**2. Apuntar torvc a ese Tor** (en vez de que la app lance el suyo propio,
`TORVC_USE_BUNDLED_TOR=0`). Si seguiste el paso 1 con un único `tor.exe`
compartido, su `SocksPort` es `9050` por defecto (el mismo puerto que usa
Tor standalone; distinto de `9150`, que es el de Tor Browser):

Linux / macOS / WSL (bash):
```bash
export TORVC_USE_BUNDLED_TOR=0
export TORVC_SERVER_URL="ws://<tu-onion-de-señalización>.onion/ws"
export TORVC_SOCKS_HOST=127.0.0.1
export TORVC_SOCKS_PORT=9050
python run.py
```

Windows (PowerShell):
```powershell
$env:TORVC_USE_BUNDLED_TOR = "0"
$env:TORVC_SERVER_URL = "ws://<tu-onion-de-señalización>.onion/ws"
$env:TORVC_SOCKS_HOST = "127.0.0.1"
$env:TORVC_SOCKS_PORT = "9050"
python run.py
```

Windows (CMD):
```bat
set TORVC_USE_BUNDLED_TOR=0
set TORVC_SERVER_URL=ws://<tu-onion-de-señalización>.onion/ws
set TORVC_SOCKS_HOST=127.0.0.1
set TORVC_SOCKS_PORT=9050
python run.py
```

> **`ws://`, no `wss://`**: Nginx (el backend) solo escucha HTTP plano en
> el puerto 80, sin TLS. La confidencialidad la da el propio circuito Tor
> -- un `.onion` ya es extremo-a-extremo cifrado y autenticado por diseño.
> Usar `wss://` contra este backend falla (el cliente intenta un handshake
> TLS contra un socket que solo habla HTTP/WS plano).

Repetí el paso 2 en otra terminal (o máquina) para el segundo
participante — cada instancia de `torvc` es un participante distinto.

No pases `TORVC_DEV_NO_TOR` (o dejalo en `0`): con esa variable activa el
cliente ignora el proxy SOCKS5 por completo.

Alternativa sin variables de entorno: boton "Configuracion de conexion" en
la pantalla de inicio de la app (URL del servidor + host/puerto SOCKS5).

Si en vez de un Tor compartido con el backend preferís que cada
participante use su propio Tor (como sería un despliegue real
multi-máquina): dejá `TORVC_USE_BUNDLED_TOR=1` (default) para que la app
lance su propio proceso Tor vendorizado (ver sección siguiente), o usá Tor
Browser como proxy (`TORVC_SOCKS_PORT=9150`) si preferís no instalar nada
aparte.

### Si falla la conexión

El mensaje de error del cliente incluye el host/puerto de Tor que está
usando, por ejemplo:
```
No se pudo conectar al servidor (¿Tor levantado en 127.0.0.1:9050?): ...
```
Cosas a revisar, de más a menos común:
- El `.onion` recién creado todavía no publicó su descriptor en la red
  (puede tardar uno o varios minutos tras el 100% de bootstrap de Tor) —
  un primer intento con timeout no es necesariamente un error de
  configuración, reintentá.
- Errores de Tor genéricos e intermitentes (`ProxyTimeoutError`,
  `General SOCKS server failure`, o en los logs de Tor mensajes de
  "Guard ... is failing a very large amount of circuits") indican que la
  red Tor actual (la tuya o la pública) está degradada en ese momento, no
  necesariamente un bug — reintentar más tarde o en otra red suele
  resolverlo.
- Puerto equivocado (9050 vs 9150 — ver arriba).
- Tor no está corriendo o todavía no terminó de conectar a
  la red Tor (puede tardar unos segundos).
- La direccion `.onion` tiene un typo o el servicio del backend no esta
  activo en ese momento.

## Probar de punta a punta SIN Tor (con el servidor mock)

Util para validar la UI y el pipeline de media sin depender de Tor ni de
tener el backend real (Docker) levantado. `mock_server/server.py` simula
el protocolo real del backend (captcha, auth por `user_id`, señalización
con envelope `{type,payload}`, y un relay TCP propio) en un solo proceso
Python. En una terminal (con el ambiente `torvc` activado):

```bash
python mock_server/server.py --host 127.0.0.1 --port 8765 --relay-port 9001
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

Con `TORVC_DEV_NO_TOR=1` la app se salta por completo la pantalla de Tor
(ni el propio ni uno externo). Repite el bloque correspondiente en la otra
terminal para el segundo participante.

En la primera ventana: "Crear nueva sala" y copiar numero+contraseña. En la
segunda: "Unirse a una sala" y pegar esas credenciales.

## Empaquetar como .exe (con Tor incluido)

1. Descarga el binario de Tor si todavia no lo hiciste (ver arriba):
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\fetch_tor.ps1
   ```
2. Instala PyInstaller en el ambiente conda `torvc`:
   ```powershell
   conda activate torvc
   pip install pyinstaller
   ```
3. Corre el build:
   ```powershell
   powershell -ExecutionPolicy Bypass -File packaging\build_exe.ps1
   ```
4. El resultado queda en `dist\TorVC\TorVC.exe` (modo "onedir": una carpeta
   con el `.exe` y sus dependencias al lado, mas facil de depurar que un
   único archivo). Esa carpeta completa es portable — se puede copiar a
   otra maquina Windows y correr sin instalar Python, conda, ni Tor por
   separado.

Detalles del build en `packaging/torvc.spec` (que binarios se embeben, que
paquetes necesitan `collect_all` por traer plugins propios como PySide6 y
OpenCV).

El build del `.exe` con PyInstaller no se probó como parte de esta
integración (fuera de alcance: el foco fue la integración de red contra
el backend real). El spec sigue el patron estandar para apps PySide6 +
OpenCV, pero es esperable tener que iterar sobre imports faltantes la
primera vez que lo corras — el error mas comun de PyInstaller es un
`ModuleNotFoundError` en tiempo de ejecucion por un import dinamico que el
analisis estatico no detecto; si pasa, agregalo a `hiddenimports` en el
spec.

Para depurar un fallo de arranque silencioso, cambia `console=False` por
`console=True` en `packaging/torvc.spec` temporalmente: así el `.exe`
abre una consola y muestra el traceback real en vez de cerrarse solo.

## Estructura del proyecto

```
environment.yml            Ambiente conda (recomendado)
requirements.txt           Alternativa pip/venv
run.py                     Punto de entrada
app/
  config.py                 Parametros de conexion y de media (todo en memoria)
  call_controller.py         Orquestador: une red + cifrado + media + UI
  main_window.py              Ventana unica (QStackedWidget)
  tor/
    tor_manager.py             Lanza/controla el proceso Tor propio (RF-03a)
  network/
    ws_client.py              Cliente de señalización (WS) por SOCKS5 (Tor), QThread + asyncio
    relay_client.py            Cliente TCP crudo al relay de media (SOCKS5/directo), handshake de token + X25519
    http_client.py              Fetch del captcha (REST) antes de abrir el WebSocket
    protocol.py                Serializacion de mensajes JSON (envelope) y frames binarios
  security/
    ephemeral.py               X25519 + HKDF + AES-256-GCM, purga en memoria
  media/
    video_capture.py            Captura de camara + compresion WebP
    webp_codec.py                Codec WebP puro (testeable sin Qt)
    audio_io.py                   Captura/reproduccion con Opus
  screens/                     Pantallas de la UI (tor, home, crear, unirse, llamada)
  utils/
    logging_guard.py             Logging solo a stdout, nunca a disco
    qt_env_fix.py                 Evita el conflicto de plugins Qt entre cv2 y PySide6
protocol/PROTOCOL.md         Especificacion del protocolo real (señalización + relay)
mock_server/server.py        Simula el backend real localmente (sin Tor ni Docker)
vendor/tor/                  Binario de Tor vendorizado (no versionado, ver su README)
scripts/fetch_tor.ps1/.sh    Descarga+verifica+extrae el Tor Expert Bundle oficial
packaging/torvc.spec         Spec de PyInstaller (.exe con Tor embebido)
packaging/build_exe.ps1      Script de build del .exe
tests/                       Pruebas unitarias (protocolo, cripto, codec WebP, bootstrap de Tor)
```

## Pruebas

```bash
conda activate torvc
pytest tests/ -v
```

Las pruebas cubren: empaquetado/desempaquetado de frames binarios y
mensajes de señalizacion (envelope `{type,payload}`), el intercambio de
claves X25519+HKDF y cifrado/descifrado AES-GCM (incluyendo que dos salas
distintas nunca deriven la misma clave), el framing por longitud del canal
de relay, el pipeline WebP respetando el limite de 40 KB/frame, y el
parseo del progreso de bootstrap / resolucion de rutas del
`TorProcessManager`.

**Verificación manual de extremo a extremo contra el backend real**
(no solo `mock_server`): se corrió el flujo completo -- captcha real,
`AUTH_REQUEST`/`AUTH_OK`, `CALL_REQUEST`→`INCOMING_CALL`→`CALL_ACCEPTED`→
`ROOM_ASSIGNED`, conexión al relay real, handshake de token + X25519, y un
frame de video cifrado enviado y decodificado correctamente del otro
lado -- usando el código de producción (`WSClient`, `RelayClient`,
`CallController`, `protocol`, `SessionKeyManager`) en dos procesos
separados (como sería el uso real), en dos modalidades:
1. Contra el `docker-compose` del backend real, sin Tor (`TORVC_DEV_NO_TOR=1`).
2. Contra el mismo backend con Tor real de punta a punta (señalización y
   relay ambos por circuitos Tor reales, con direcciones `.onion` v3
   reales).

**Lo que no se verificó visualmente en esta integración:** la GUI de
PySide6 corriendo con cámara/micrófono reales (no había hardware de cámara
disponible en el entorno donde se hizo la integración) ni el empaquetado
`.exe`. La verificación de extremo a extremo usó directamente las clases
de producción (sin mocks), reemplazando solo el origen del frame de video
por uno sintético -- el cifrado, envío, recepción y decodificación son el
código real sin modificar.

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

**La pantalla de arranque se queda en "No se pudo conectar a Tor":**
revisa que corriste `scripts/fetch_tor.ps1`/`.sh` y que
`vendor/tor/<plataforma>/tor(.exe)` existe. Si el proceso Tor arranca pero
nunca llega a `Bootstrapped 100%`, puede ser una red muy restringida
(firewall bloqueando la red Tor, común en redes universitarias/
corporativas) o la red Tor pública temporalmente sobrecargada — en ese
caso probá el flujo de Tor externo con Tor Browser (que suele tener mejor
logica de reintentos/bridges), o reintentá en otra red.

**Se conecta a la sala pero falla al conectar al relay (video/audio no
llega):** si el error menciona `ProxyTimeoutError`, `Connection refused` o
`General SOCKS server failure` al conectar al `.onion` del relay, revisá
primero que el backend tenga `ONION_ADDRESS_POOL` bien configurado (ver su
README) con el puerto virtual del `.onion` igual al puerto de host
(19001, no 9001) — un desajuste ahí da "Connection refused". Si el puerto
está bien pero el error es intermitente, es probablemente inestabilidad
de la red Tor en ese momento, no un problema de configuración.

**El `.exe` empaquetado no arranca o se cierra solo:** cambia `console=False`
a `console=True` en `packaging/torvc.spec`, reconstruí, y corré el `.exe`
desde una terminal para ver el traceback real. El motivo mas comun es un
`ModuleNotFoundError` por un import que PyInstaller no detecto solo — hay
que agregarlo a `hiddenimports` en el spec.

## Siguientes pasos sugeridos

1. Probar la GUI real (cámara + micrófono) en una llamada completa, en dos
   máquinas o dos cuentas de usuario -- la integración de red/protocolo ya
   está verificada, falta la validación visual/de hardware.
2. Generar el `.exe` con `packaging/build_exe.ps1` en Windows real e
   iterar sobre los `hiddenimports` que haga falta agregar.
3. Evaluar correr el cliente desde Tails OS (Perfil 1 de la propuesta).
4. Configurar `ONION_ADDRESS_POOL` con más de 10 direcciones en el backend
   si se espera más de un puñado de llamadas concurrentes (ver README del
   backend).
