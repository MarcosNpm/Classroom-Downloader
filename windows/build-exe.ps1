$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Repo = (Resolve-Path (Join-Path $ScriptDir "..")).Path
$Venv = Join-Path $ScriptDir ".venv-build"
$Python = Join-Path $Venv "Scripts\python.exe"
$Spec = Join-Path $ScriptDir "classroom-dl.spec"
$Dist = Join-Path $ScriptDir "dist"
$Build = Join-Path $ScriptDir "build"

$PyLauncher = Get-Command py -ErrorAction SilentlyContinue
$PythonCommand = Get-Command python -ErrorAction SilentlyContinue
if (-not $PyLauncher -and -not $PythonCommand) {
    Write-Host "No se encontro Python 3.10 o superior." -ForegroundColor Red
    Write-Host "Instala Python desde https://www.python.org/downloads/windows/"
    exit 1
}

if ($PyLauncher) {
    & py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
} else {
    & python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
}
if ($LASTEXITCODE -ne 0) {
    Write-Host "classroom-dl necesita Python 3.10 o superior." -ForegroundColor Red
    exit 1
}

if (-not (Test-Path $Python)) {
    Write-Host "Creando el entorno de compilacion en $Venv..."
    if ($PyLauncher) {
        & py -3 -m venv $Venv
    } else {
        & python -m venv $Venv
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Host "No se pudo crear el entorno de compilacion." -ForegroundColor Red
        exit 1
    }
}

Write-Host "Instalando dependencias de compilacion..."
& $Python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { exit 1 }
& $Python -m pip install -e $Repo pyinstaller
if ($LASTEXITCODE -ne 0) { exit 1 }

Write-Host "Generando el ejecutable..."
& $Python -m PyInstaller --clean --noconfirm --distpath $Dist --workpath $Build $Spec
if ($LASTEXITCODE -ne 0) {
    Write-Host "Fallo la compilacion del ejecutable." -ForegroundColor Red
    exit 1
}

$Exe = Join-Path $Dist "classroom-dl.exe"
if (-not (Test-Path $Exe)) {
    Write-Host "No se encontro el ejecutable generado." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Listo: $Exe" -ForegroundColor Green
Write-Host "Podes copiar ese .exe a otra carpeta o pasarselo a un companero."
