#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd -- "$SCRIPT_DIR/.." && pwd)"

DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
VENV="$DATA_HOME/classroom-dl/venv"
PYTHON="$VENV/bin/python"
MARKER="$VENV/.classroom-dl-installed"

INTERACTIVE=0
if [ "$#" -eq 0 ]; then
    INTERACTIVE=1
fi

pause_if_interactive() {
    if [ "$INTERACTIVE" -eq 1 ]; then
        printf '\nPulsa Enter para cerrar...'
        read -r _ || true
    fi
}

find_python() {
    local candidate
    for candidate in python3 python3.13 python3.12 python3.11 python3.10 python; do
        if command -v "$candidate" >/dev/null 2>&1; then
            if "$candidate" -c \
                'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' \
                >/dev/null 2>&1; then
                printf '%s\n' "$candidate"
                return 0
            fi
        fi
    done
    return 1
}

PYTHON_BIN="$(find_python || true)"
if [ -z "$PYTHON_BIN" ]; then
    cat <<'EOF'
No se encontro Python 3.10 o superior.

Instala Python y volve a ejecutar este launcher:
  Debian/Ubuntu: sudo apt install python3 python3-venv
  Fedora:        sudo dnf install python3
  Arch:          sudo pacman -S python

Tambien podes descargarlo desde https://www.python.org/downloads/
EOF
    pause_if_interactive
    exit 1
fi

if [ ! -x "$PYTHON" ]; then
    printf 'Creando el entorno de Python en %s...\n' "$VENV"
    if [ -d "$VENV" ]; then
        if ! "$PYTHON_BIN" -m venv --clear "$VENV"; then
            cat <<'EOF'

No se pudo recrear el entorno de Python.
En Debian/Ubuntu suele faltar el paquete python3-venv:
  sudo apt install python3 python3-venv
EOF
            pause_if_interactive
            exit 1
        fi
    elif ! "$PYTHON_BIN" -m venv "$VENV"; then
        cat <<'EOF'

No se pudo crear el entorno de Python.
En Debian/Ubuntu suele faltar el paquete python3-venv:
  sudo apt install python3 python3-venv
EOF
        pause_if_interactive
        exit 1
    fi
fi

if [ ! -f "$MARKER" ]; then
    printf 'Instalando classroom-dl y sus dependencias...\n'
    if ! "$PYTHON" -m pip install --upgrade pip; then
        printf 'No se pudo actualizar pip.\n' >&2
        pause_if_interactive
        exit 1
    fi
    if ! "$PYTHON" -m pip install -e "$REPO"; then
        printf 'No se pudo instalar classroom-dl.\n' >&2
        pause_if_interactive
        exit 1
    fi
    touch "$MARKER"
fi

set +e
if [ "$INTERACTIVE" -eq 1 ]; then
    "$PYTHON" -m classroom_dl.cli sync
else
    "$PYTHON" -m classroom_dl.cli "$@"
fi
CODE=$?
set -e

pause_if_interactive
exit "$CODE"
