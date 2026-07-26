#!/bin/bash
# Aparté M6 · étape 4 : les deux sorties.
# Point 6 : « Quitter » démonte dans l'ordre, rien ne survit, le port est rendu.
# Point 7 : le Ctrl-C sous rumps — on l'OBSERVE. L'invariant s'écrira après, jamais
# avant : c'est précisément l'erreur corrigée en M8.
#
# Le SIGINT est envoyé par le script à un PID précis. Ne jamais demander un Ctrl-C
# à l'humain : il tuerait le groupe de processus, `tee` compris, et ce journal ne
# partirait jamais.
export PYTHONUNBUFFERED=1
RELAY=http://IP-DU-POSTE-LINUX:8010
APP="$HOME/aparte"
PY="$APP/.venv/bin/python"
cd "$APP" || exit 1

port_pris() { lsof -nP -iTCP:8765 -sTCP:LISTEN >/dev/null 2>&1; }

echo "=== Aparté M6 · étape 4 : « Quitter », puis Ctrl-C ==="

echo ""
echo "--- 1/6 état de départ ---"
pgrep -fl "aparte desktop" || echo "aucun serveur (relance l'étape 1 si c'est inattendu)"
port_pris && echo "port 8765 : occupé" || echo "port 8765 : libre"

echo ""
echo "--- 2/6 à toi : clique « Quitter » dans le menu de l'icône ---"
echo -n "  Fait ? Entrée pour vérifier : "; read -r _
for i in $(seq 1 30); do
  pgrep -f "aparte desktop" >/dev/null || break
  sleep 1
done
echo "  attendu $i s"
if pgrep -fl "aparte desktop"; then
  echo "  ✗ un processus survit"
else
  echo "  ✓ aucun processus « aparte desktop »"
fi
port_pris && echo "  ✗ port 8765 toujours occupé" || echo "  ✓ port 8765 rendu"
echo "  --- fin du journal du serveur (le démontage doit s'y voir) ---"
tail -12 desktop.log

echo ""
echo "--- 3/6 rien ne doit rester du micro ---"
pgrep -fl "afplay|arecord" || echo "  ✓ aucun enregistreur ni lecteur de son en vie"
ls -la "${TMPDIR:-/tmp}"/aparte-* 2>/dev/null || echo "  ✓ aucun fichier de capture laissé derrière"

echo ""
echo "--- 4/6 code corrigé, puis relance pour la seconde sortie ---"
# La première validation a montré `doctor` annonçant « missing Menu-bar icon ·
# start Aparté » alors que l'icône était là : il tourne dans un autre processus
# que le serveur. Il interroge maintenant une route en lecture seule.
if curl -fsS --connect-timeout 8 "$RELAY/src.tar.gz" -o src.tar.gz; then
  tar xzf src.tar.gz -C src && echo "src/aparte mis à jour"
else
  echo "téléchargement impossible — on continue avec le code en place"
fi
nohup "$PY" -m aparte desktop --no-browser > desktop-ctrlc.log 2>&1 < /dev/null &
SRV=$!
sleep 6
kill -0 "$SRV" 2>/dev/null && echo "serveur vivant (pid $SRV)" || { echo "SERVEUR MORT — étape interrompue"; exit 1; }
echo -n "  l'icône est-elle bien revenue dans la barre de menus ? : "; read -r rep_retour
echo "  → icône après relance : $rep_retour"
echo "  --- doctor doit maintenant voir l'icône du serveur qui tourne ---"
echo -n "  tray-state : "; curl -sS "http://127.0.0.1:8765/api/tray-state"; echo ""
"$PY" -m aparte doctor 2>&1 | grep -i "menu-bar" || echo "  (aucune ligne Menu-bar ?!)"

echo ""
echo "--- 5/6 SIGINT sur ce PID précis (l'équivalent d'un Ctrl-C) ---"
kill -INT "$SRV"
sleep 4
if kill -0 "$SRV" 2>/dev/null; then
  echo "  le processus a SURVÉCU au SIGINT (pid $SRV encore là)"
  VERDICT="survit"
else
  echo "  le processus est mort sur le SIGINT"
  VERDICT="mort"
fi
echo "  --- ce qu'il a écrit ---"
tail -12 desktop-ctrlc.log
echo ""
echo "  Ce qu'on cherche : la ligne « Stopping desktop server. »"
grep -q "Stopping desktop server" desktop-ctrlc.log \
  && echo "  → PRÉSENTE : le démontage a eu lieu ($VERDICT)" \
  || echo "  → ABSENTE : le processus est parti sans démonter ($VERDICT)"

echo ""
echo "--- 6/6 nettoyage de ce qui traînerait ---"
if kill -0 "$SRV" 2>/dev/null; then
  kill "$SRV" 2>/dev/null
  sleep 2
  kill -9 "$SRV" 2>/dev/null
  echo "  serveur arrêté à la main"
fi
port_pris && echo "  ✗ port 8765 encore occupé" || echo "  ✓ port 8765 libre"
echo -n "  l'icône a-t-elle disparu de la barre de menus ? : "; read -r rep_disparue
echo "  → icône après SIGINT : $rep_disparue"

echo ""
echo "=== étape 4 terminée — plus aucun serveur ne tourne ==="
