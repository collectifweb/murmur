#!/bin/bash
# Aparté — M8. Icône unique : va chercher l'étape en cours, l'exécute, renvoie le journal.
RELAY=http://IP-DU-POSTE-LINUX:8010
D="$HOME/aparte-m8"
mkdir -p "$D"
cd "$D" || exit 1

if ! curl -fsS --connect-timeout 8 "$RELAY/step.sh" -o "$D/step.sh"; then
  echo "Impossible de joindre le relais ($RELAY)."
  echo "Vérifie que le PC Linux est allumé et que Mullvad autorise le réseau local."
  echo "Appuie sur Entrée pour fermer."
  read -r _
  exit 1
fi

bash "$D/step.sh" 2>&1 | tee "$D/step.log"
sleep 1
if curl -sS --connect-timeout 8 --upload-file "$D/step.log" "$RELAY/logs/step.log" >/dev/null 2>&1; then
  echo ""
  echo "--- Journal envoyé à Claude. Tu peux fermer cette fenêtre. ---"
else
  echo ""
  echo "--- Journal NON envoyé (relais injoignable). Garde la fenêtre ouverte. ---"
fi
