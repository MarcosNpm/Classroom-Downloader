# classroom-dl

CLI en Python para **descargar desde la terminal** los materiales, anuncios, tareas y tus propias entregas de Google Classroom.

- Sincronización incremental: no vuelve a bajar lo que ya tienes.
- Exporta Google Docs/Sheets/Slides a formatos reales (PDF, DOCX, XLSX…).
- Guarda YouTube, Forms y enlaces web como `.url`, incluso si están pegados en la descripción de una tarea, material o anuncio.
- Selección interactiva de cursos o modo script (`--all`, `--course ID`).
- Progreso detallado con `--verbose`: archivo, tamaño, velocidad y tiempo restante.
- Reanudable: descarga a `.part` y renombra al terminar.
- Solo lectura: no modifica nada en Classroom ni en Drive.

---

## 1. Requisitos

- Python 3.10 o superior (probado con 3.13).
- Una cuenta de Google con acceso a Classroom.
- Conexión a internet la primera vez (para el consentimiento OAuth).

## 2. Instalación

### Instalación manual

```bash
cd /home/nickname/carpeta-destino

python3 -m venv .venv
.venv/bin/pip install -e .

# El comando queda disponible dentro del venv:
.venv/bin/classroom-dl --help
```

### Launcher automático para Linux

Si no querés crear el entorno a mano:

```bash
chmod +x linux/classroom-dl.sh
./linux/classroom-dl.sh
```

El launcher crea el entorno en `${XDG_DATA_HOME:-$HOME/.local/share}/classroom-dl/venv`, instala las dependencias y abre el menú interactivo de cursos. También acepta argumentos:

```bash
./linux/classroom-dl.sh sync --all
./linux/classroom-dl.sh sync --all --verbose   # progreso detallado de cada archivo
./linux/classroom-dl.sh courses
```

En Debian/Ubuntu puede hacer falta instalar el módulo `venv`:

```bash
sudo apt install python3 python3-venv
```

Si preferís instalar solo las dependencias, también está `requirements.txt`:

```bash
python3 -m pip install -r requirements.txt
```

Si quieres usarlo desde cualquier carpeta sin activar el venv, crea un alias:

```bash
echo 'alias classroom-dl="/home/name/carpeta-destino/.venv/bin/classroom-dl"' >> ~/.bashrc
source ~/.bashrc
```

> **Windows:** hay launchers para cmd/PowerShell y un build de `.exe` en [`windows/README.md`](windows/README.md). Esa versión es independiente de la instalación de Linux.

---

## 3. Configurar Google Cloud (una sola vez)

Classroom no permite descargar archivos con usuario/contraseña: hay que crear una app OAuth propia. Son 5 minutos.

### 3.1 Crear el proyecto

1. Entra a <https://console.cloud.google.com/>.
2. Arriba a la izquierda, **Seleccionar proyecto → Nuevo proyecto**.
3. Ponle un nombre (por ejemplo `classroom-dl`) y crea.

### 3.2 Habilitar las APIs

1. **APIs y servicios → Biblioteca**.
2. Busca y habilita:
   - **Google Classroom API**
   - **Google Drive API**

### 3.3 Pantalla de consentimiento

1. **APIs y servicios → Pantalla de consentimiento OAuth**.
2. Tipo de usuario: **External** → Crear.
3. Completa nombre de la app, correo de soporte y correo del desarrollador.
4. En **Público / Usuarios de prueba**, agrega **tu propio correo**.
5. Deja la app en modo **Testing** (no hace falta verificación para uso personal).

> **Importante:** en modo *Testing* Google caduca el token cada **7 días**. Cuando la app deje de funcionar, ejecuta `classroom-dl auth --force`. Es una limitación de Google, no de la herramienta.

### 3.4 Crear las credenciales

1. **APIs y servicios → Credenciales → Crear credenciales → ID de cliente de OAuth**.
2. Tipo de aplicación: **Aplicación de escritorio**.
3. **Descargar JSON**.
4. Guárdalo como:

```bash
mkdir -p ~/.config/classroom-dl
mv ~/Descargas/client_secret_*.json ~/.config/classroom-dl/client_secret.json
chmod 600 ~/.config/classroom-dl/client_secret.json
```

También puedes usar `--credentials RUTA` o la variable `CLASSROOM_DL_CREDENTIALS`.

### 3.5 Autorizar

```bash
.venv/bin/classroom-dl auth
```

Se abre el navegador. Inicia sesión con la cuenta que usa Classroom y acepta los permisos. El token queda en `~/.config/classroom-dl/token.json` con permisos `600`.

### Permisos que solicita

| Scope | Para qué |
|---|---|
| `classroom.courses.readonly` | Listar tus cursos |
| `classroom.coursework.me.readonly` | Ver tareas y sus adjuntos |
| `classroom.courseworkmaterials.readonly` | Ver materiales del curso |
| `classroom.announcements.readonly` | Ver anuncios |
| `classroom.student-submissions.me.readonly` | Ver tus entregas |
| `drive.readonly` | Descargar los archivos adjuntos |

Todos son de **solo lectura**.

### 3.6 Probar con compañeros

Cada persona se autoriza con **su propia cuenta**: el token es personal y se guarda solo en su máquina. Hay dos formas de que varios compañeros prueben el proyecto:

**Opción A — compartir el mismo proyecto (rápido, hasta 100 usuarios de prueba)**

1. El dueño del proyecto entra a **Google Auth Platform → Público / Audience → Usuarios de prueba** y agrega el correo de cada compañero.
2. Les pasa el `client_secret.json` por un canal privado (nunca por GitHub, Discord público ni el repo).
3. Cada uno lo guarda en `~/.config/classroom-dl/client_secret.json`, instala el repo y ejecuta `classroom-dl auth`.

**Opción B — cada uno crea su propio proyecto (recomendado si el repo es público)**

Repite la sección 3 completa con su propia cuenta de Google. Son unos 5 minutos y evita compartir credenciales.

Checklist para un compañero desde cero:

```bash
git clone git@github.com:MarcosNpm/Classroom-Downloader.git
cd Classroom-Downloader
python3 -m venv .venv
.venv/bin/pip install -e .

# Guardar su client_secret.json en ~/.config/classroom-dl/client_secret.json
.venv/bin/classroom-dl auth
.venv/bin/classroom-dl sync --dry-run
.venv/bin/classroom-dl sync --all
```

En ambos casos:

- **No compartan `token.json`**: da acceso a la cuenta de esa persona.
- `client_secret.json` y `token.json` ya están en `.gitignore`; no deben subirse al repo.
- El modo *Testing* admite hasta 100 usuarios de prueba y el token caduca a los 7 días para todos.
- Si alguien ve el error `Scope has changed...`, está en la sección de problemas frecuentes.

---

## 4. Uso

### Ver cursos

```bash
classroom-dl courses
classroom-dl courses --teacher          # incluye cursos donde eres profesor
classroom-dl courses --include-archived
classroom-dl courses --json             # para scripts
```

### Ver contenidos sin descargar

```bash
classroom-dl list                       # menú interactivo de cursos
classroom-dl list 123456789             # por ID
classroom-dl list 123456789 --only tareas
classroom-dl list 123456789 --since 2026-03-01
```

### Descargar

```bash
# Interactivo: mueve con ↑/↓, marca con ESPACIO y confirma con Enter
classroom-dl sync

# Todos los cursos
classroom-dl sync --all

# Un curso concreto (repetible)
classroom-dl sync --course 123456789
classroom-dl sync -c 111 -c 222 --jobs 4

# Simular sin escribir nada
classroom-dl sync --all --dry-run

# Solo tareas y entregas, desde una fecha
classroom-dl sync --all --only tareas,entregas --since 2026-03-01

# Revisar si algún archivo cambió en Drive
classroom-dl sync --all --refresh

# Ver el progreso de cada descarga: archivo, tamaño, velocidad y tiempo
classroom-dl sync --all --verbose
```

Tipos disponibles para `--only`: `materiales`, `anuncios`, `tareas`, `entregas` (o sus nombres en inglés), y `all`.

Con `--verbose` se muestra una barra por archivo mientras se descarga. Si la salida no es una terminal (por ejemplo, un cron con salida a un log), se imprimen líneas de texto con el avance y la velocidad, sin códigos ANSI.

### Estado y configuración

```bash
classroom-dl status                     # token, destino y cursos sincronizados
classroom-dl config                     # ver configuración
classroom-dl config --output ~/Classroom --docs-format docx --jobs 4
classroom-dl guide                      # recordatorio de los pasos de Google Cloud
```

Opciones globales (antes del subcomando):

```bash
classroom-dl --output /ruta/destino --jobs 4 sync --all
classroom-dl --credentials ./client_secret.json auth
```

---

## 5. Cómo quedan los archivos

Destino por defecto: `~/Classroom` (configurable).

```
~/Classroom/
└── Programación I - Sección B/
    ├── Materiales/
    │   └── 2026-03-10 - Guía de recursión/
    │       ├── guia.pdf
    │       └── ejemplos.zip
    ├── Anuncios/
    │   └── 2026-03-12 - Cambio de aula/
    │       └── aviso.pdf
    ├── Tareas/
    │   └── 2026-03-15 - Taller 1/
    │       ├── enunciado.pdf
    │       └── datos.xlsx
    ├── Mis entregas/
    │   └── 2026-03-15 - Taller 1/
    │       └── mi_entrega.zip
    └── Enlaces/
        └── 2026-03-15 - Taller 1/
            ├── Formulario.url
            └── Video de YouTube.url
```

- Los nombres se sanean (sin `/ \ : * ? " < > |`) y se truncan.
- Si dos archivos se llaman igual en la misma carpeta: `archivo (2).pdf`.
- Los Google Docs se exportan a PDF por defecto; Sheets a XLSX. Se cambia con `config` o con `--docs-format` / `--sheets-format`.
- Los formularios, Sites o scripts de Apps no son archivos descargables: se guardan como `.url`.

---

## 6. Cómo funciona la sincronización

Cada curso tiene un manifest en:

```
~/.local/state/classroom-dl/manifests/<courseId>.json
```

Ahí se registra cada archivo descargado (ruta, `modifiedTime`, tamaño).

- Si el archivo ya está en el manifest **y existe en disco**, se omite.
- Si borraste el archivo a mano, se vuelve a descargar.
- `--refresh` consulta Drive y actualiza solo los archivos cuyo `modifiedTime` cambió.
- `--prune` olvida del manifest los archivos que ya no están en disco (no borra nada).
- `--dry-run` no escribe archivos ni modifica el manifest.

### Cron / tarea programada

```cron
# Todos los días a las 20:00
0 20 * * * /home/Markus/proyecto_class/.venv/bin/classroom-dl sync --all >> ~/.local/state/classroom-dl/sync.log 2>&1
```

Recuerda reautorizar cada 7 días si la app sigue en modo *Testing*.

---

## 7. Problemas frecuentes

| Síntoma | Causa / solución |
|---|---|
| `No encuentro client_secret.json` | Falta el JSON o está en otra ruta. Usa `--credentials`. |
| `invalid_grant` / `Token has been expired or revoked` | Token caducado (7 días en Testing) → `classroom-dl auth --force`. |
| `403 accessNotConfigured` | No habilitaste Classroom API o Drive API en el proyecto. |
| `403 insufficientPermissions` | Tu cuenta no tiene acceso a ese archivo, o el token es de otra cuenta. |
| `403 userRateLimitExceeded` | Cuota de Google. La app reintenta sola; baja `--jobs` si persiste. |
| `404 File not found` | El profesor borró el archivo o restringió el acceso. |
| Los PDFs de Docs salen vacíos | El documento es muy grande o no es exportable; prueba `--docs-format docx`. |
| `No hay cursos para mostrar` | La cuenta no es alumno en ningún curso activo (prueba `--teacher`). |
| `Scope has changed from ... to ...` | Google no concedió todos los permisos. En **Google Auth Platform → Acceso a los datos** agrega el scope que falta (normalmente `classroom.coursework.me.readonly`) y repite `classroom-dl auth --force`. En la pantalla de consentimiento deja **todas** las casillas marcadas. |
| «Google no ha verificado esta aplicación» | Normal en modo Testing: **Configuración avanzada → Ir a classroom-dl (no seguro)**. |
| La cuenta institucional bloquea la app | Un administrador de Workspace puede restringir apps de terceros. Usa una cuenta personal o pide autorización al admin. |

Para depurar, `sync --verbose` muestra el progreso detallado de las descargas y también los archivos omitidos.

---

## 8. Desarrollo

```bash
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest
.venv/bin/ruff check .
```

Estructura:

```
classroom_dl/
├── cli.py      # comandos typer
├── auth.py     # OAuth y token
├── api.py      # Classroom API, paginación y reintentos
├── drive.py    # descarga y exportación de Drive
├── sync.py     # orquestación y concurrencia
├── progress.py # protocolo de progreso de descargas
├── state.py    # manifest incremental
├── paths.py    # nombres y carpetas seguras
├── ui.py       # tablas rich y selección interactiva
└── config.py   # configuración y rutas XDG
```

---

## 9. Alcance y límites

- Descarga únicamente contenido al que **tu cuenta ya tiene acceso**. No evade permisos ni restricciones de Drive.
- No descarga los archivos entregados por otros compañeros (la API no lo permite con scopes de alumno).
- No sincroniza comentarios, calificaciones ni rúbricas (solo adjuntos y enlaces).
- Respeta los Términos de Servicio de Google y las normas de tu institución.
