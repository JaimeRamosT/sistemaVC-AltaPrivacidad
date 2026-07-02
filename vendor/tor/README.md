# Binario de Tor vendorizado

Esta carpeta debe contener el binario oficial de Tor (Tor Expert Bundle)
para que la app pueda lanzar y controlar su propio proceso Tor (ver
`app/tor/tor_manager.py`), en vez de depender de que la persona tenga Tor
Browser o un daemon `tor` corriendo por su cuenta (RF-03a).

**Los binarios NO se versionan en git** (son pesados y binarios; ver
`.gitignore`). Cada quien los descarga localmente con los scripts de abajo.

## Estructura esperada

```
vendor/tor/
  windows/   tor.exe (+ DLLs que traiga el bundle)
  linux/     tor
  macos/     tor
```

`app/tor/tor_manager.py` busca primero `vendor/tor/<plataforma>/tor(.exe)`
directo, y si no lo encuentra ahí, hace una búsqueda recursiva por si el
Tor Expert Bundle anida el binario en una subcarpeta (algunas versiones lo
ponen dentro de `tor/`).

## Cómo obtenerlo

### Windows

```powershell
powershell -ExecutionPolicy Bypass -File scripts\fetch_tor.ps1
```

### Linux / macOS

```bash
./scripts/fetch_tor.sh
```

Ambos scripts descargan la versión más reciente del **Tor Expert Bundle**
directo de `dist.torproject.org` (el distribuidor oficial), verifican el
checksum SHA256 publicado junto al archivo, y extraen el contenido acá.

**No pude ejecutar ni verificar estos scripts yo mismo**: el dominio
`torproject.org` está bloqueado en el entorno donde desarrollé esto. Se
revisaron a mano por sintaxis, pero probalos vos antes de confiar en el
resultado, y si algo no cuadra (versión, estructura del zip, etc.) avisame
para ajustarlos.

### Verificación adicional recomendada

Los scripts solo validan el checksum SHA256 que el propio servidor publica
junto al archivo, lo cual protege contra corrupción en la descarga pero
**no contra un servidor comprometido**. Para una herramienta de anonimato,
lo más riguroso es verificar también la firma PGP oficial del paquete:

https://support.torproject.org/tbb/how-to-verify-signature/

### Alternativa manual

Si preferís no correr los scripts, bajá el "Tor Expert Bundle" a mano desde
https://www.torproject.org/download/tor/ y descomprimí el binario
correspondiente a tu plataforma dentro de la carpeta de arriba.

## Modo sin binario vendorizado

Si no hay binario en `vendor/tor/<plataforma>/`, la app no falla: muestra
un error en la pantalla de arranque con un botón "Usar un Tor externo
(avanzado)", que vuelve al flujo anterior (Tor Browser / daemon `tor`
manejado por el usuario, documentado en el `README.md` principal). También
se puede forzar ese modo de entrada con `TORVC_USE_BUNDLED_TOR=0`.
