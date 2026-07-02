# Protocolo real del cliente (backend TorZoom)

> Este documento describe el protocolo que el cliente habla realmente contra
> el backend TorZoom (repo `Anonymized-video-calls-over-the-Tor-network`,
> `manager/protocol/messages.go` + `manager/internal/signaling/handler.go` +
> `tcp-relay/main.go`). Reemplaza la versión anterior de este archivo, que
> describía el contrato de `mock_server/server.py` (un modelo de "sala con
> código+contraseña" que el backend real no implementa). `mock_server` fue
> reescrito para simular este protocolo localmente, sin Tor ni Docker -- ver
> su propio docstring para el alcance exacto y las simplificaciones.

## 1. Transporte

- El cliente **nunca** se conecta directo a Internet. Toda conexión sale por
  un proxy **SOCKS5** local de Tor (`127.0.0.1:9050` por defecto,
  configurable) -- RNF-01b. En modo `TORVC_DEV_NO_TOR=1` (solo pruebas
  locales contra el docker-compose del backend) esto se salta.
- **Dos conexiones TCP separadas por llamada**, no una sola como en el
  borrador anterior:
  1. **Señalización**: `ws://<onion-de-señalización>/ws` (nótese `ws://`,
     no `wss://` -- Nginx no termina TLS, la confidencialidad la da el
     circuito Tor), persistente durante toda la sesión (desde crear/unirse
     a una sala hasta colgar). Ver `app/network/ws_client.py`.
  2. **Media**: una conexión TCP cruda directa a `onion_address:port` del
     relay asignado (`ROOM_ASSIGNED`, ver sección 3), que dura lo que dura
     la llamada activa. Ver `app/network/relay_client.py`.
- No se usa WebRTC ni UDP en ningún punto -- RNF-02b.

## 2. Señalización (JSON, envelope `{type, payload}`)

A diferencia del borrador anterior (mensajes planos `{"type": ..., "campo":
...}`), el backend real envuelve el payload:

```json
{"type": "TIPO_EN_MAYUSCULAS", "payload": { ... }}
```

El backend solo entiende un conjunto **fijo** de tipos -- no hay un
"reenvía esto tal cual al otro peer" genérico como tenía `mock_server`.

### 2.1 Autenticación (obligatoria, primer mensaje tras conectar)

Antes de `AUTH_REQUEST` hay que pedir un captcha de un solo uso por REST:

```
POST /api/captcha/challenge  ->  {"captcha_token": "cap_..."}
```
(ver `app/network/http_client.py`)

**Cliente -> Servidor**:
```json
{"type": "AUTH_REQUEST", "payload": {"user_id": "...", "captcha_token": "cap_..."}}
```

**Servidor -> Cliente**:
```json
{"type": "AUTH_OK", "payload": {"user_id": "...", "server_ts": 1751385600123}}
{"type": "AUTH_FAIL", "payload": {"reason": "invalid_captcha" | "rate_limited"}}
```

`user_id` es un identificador efímero elegido por el cliente. Como el
backend modela "llamar a un usuario" y no "salas", el cliente mapea su UX
de sala así (ver `app/call_controller.py`):

- Quien **crea** la sala se autentica con
  `user_id = sha256(f"{room_id}:{password}")` -- calculable por cualquiera
  que conozca el código+contraseña, igual que antes.
- Quien **se une** se autentica con un `user_id` propio aleatorio
  (`uuid4`), desechable, y llama al hash de arriba como `target_user_id`.

### 2.2 Llamada

**Cliente -> Servidor** -- iniciar llamada (quien se une llama al hash de sala):
```json
{"type": "CALL_REQUEST", "payload": {"call_id": "...", "target_user_id": "...", "call_type": "video"}}
```

**Servidor -> Cliente** -- al destinatario (quien creó la sala):
```json
{"type": "INCOMING_CALL", "payload": {"call_id": "...", "caller_user_id": "...", "call_type": "video"}}
```
El cliente **acepta automáticamente** toda `INCOMING_CALL` mientras espera
en una sala (no hay paso de confirmación manual, igual que antes el
creador nunca aprobaba explícitamente al peer que se unía):
```json
{"type": "CALL_ACCEPTED", "payload": {"call_id": "..."}}
```

**Servidor -> Cliente** -- a ambos participantes, con los datos del relay:
```json
{"type": "ROOM_ASSIGNED", "payload": {
  "call_id": "...", "onion_address": "...", "port": 19001,
  "role": "initiator" | "responder", "token": "tzr_..."
}}
```

Otras respuestas posibles a `CALL_REQUEST`:
```json
{"type": "USER_OFFLINE", "payload": {"target_user_id": "...", "call_id": "..."}}
{"type": "CALL_BUSY", "payload": {"target_user_id": "...", "call_id": "..."}}
```
(el cliente los traduce a los mismos códigos de error que mostraba
`join_room_screen` para "sala no existe" / "sala ocupada")

**Cliente -> Servidor** -- colgar:
```json
{"type": "CALL_ENDED", "payload": {"call_id": "..."}}
```
El backend lo reenvía al otro participante con el mismo tipo, y destruye el
contenedor del relay.

### 2.3 Keepalive

El backend cierra la conexión si no recibe **ningún mensaje de aplicación**
en 45s (los pings/pongs propios del protocolo WebSocket no cuentan para
ese temporizador). Por eso `WSClient` manda esto cada 20s mientras la sesión
está viva, de forma totalmente interna (no lo maneja `call_controller.py`):
```json
{"type": "HEARTBEAT", "payload": {"ts": 1751385600123}}
{"type": "HEARTBEAT_ACK", "payload": {"client_ts": ..., "server_ts": ...}}
```

### 2.4 Errores

```json
{"type": "ERROR", "payload": {"code": "...", "message": "..."}}
```

## 3. Canal de media (TCP crudo directo al relay, NO WebSocket)

El backend no reenvía datos de aplicación arbitrarios entre los dos peers
de una llamada (a diferencia de `mock_server`), así que tanto el
intercambio de clave de sesión como los frames de media viajan por esta
conexión, no por la de señalización. Ver `tcp-relay/main.go` (lado
servidor) y `app/network/relay_client.py` (lado cliente).

Secuencia sobre la conexión TCP a `onion_address:port`:

1. Cliente escribe `token + "\n"` (el `token` de `ROOM_ASSIGNED`) en un
   único `write()`. El relay valida solo el *formato* (prefijo `tzr_`), no
   el contenido -- la identidad ya la validó el manager.
2. Relay responde `"OK\n"`.
3. Cada lado escribe sus **32 bytes crudos** de clave pública X25519 (sin
   framing, tamaño fijo) y lee los 32 bytes del otro lado. Cada cliente
   deriva localmente (HKDF-SHA256, salt = `room_id`) la clave AES-256-GCM
   de la llamada -- el relay nunca ve esto, son bytes opacos para él.
4. A partir de ahí, cada `MediaFrame` (ver más abajo) va precedido por un
   entero de 4 bytes big-endian con su longitud (`pack_length_prefixed` en
   `app/network/protocol.py`) -- necesario porque, a diferencia de un frame
   binario de WebSocket, una conexión TCP cruda no tiene noción de límites
   de mensaje propios.
5. El relay hace `io.Copy` puro bidireccional entre los dos peers durante
   como máximo 4 horas, o hasta que uno de los dos cierre la conexión.

### 3.1 Formato de `MediaFrame` (cabecera fija de 21 bytes + payload cifrado)

Sin cambios respecto al borrador original -- este formato es transporte-
agnóstico:

| Offset | Tamaño | Campo        | Descripción                                   |
|-------:|-------:|--------------|------------------------------------------------|
| 0      | 1      | `type`       | `0x01` video (WebP), `0x02` audio (Opus), `0x03` control (mute state) |
| 1      | 4      | `seq`        | uint32 BE, contador incremental por stream (independiente por tipo) |
| 5      | 8      | `ts_ms`      | uint64 BE, timestamp de captura (epoch ms)      |
| 13     | 8      | `nonce`      | 8 bytes aleatorios (se combinan con `seq` para formar el nonce de 12 bytes de AES-GCM) |
| 21     | N      | `ciphertext` | payload cifrado + tag GCM (16 bytes al final)   |

El tipo `0x03` (control) es nuevo frente al borrador original: reemplaza el
mensaje `mute_state` de señalización (que ya no existe, ver sección 2). Su
texto plano (antes de cifrar) es `{"audio_muted": bool, "video_muted": bool}`.

Reglas de compresión sin cambios (RNF-03): video 360p/12 FPS/WebP
≤ 40 KB/frame; audio Opus ≤ 32 kbps.

## 4. Ciclo de vida de una llamada

1. A crea sala: genera `room_id`+`password` localmente, se autentica como
   `sha256(room_id:password)`, recibe `AUTH_OK`, espera.
2. A comparte `room_id`+`password` por canal externo seguro.
3. B se une: se autentica con un `user_id` propio aleatorio, envía
   `CALL_REQUEST` contra el hash de A.
4. A recibe `INCOMING_CALL`, acepta automáticamente (`CALL_ACCEPTED`).
5. Ambos reciben `ROOM_ASSIGNED` y conectan al relay indicado: handshake de
   token, luego handshake de clave pública X25519 sobre esa misma conexión.
6. Ambos empiezan a mandar `MediaFrame` cifrados (video/audio/control) por
   el relay.
7. Al colgar, quien cuelga manda `CALL_ENDED`; el backend lo reenvía al
   otro y destruye el contenedor del relay. Ambos clientes purgan claves en
   memoria (`SessionKeyManager.purge()`) y cierran ambas conexiones.

## 5. Diferencias frente al borrador original (para referencia histórica)

| Borrador original (`mock_server`) | Backend real (TorZoom) |
|---|---|
| Mensajes JSON planos `{"type": ...}` | Envelope `{"type", "payload"}` |
| Modelo de sala (código+contraseña, sin auth) | Modelo de usuario (`user_id` + captcha) |
| `create_room`/`join_room`/`peer_joined` | `AUTH_REQUEST`/`CALL_REQUEST`/`INCOMING_CALL`/`CALL_ACCEPTED` |
| Media multiplexada en el mismo WebSocket | Media por una conexión TCP aparte al relay |
| `key_exchange`/`mute_state` vía señalización | Viajan por el canal de relay (pubkey en claro, mute como `MediaFrame` tipo `0x03`) |
| `ping`/`pong` opcional | `HEARTBEAT`/`HEARTBEAT_ACK` obligatorio cada 20s (deadline de 45s del backend) |
