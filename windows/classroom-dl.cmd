@echo off
setlocal EnableExtensions

chcp 65001 >nul 2>nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

set "SCRIPT_DIR=%~dp0"
set "REPO=%SCRIPT_DIR%.."
for %%I in ("%REPO%") do set "REPO=%%~fI"

if not defined LOCALAPPDATA set "LOCALAPPDATA=%USERPROFILE%\AppData\Local"
set "VENV=%LOCALAPPDATA%\classroom-dl\venv"
set "PYTHON=%VENV%\Scripts\python.exe"
set "MARKER=%VENV%\.classroom-dl-installed"

set "INTERACTIVE=0"
if "%~1"=="" set "INTERACTIVE=1"

where py >nul 2>nul
if not errorlevel 1 (
    set "BOOTSTRAP=py -3"
    goto :have_python
)

where python >nul 2>nul
if errorlevel 1 goto :no_python
set "BOOTSTRAP=python"

:have_python
%BOOTSTRAP% -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if errorlevel 1 goto :bad_python

if not exist "%PYTHON%" (
    echo Creando el entorno de Python en "%VENV%"...
    %BOOTSTRAP% -m venv "%VENV%"
    if errorlevel 1 goto :install_error
)

if not exist "%MARKER%" (
    echo Instalando classroom-dl y sus dependencias...
    "%PYTHON%" -m pip install --upgrade pip
    if errorlevel 1 goto :install_error
    "%PYTHON%" -m pip install -e "%REPO%"
    if errorlevel 1 goto :install_error
    type nul > "%MARKER%"
)

if "%INTERACTIVE%"=="1" (
    "%PYTHON%" -m classroom_dl.cli sync
) else (
    "%PYTHON%" -m classroom_dl.cli %*
)
set "CODE=%ERRORLEVEL%"

if "%INTERACTIVE%"=="1" (
    echo.
    pause
)
exit /b %CODE%

:no_python
echo.
echo No se encontro Python 3.10 o superior.
echo Instala Python desde https://www.python.org/downloads/windows/
echo Marca la opcion "Add python.exe to PATH" durante la instalacion.
echo.
if "%INTERACTIVE%"=="1" pause
exit /b 1

:bad_python
echo.
echo La version de Python instalada es demasiado vieja.
echo classroom-dl necesita Python 3.10 o superior.
echo.
if "%INTERACTIVE%"=="1" pause
exit /b 1

:install_error
echo.
echo No se pudo preparar el entorno de Python.
echo Revisa tu conexion a internet y vuelve a intentarlo.
echo.
if "%INTERACTIVE%"=="1" pause
exit /b 1
