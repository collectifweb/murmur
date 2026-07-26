#!/bin/bash
# Aparté M6 · étape 1 : installer le code de M6 et regarder l'icône apparaître.
# Points 1 et 2 de la checklist : apparition sans vol de focus, rendu template en
# barre claire et en barre sombre.
export PYTHONUNBUFFERED=1
RELAY=http://178.249.214.4:8010
APP="$HOME/aparte"
PY="$APP/.venv/bin/python"

echo "=== Aparté M6 · étape 1 : installation et apparition de l'icône ==="

echo ""
echo "--- 1/6 arrêt de ce qui tourne encore ---"
pkill -f "aparte desktop" 2>/dev/null && echo "ancien serveur arrêté" || echo "rien à arrêter"
sleep 1

echo ""
echo "--- 2/6 récupération du code de M6 ---"
cd "$APP" || { echo "introuvable : $APP"; exit 1; }
if curl -fsS --connect-timeout 8 "$RELAY/src.tar.gz" -o src.tar.gz; then
  tar xzf src.tar.gz -C src && echo "src/aparte remplacé"
else
  echo "téléchargement impossible — le relais sert-il bien src.tar.gz ?"
  exit 1
fi

echo ""
echo "--- 3/6 installation de l'extra macos (apporte rumps) ---"
"$PY" -m pip install -e ".[macos]" 2>&1 | tail -4
"$PY" -c "import rumps; print('rumps', getattr(rumps, '__version__', '?'))"

echo ""
echo "--- 4/6 démarrage du serveur, sans ouvrir le navigateur ---"
# --no-browser : le point 1 est « sans vol de focus », donc rien d'autre ne doit
# venir au premier plan pendant qu'on regarde la barre de menus.
nohup "$PY" -m aparte desktop --no-browser > desktop.log 2>&1 < /dev/null &
SRV=$!
sleep 6
if kill -0 "$SRV" 2>/dev/null; then echo "serveur vivant (pid $SRV)"; else echo "SERVEUR MORT"; fi
echo "--- ce qu'il a écrit au démarrage ---"
cat desktop.log

echo ""
echo "--- 5/6 ce que le serveur dit de lui-même ---"
echo -n "hotkey-state    : "; curl -sS "http://127.0.0.1:8765/api/hotkey-state" || echo "(pas de réponse)"
echo ""
echo -n "recording-state : "; curl -sS "http://127.0.0.1:8765/api/recording-state" || echo "(pas de réponse)"
echo ""
echo "--- doctor (la ligne « Menu-bar icon » est celle de M6) ---"
"$PY" -m aparte doctor 2>&1 | sed -n '1,60p'

echo ""
echo "--- 6/6 ce que le journal ne peut pas voir : à toi de regarder ---"
echo ""
echo "  a) Regarde en haut à droite de l'écran, dans la barre de menus."
echo "     Y a-t-il une petite icône Aparté (trois barres verticales) ?"
echo -n "  Réponse (oui / non / autre) : "; read -r rep_icone
echo "  → icône visible : $rep_icone"
echo ""
echo "  b) Est-ce qu'une fenêtre est passée devant celle-ci pendant le démarrage,"
echo "     ou est-ce que le Terminal est resté au premier plan ?"
echo -n "  Réponse : "; read -r rep_focus
echo "  → vol de focus : $rep_focus"
echo ""
echo "  c) Bascule l'apparence du Mac : menu Pomme → Réglages Système →"
echo "     Apparence → Clair, puis Sombre. Regarde l'icône dans les deux."
echo "     Est-elle nette et lisible des deux côtés (noire sur clair,"
echo "     blanche sur sombre), sans carré ni fond ?"
echo -n "  Réponse : "; read -r rep_theme
echo "  → rendu clair/sombre : $rep_theme"
echo ""
echo "  d) Clique sur l'icône. Le menu s'ouvre-t-il ? Recopie la première ligne"
echo "     (l'état) et la deuxième (le raccourci)."
echo -n "  Réponse : "; read -r rep_menu
echo "  → menu : $rep_menu"

echo ""
echo "=== étape 1 terminée — le serveur reste allumé pour l'étape 2 ==="
