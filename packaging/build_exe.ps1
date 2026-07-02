<#
.SYNOPSIS
    Empaqueta el cliente como .exe autocontenido (con Tor embebido si
    vendor/tor/windows/ esta poblado -- ver scripts/fetch_tor.ps1).

.USAGE
    conda activate torvc
    pip install pyinstaller
    powershell -ExecutionPolicy Bypass -File packaging\build_exe.ps1
#>

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$vendorTor = Join-Path $root "vendor\tor\windows\tor.exe"

if (-not (Test-Path $vendorTor)) {
    Write-Warning "No se encontro $vendorTor."
    Write-Warning "El .exe se generara SIN Tor embebido (la app caera al modo 'Tor externo' en tiempo de ejecucion)."
    Write-Warning "Para un build autocontenido, corre primero: powershell -ExecutionPolicy Bypass -File scripts\fetch_tor.ps1"
    Start-Sleep -Seconds 2
}

if (-not (Get-Command pyinstaller -ErrorAction SilentlyContinue)) {
    throw "PyInstaller no esta instalado en este ambiente. Corre: pip install pyinstaller"
}

Push-Location $root
try {
    pyinstaller (Join-Path "packaging" "torvc.spec") --noconfirm
} finally {
    Pop-Location
}

Write-Host ""
Write-Host "Listo. El ejecutable queda en dist\TorVC\TorVC.exe"
