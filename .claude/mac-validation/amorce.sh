#!/bin/sh
# Amorce M8 : pose sur le Bureau l'icône unique qui exécutera chaque étape.
set -e
RELAY=http://IP-DU-POSTE-LINUX:8010
mkdir -p "$HOME/aparte-m8"
curl -fsS "$RELAY/aparte-etape.command" -o "$HOME/Desktop/aparte-etape.command"
chmod +x "$HOME/Desktop/aparte-etape.command"
echo ""
echo "OK. Sur ton Bureau : 'aparte-etape.command'."
echo "Double-clique dessus pour lancer l'etape en cours."
echo ""
