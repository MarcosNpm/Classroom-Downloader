# classroom-dl en Windows

Esta carpeta es independiente de la instalación de Linux. No cambia el comportamiento de Linux: agrega launchers para **cmd / PowerShell** y un build de **.exe** para Windows.

## Opción 1: launcher para cmd (recomendado)

Requisitos:

- Windows 10 u 11.
- Python 3.10 o superior instalado desde <https://www.python.org/downloads/windows/>.
- Durante la instalación de Python, marcar **Add python.exe to PATH**.

Pasos:

1. Clonar o descargar este repositorio.
2. Guardar el `client_secret.json` de Google en:

   ```text
   %LOCALAPPDATA%\classroom-dl\client_secret.json
   ```

   Si la carpeta no existe, crearla. El token se guardará después en la misma carpeta como `token.json`.

3. Hacer doble clic en:

   ```text
   windows\classroom-dl.cmd
   ```

   La primera vez crea un entorno en `%LOCALAPPDATA%\classroom-dl\venv`, instala las dependencias y abre el menú interactivo de cursos. Las siguientes veces arranca directo. No hace falta instalar `requirements.txt` a mano: el launcher usa `pyproject.toml`.

4. Elegir los cursos con **↑/↓**, marcar con **ESPACIO** y confirmar con **Enter**.

También se puede usar desde cmd o PowerShell pasando comandos:

```bat
windows\classroom-dl.cmd courses
windows\classroom-dl.cmd sync --all
windows\classroom-dl.cmd sync --all --verbose
windows\classroom-dl.cmd sync --course 689753457843
windows\classroom-dl.cmd auth --force
```

Cuando se ejecuta con argumentos no hace `pause`; cuando se hace doble clic deja la ventana abierta al terminar para poder leer el resumen.

## Opción 2: PowerShell

Si preferís PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\windows\classroom-dl.ps1
```

O con argumentos:

```powershell
powershell -ExecutionPolicy Bypass -File .\windows\classroom-dl.ps1 sync --all
```

El `-ExecutionPolicy Bypass` es solo para ejecutar este script; no cambia la política del sistema.

## Opción 3: .exe standalone

El `.exe` no necesita Python instalado. Se puede generar de dos formas.

### Compilarlo en Windows

```powershell
powershell -ExecutionPolicy Bypass -File .\windows\build-exe.ps1
```

El resultado queda en:

```text
windows\dist\classroom-dl.exe
```

Se puede copiar a otra carpeta o pasar a un compañero. Al hacer doble clic abre una consola y el menú interactivo.

### Descargarlo desde GitHub Actions

El workflow `.github/workflows/build-windows.yml` compila el `.exe` en `windows-latest` cuando se ejecuta manualmente o cuando se crea un tag `v*`.

1. Ir a **Actions → Build Windows EXE → Run workflow**.
2. Descargar el artifact `classroom-dl-windows`.
3. Descomprimirlo y ejecutar `classroom-dl.exe`.

El `.exe` no está firmado digitalmente. Windows SmartScreen puede mostrar una advertencia la primera vez; es normal en ejecutables generados con PyInstaller. Solo ejecutalo si lo generaste vos o confiás en el repositorio.

## Rutas en Windows

- Configuración, `client_secret.json` y `token.json`:

  ```text
  %LOCALAPPDATA%\classroom-dl\
  ```

- Descargas por defecto:

  ```text
  %USERPROFILE%\Classroom\
  ```

- Estado y manifests:

  ```text
  %LOCALAPPDATA%\classroom-dl\manifests\
  ```

## Problemas frecuentes

| Síntoma | Solución |
|---|---|
| `No se encontro Python 3.10 o superior` | Instalar Python y marcar “Add python.exe to PATH”. |
| `No encuentro client_secret.json` | Guardarlo en `%LOCALAPPDATA%\classroom-dl\client_secret.json`. |
| PowerShell bloquea el `.ps1` | Usar `classroom-dl.cmd` o ejecutar con `-ExecutionPolicy Bypass`. |
| SmartScreen bloquea el `.exe` | Es un ejecutable sin firma; compilarlo uno mismo o usar el `.cmd`. |
| Windows Firewall pregunta por Python | Permitir el acceso en redes privadas para completar el OAuth local. |
| El token vence cada 7 días | Ejecutar `classroom-dl.cmd auth --force` (modo Testing de Google). |
| La consola muestra acentos raros | Usar `classroom-dl.cmd`, que configura UTF-8; o ejecutar `chcp 65001` antes. |
