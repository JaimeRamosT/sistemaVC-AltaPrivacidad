<#
.SYNOPSIS
    Descarga, verifica (SHA256) y extrae el Tor Expert Bundle oficial para
    Windows x86_64 en vendor/tor/windows/, para que TorVC pueda arrancar su
    propio proceso Tor (dev y luego empaquetado en el .exe con PyInstaller).

.DESCRIPTION
    Este script solo trae binarios OFICIALES de torproject.org y valida su
    checksum SHA256 publicado junto al archivo. Para una herramienta de
    anonimato, la verificacion criptografica es importante: se recomienda
    ademas verificar la firma PGP manualmente (ver el mensaje final del
    script) antes de confiar en el binario para uso real.

.USAGE
    powershell -ExecutionPolicy Bypass -File scripts\fetch_tor.ps1
#>

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$destDir = Join-Path $root "vendor\tor\windows"
New-Item -ItemType Directory -Force -Path $destDir | Out-Null

$indexUrl = "https://dist.torproject.org/torbrowser/"

Write-Host "Buscando la version mas reciente del Tor Expert Bundle en $indexUrl ..."
$index = Invoke-WebRequest -Uri $indexUrl -UseBasicParsing
$versions = $index.Links.href | Where-Object { $_ -match '^\d+\.\d+(\.\d+)?/$' } | ForEach-Object { $_.TrimEnd('/') }
if (-not $versions) {
    throw "No se pudo determinar la version mas reciente desde $indexUrl. Revisa la pagina manualmente."
}
$latest = ($versions | Sort-Object { [version]($_ -replace '[^\d\.]', '') } -Descending)[0]
Write-Host "Version detectada: $latest"

$fileName = "tor-expert-bundle-windows-x86_64-${latest}.tar.gz"
$downloadUrl = "$indexUrl$latest/$fileName"
$checksumUrl = "${downloadUrl}.sha256sum"

$tmpDir = Join-Path $env:TEMP "torvc-tor-fetch"
New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null
$archivePath = Join-Path $tmpDir $fileName

Write-Host "Descargando $downloadUrl ..."
Invoke-WebRequest -Uri $downloadUrl -OutFile $archivePath -UseBasicParsing

Write-Host "Verificando checksum SHA256..."
try {
    $checksumContent = (Invoke-WebRequest -Uri $checksumUrl -UseBasicParsing).Content
    $expectedHash = ($checksumContent -split '\s+')[0].Trim().ToLower()
    $actualHash = (Get-FileHash -Path $archivePath -Algorithm SHA256).Hash.ToLower()
    if ($expectedHash -ne $actualHash) {
        throw "El checksum SHA256 NO coincide. Esperado: $expectedHash / Obtenido: $actualHash. No uses este archivo."
    }
    Write-Host "Checksum SHA256 OK ($actualHash)."
} catch {
    Write-Warning "No se pudo verificar el checksum automaticamente: $_"
    Write-Warning "Verifica manualmente antes de confiar en este binario: $checksumUrl"
}

Write-Host "Extrayendo en $destDir ..."
tar -xzf $archivePath -C $destDir

$torExe = Get-ChildItem -Path $destDir -Filter "tor.exe" -Recurse | Select-Object -First 1
if ($torExe) {
    Write-Host "Listo: $($torExe.FullName)"
} else {
    Write-Warning "Se extrajo el paquete pero no se encontro tor.exe dentro de $destDir. Revisa el contenido manualmente."
}

Write-Host ""
Write-Host "IMPORTANTE (recomendado para una herramienta de anonimato):"
Write-Host "  Este script solo valida el checksum SHA256 publicado en el mismo servidor."
Write-Host "  Para verificacion criptografica completa, valida tambien la firma PGP oficial:"
Write-Host "  https://support.torproject.org/tbb/how-to-verify-signature/"
