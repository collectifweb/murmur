#!/usr/bin/env python3
"""M7-0 — fabrique un bundle sonde, le compile et le signe. Tourne sur le Mac.

    python3 construire-sonde.py <exec|child> <destination.app> [--variante <suffixe>]
                                [--identite <nom-de-certificat>]

Utilise `aparte.macos_desktop`, donc c'est **le code de M7a** qui est mis à l'épreuve,
pas une maquette écrite pour l'occasion — sinon la mesure ne dirait rien de ce qu'on
livrera.

`--variante` change délibérément le binaire produit (scénario B) : il ajoute une
constante inutilisée au source C, ce qui suffit à changer le cdhash sans rien changer
au comportement. `--identite` signe avec un certificat du trousseau au lieu de l'ad-hoc
(scénario C).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent
SONDE = RACINE / "sonde.py"

sys.path.insert(0, str(RACINE.parent.parent.parent / "src"))

from aparte import macos_desktop  # noqa: E402


def executer(commande: list[str]) -> None:
    print("$ " + " ".join(commande))
    fini = subprocess.run(commande, capture_output=True, text=True)
    if fini.stdout.strip():
        print(fini.stdout.strip())
    if fini.stdout.strip() or fini.stderr.strip():
        print(fini.stderr.strip())
    if fini.returncode != 0:
        raise SystemExit(f"échec ({fini.returncode}) : {' '.join(commande)}")


def main() -> int:
    analyseur = argparse.ArgumentParser()
    analyseur.add_argument("mode", choices=[macos_desktop.LAUNCH_EXEC, macos_desktop.LAUNCH_CHILD])
    analyseur.add_argument("destination")
    analyseur.add_argument("--variante", default="")
    analyseur.add_argument("--identite", default="-")
    arguments = analyseur.parse_args()

    destination = Path(arguments.destination).expanduser()
    if destination.exists():
        shutil.rmtree(destination)

    chemins = macos_desktop.write_bundle(
        destination,
        sys.executable,
        mode=arguments.mode,
        language="fr",
        # La sonde, pas le serveur : on mesure l'attribution, pas la dictée.
        args=(str(SONDE), arguments.mode),
    )

    if arguments.variante:
        # Scénario B : un binaire volontairement différent, à comportement identique.
        # La fonction est exportée pour que le compilateur ne l'élimine pas — sinon le
        # binaire serait inchangé et le scénario ne prouverait rien.
        source = chemins["source"]
        supplement = (
            f'\nstatic const char *kVariante = "{arguments.variante}";\n'
            "const void *aparte_variante(void);\n"
            "const void *aparte_variante(void) { return kVariante; }\n"
        )
        source.write_text(source.read_text(encoding="utf-8") + supplement, encoding="utf-8")

    executer(macos_desktop.clang_command(chemins["source"], chemins["executable"]))
    chemins["source"].unlink()  # le source n'a rien à faire dans le bundle livré

    signature = macos_desktop.codesign_command(destination)
    if arguments.identite != "-":
        signature[signature.index("-", 2)] = arguments.identite
    executer(signature)

    print()
    print(f"bundle : {destination}")
    executer(["codesign", "--verify", "--strict", "--verbose=2", str(destination)])
    executer(["codesign", "-d", "-r-", "--verbose=2", str(destination)])
    executer(["codesign", "-dvvv", str(destination)])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
