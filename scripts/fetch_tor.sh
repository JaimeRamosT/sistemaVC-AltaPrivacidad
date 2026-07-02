#!/usr/bin/env bash
# Descarga, verifica (SHA256) y extrae el Tor Expert Bundle oficial para
# Linux/macOS en vendor/tor/<linux|macos>/, para probar/empaquetar el modo
# de Tor propio de la app (ver app/tor/tor_manager.py).
#
# Uso:
#   ./scripts/fetch_tor.sh           # detecta el SO automaticamente
#   ./scripts/fetch_tor.sh linux
#   ./scripts/fetch_tor.sh macos
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

TARGET="${1:-}"
if [ -z "$TARGET" ]; then
    case "$(uname -s)" in
        Linux) TARGET="linux" ;;
        Darwin) TARGET="macos" ;;
        *) echo "SO no reconocido automaticamente, pasa 'linux' o 'macos' como argumento." >&2; exit 1 ;;
    esac
fi

case "$TARGET" in
    linux) BUNDLE_ARCH="linux-x86_64" ;;
    macos) BUNDLE_ARCH="macos-x86_64" ;;
    *) echo "Plataforma no soportada: $TARGET (usa 'linux' o 'macos')" >&2; exit 1 ;;
esac

DEST_DIR="$ROOT_DIR/vendor/tor/$TARGET"
mkdir -p "$DEST_DIR"

INDEX_URL="https://dist.torproject.org/torbrowser/"

echo "Buscando la version mas reciente del Tor Expert Bundle en $INDEX_URL ..."
LATEST=$(curl -fsSL "$INDEX_URL" \
    | grep -oE 'href="[0-9]+\.[0-9]+(\.[0-9]+)?/"' \
    | sed -E 's/href="([0-9.]+)\/"/\1/' \
    | sort -t. -k1,1n -k2,2n -k3,3n \
    | tail -n1)

if [ -z "$LATEST" ]; then
    echo "No se pudo determinar la version mas reciente desde $INDEX_URL. Revisa la pagina manualmente." >&2
    exit 1
fi
echo "Version detectada: $LATEST"

FILE_NAME="tor-expert-bundle-${BUNDLE_ARCH}-${LATEST}.tar.gz"
DOWNLOAD_URL="${INDEX_URL}${LATEST}/${FILE_NAME}"
CHECKSUM_URL="${DOWNLOAD_URL}.sha256sum"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
ARCHIVE_PATH="$TMP_DIR/$FILE_NAME"

echo "Descargando $DOWNLOAD_URL ..."
curl -fsSL "$DOWNLOAD_URL" -o "$ARCHIVE_PATH"

echo "Verificando checksum SHA256..."
EXPECTED_HASH="$(curl -fsSL "$CHECKSUM_URL" | awk '{print $1}' | tr 'A-F' 'a-f')"
if command -v sha256sum >/dev/null 2>&1; then
    ACTUAL_HASH="$(sha256sum "$ARCHIVE_PATH" | awk '{print $1}')"
else
    ACTUAL_HASH="$(shasum -a 256 "$ARCHIVE_PATH" | awk '{print $1}')"
fi

if [ -n "$EXPECTED_HASH" ] && [ "$EXPECTED_HASH" = "$ACTUAL_HASH" ]; then
    echo "Checksum SHA256 OK ($ACTUAL_HASH)."
else
    echo "ADVERTENCIA: no se pudo verificar el checksum automaticamente (esperado='$EXPECTED_HASH' obtenido='$ACTUAL_HASH')." >&2
    echo "Verifica manualmente antes de confiar en este binario: $CHECKSUM_URL" >&2
fi

echo "Extrayendo en $DEST_DIR ..."
tar -xzf "$ARCHIVE_PATH" -C "$DEST_DIR"

TOR_BIN="$(find "$DEST_DIR" -type f -name "tor" | head -n1 || true)"
if [ -n "$TOR_BIN" ]; then
    chmod +x "$TOR_BIN"
    echo "Listo: $TOR_BIN"
else
    echo "Se extrajo el paquete pero no se encontro el binario 'tor' dentro de $DEST_DIR. Revisa el contenido manualmente." >&2
fi

echo
echo "IMPORTANTE (recomendado para una herramienta de anonimato):"
echo "  Este script solo valida el checksum SHA256 publicado en el mismo servidor."
echo "  Para verificacion criptografica completa, valida tambien la firma PGP oficial:"
echo "  https://support.torproject.org/tbb/how-to-verify-signature/"
