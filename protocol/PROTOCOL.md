# Protocolo WSS del cliente (borrador para el POC)

> Este documento define el protocolo que asume el cliente de escritorio para hablar
> con el backend (pool de contenedores Docker + direcciones `.onion` v3, ver
> "Segunda iteración: arquitectura básica"). Como el backend ya corre en otro
> espacio y no había especificación disponible, este protocolo es la propuesta
> de referencia para el POC. Si el backend real difiere, solo hay que ajustar
> `app/network/protocol.py` — el resto del cliente no depende de los detalles
> de transporte.

## 1. Transporte

- El cliente **nunca** se conecta directo a Internet. Toda conexión sale por un
  proxy **SOCKS5** local de Tor (`127.0.0.1:9050` por defecto, configurable) — RNF-01b.
- Conexión final: `wss://<direccion>.onion/ws` sobre **TCP** (WebSocket Seguro) — RNF-02a.
- No se usa WebRTC ni UDP en ningún punto — RNF-02b.
- Un único socket WebSocket multiplexa dos tipos de frame:
  - **Frames de texto** → JSON, señalización (control de sala/llamada).
  - **Frames binarios** → media (audio/video) ya comprimida y cifrada.

## 2. Mensajes de señalización (JSON, frames de texto)

Todos los mensajes tienen un campo `type`. El cliente ignora campos desconocidos
(compatibilidad hacia adelante).

### 2.1 Gestión de salas (RF-01)

**Cliente → Servidor** — crear sala:
```json
{"type": "create_room"}
```

**Servidor → Cliente** — sala creada (el backend genera número + password y
define expiración ≤ 30 min, RNF-04e):
```json
{
  "type": "room_created",
  "roomId": "482913",
  "password": "k3f9-qz2p",
  "expiresAt": 1751385600
}
```

**Cliente → Servidor** — unirse a sala existente:
```json
{"type": "join_room", "roomId": "482913", "password": "k3f9-qz2p"}
```

**Servidor → Cliente** — resultado del join:
```json
{"type": "join_ok", "roomId": "482913"}
```
```json
{"type": "join_error", "reason": "invalid_credentials" | "expired" | "room_full"}
```

**Servidor → Cliente** (al creador, cuando el segundo usuario entra):
```json
{"type": "peer_joined"}
```
```json
{"type": "peer_left"}
```

### 2.2 Intercambio de claves de sesión (RNF-04b)

Antes de enviar media, ambos peers negocian una clave simétrica efímera
punto-a-punto (el servidor solo reenvía bytes opacos, no puede leerla):

```json
{"type": "key_exchange", "publicKey": "<base64 X25519 pubkey, 32 bytes>"}
```

Cuando ambos lados han enviado y recibido `key_exchange`, cada cliente deriva
localmente (HKDF-SHA256, ver `app/security/ephemeral.py`) la clave AES-256-GCM
usada para cifrar/descifrar los frames binarios de media. La clave nunca se
transmite ni se escribe a disco.

### 2.3 Control de llamada (RF-02)

```json
{"type": "call_start"}
{"type": "call_end"}
{"type": "mute_state", "audio": true, "video": false}
{"type": "ping", "ts": 1751385600123}
{"type": "pong", "ts": 1751385600123}
```

### 2.4 Errores

```json
{"type": "error", "code": "SESSION_EXPIRED", "message": "..."}
```

## 3. Frames de media (binarios)

Cabecera fija de 21 bytes + payload cifrado:

| Offset | Tamaño | Campo        | Descripción                                   |
|-------:|-------:|--------------|------------------------------------------------|
| 0      | 1      | `type`       | `0x01` = video (WebP), `0x02` = audio (Opus)   |
| 1      | 4      | `seq`        | uint32 BE, contador incremental por stream      |
| 5      | 8      | `ts_ms`      | uint64 BE, timestamp de captura (epoch ms)      |
| 13     | 8      | `nonce`      | 8 bytes aleatorios (se combinan con `seq` para formar el nonce de 12 bytes de AES-GCM) |
| 21     | N      | `ciphertext` | payload cifrado (WebP frame u Opus packet) + tag GCM (16 bytes al final) |

Reglas de compresión (RNF-03):
- Video: 360p, 12 FPS, WebP, objetivo ≤ 40 KB/frame → ≤ 480 Kbps aprox. (RNF-03b).
- Audio: Opus, ≤ 32 kbps (RNF-03d).

## 4. Ciclo de vida de una llamada

1. A crea sala → `create_room` → recibe `room_created`.
2. A comparte `roomId` + `password` por canal externo seguro.
3. B envía `join_room` → recibe `join_ok`; A recibe `peer_joined`.
4. Ambos intercambian `key_exchange` y derivan la clave de sesión en memoria.
5. Ambos envían `call_start` y comienzan a transmitir frames binarios cifrados.
6. Cualquiera puede enviar `mute_state` en cualquier momento.
7. Al colgar, cualquiera envía `call_end`; ambos clientes purgan claves en
   memoria (`SessionKeyManager.purge()`) y cierran el socket. El backend
   ejecuta su propio script de sanitización del contenedor (RNF-04c, fuera
   del alcance del cliente).

## 5. Notas para integrar contra el backend real

- Si los nombres de campo difieren, ajustar únicamente
  `app/network/protocol.py` (serialización) — la UI y los pipelines de media
  consumen objetos Python, no JSON crudo.
- Si el backend ya hace el cifrado de transporte punto a punto de otra forma,
  el módulo `app/security/ephemeral.py` puede desactivarse sin tocar el resto.
