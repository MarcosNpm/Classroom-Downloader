$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Repo = (Resolve-Path (Join-Path $ScriptDir "..")).Path
$LocalAppData = if ($env:LOCALAPPDATA) {
    $env:LOCALAPPDATA
} else {
    Join-Path $env:USERPROFILE "AppData\Local"
}
$Venv = Join-Path $LocalAppData "classroom-dl\venv"
$Python = Join-Path $Venv "Scripts\python.exe"
$Marker = Join-Path $Venv ".classroom-dl-installed"

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
} catch {
    # Algunas consolas antiguas no permiten cambiar la codificación.
}

$CliArgs = @($args)
$Interactive = $CliArgs.Count -eq 0
if ($Interactive) {
    $CliArgs = @("sync")
}

$PyLauncher = Get-Command py -ErrorAction SilentlyContinue
$PythonCommand = Get-Command python -ErrorAction SilentlyContinue
if (-not $PyLauncher -and -not $PythonCommand) {
    Write-Host ""
    Write-Host "No se encontro Python 3.10 o superior." -ForegroundColor Yellow
    Write-Host "Instala Python desde https://www.python.org/downloads/windows/"
    Write-Host 'Marca la opcion "Add python.exe to PATH" durante la instalacion.'
    if ($Interactive) { Read-Host "Pulsa Enter para cerrar" | Out-Null }
    exit 1
}

if ($PyLauncher) {
    & py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
} else {
    & python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
}
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "La version de Python instalada es demasiado vieja." -ForegroundColor Yellow
    Write-Host "classroom-dl necesita Python 3.10 o superior."
    if ($Interactive) { Read-Host "Pulsa Enter para cerrar" | Out-Null }
    exit 1
}

if (-not (Test-Path $Python)) {
    Write-Host "Creando el entorno de Python en $Venv..."
    if ($PyLauncher) {
        & py -3 -m venv $Venv
    } else {
        & python -m venv $Venv
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Host "No se pudo crear el entorno de Python." -ForegroundColor Red
        if ($Interactive) { Read-Host "Pulsa Enter para cerrar" | Out-Null }
        exit 1
    }
}

if (-not (Test-Path $Marker)) {
    Write-Host "Instalando classroom-dl y sus dependencias..."
    & $Python -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) {
        Write-Host "No se pudo actualizar pip." -ForegroundColor Red
        if ($Interactive) { Read-Host "Pulsa Enter para cerrar" | Out-Null }
        exit 1
    }
    & $Python -m pip install -e $Repo
    if ($LASTEXITCODE -ne 0) {
        Write-Host "No se pudo instalar classroom-dl." -ForegroundColor Red
        if ($Interactive) { Read-Host "Pulsa Enter para cerrar" | Out-Null }
        exit 1
    }
    New-Item -ItemType File -Path $Marker -Force | Out-Null
}

& $Python -m classroom_dl.cli @CliArgs
$Code = $LASTEXITCODE

if ($Interactive) {
    Write-Host ""
    Read-Host "Pulsa Enter para cerrar" | Out-Null
}
exit $Code
