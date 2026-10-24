"""Punto de entrada del ejecutable de Windows."""

from __future__ import annotations

import sys

from classroom_dl.cli import main


def run() -> None:
    interactive = len(sys.argv) == 1
    if interactive:
        # Al hacer doble clic no hay argumentos: abrimos el menú de cursos.
        sys.argv.append("sync")

    try:
        main()
    except SystemExit:
        raise
    finally:
        if interactive and sys.stdin.isatty():
            try:
                input("\nPulsa Enter para cerrar...")
            except (EOFError, KeyboardInterrupt):
                pass


if __name__ == "__main__":
    run()
