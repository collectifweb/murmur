#!/usr/bin/env python3
"""M7-0 — la sonde TCC. Demande les deux autorisations et écrit ce qu'elle a obtenu.

Lancée **par le bundle**, jamais depuis le Terminal : c'est tout l'objet de la mesure.
Si macOS attribue la demande au bundle, la fenêtre dira « Aparté » ; s'il l'attribue à
l'interpréteur ou au lanceur du bundle, elle dira autre chose, et M7 s'arrête là.

Le journal part dans un fichier, pas sur la sortie standard : une application lancée
depuis le Finder n'a pas de terminal où écrire.
"""

from __future__ import annotations

import datetime
import os
import subprocess
import sys
from pathlib import Path

JOURNAL = Path.home() / "aparte-m7-sonde.log"


def dire(ligne: str) -> None:
    horodatage = datetime.datetime.now().strftime("%H:%M:%S")
    with JOURNAL.open("a", encoding="utf-8") as fichier:
        fichier.write(f"[{horodatage}] {ligne}\n")


def executer(commande: list[str]) -> str:
    try:
        fini = subprocess.run(commande, capture_output=True, text=True, timeout=20)
        return (fini.stdout + fini.stderr).strip()
    except Exception as erreur:  # la sonde ne doit jamais mourir sur un outil manquant
        return f"(échec : {erreur})"


def main() -> int:
    dire("=" * 70)
    dire(f"sonde lancée — variante {sys.argv[1] if len(sys.argv) > 1 else '?'}")
    dire(f"exécutable Python : {sys.executable}")
    dire(f"pid {os.getpid()}, parent {os.getppid()}")

    # Ce que macOS pense être en train d'exécuter. Sur la variante « enfant », le parent
    # est le lanceur du bundle ; sur « exec », il ne reste plus que Python.
    dire(f"chaîne des processus :\n{executer(['ps', '-o', 'pid,ppid,comm', '-p', str(os.getpid()), '-p', str(os.getppid())])}")

    from aparte.macos_permissions import (
        accessibility_trusted,
        microphone_authorization,
        prompt_accessibility,
        request_microphone_access,
    )

    dire(f"micro avant la demande : {microphone_authorization()}")
    dire("→ demande du micro ; REGARDE LE NOM DANS LA FENÊTRE")
    dire(f"micro après la demande : {request_microphone_access()}")

    dire(f"accessibilité avant la demande : {accessibility_trusted()}")
    dire("→ demande de l'accessibilité ; REGARDE LE NOM DANS LA FENÊTRE")
    dire(f"accessibilité après la demande : {prompt_accessibility()}")

    dire("sonde terminée")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
