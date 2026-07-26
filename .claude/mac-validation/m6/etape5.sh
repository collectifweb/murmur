#!/bin/bash
# Aparté M6 · étape 5 : sans rumps, tout le reste tient.
# Point 9 : une installation sans l'extra `macos` n'a pas d'icône — c'est un choix
# d'installation, pas une panne. Le serveur, le raccourci et la dictée doivent
# marcher exactement comme avant, et `doctor` doit dire comment récupérer l'icône.
export PYTHONUNBUFFERED=1
APP="$HOME/aparte"
PY="$APP/.venv/bin/python"
cd "$APP" || exit 1

echo "=== Aparté M6 · étape 5 : le repli sans rumps ==="

echo ""
echo "--- 1/6 désinstallation de rumps (elle sera annulée en fin d'étape) ---"
pkill -f "aparte desktop" 2>/dev/null; sleep 1
"$PY" -m pip uninstall -y rumps 2>&1 | tail -2
"$PY" -c "import rumps" 2>&1 | tail -1

echo ""
echo "--- 2/6 doctor doit le signaler, sans crier ---"
"$PY" -m aparte doctor 2>&1 | sed -n '1,60p'

echo ""
echo "--- 3/6 démarrage : le serveur doit vivre comme avant ---"
nohup "$PY" -m aparte desktop --no-browser > desktop-sans-rumps.log 2>&1 < /dev/null &
SRV=$!
sleep 6
kill -0 "$SRV" 2>/dev/null && echo "serveur vivant (pid $SRV)" || echo "SERVEUR MORT"
cat desktop-sans-rumps.log
echo -n "page d'accueil : HTTP "; curl -sS -o /dev/null -w "%{http_code}\n" "http://127.0.0.1:8765/"
echo -n "hotkey-state   : "; curl -sS "http://127.0.0.1:8765/api/hotkey-state"; echo ""

echo ""
echo "--- 4/6 aucune notification alarmante ne doit être apparue ---"
echo "  (une dépendance absente est un choix, pas une panne — seul un échec"
echo "   inattendu a le droit de klaxonner)"
echo -n "  As-tu vu passer une notification ? Laquelle ? : "; read -r rep_notif
echo "  → notification : $rep_notif"
echo -n "  Y a-t-il quelque chose dans la barre de menus ? (attendu : rien) : "; read -r rep_barre
echo "  → barre de menus : $rep_barre"

echo ""
echo "--- 5/6 le raccourci doit encore dicter ---"
echo "  Appuie ⌃⌥D, dis une phrase, appuie ⌃⌥D. Sans icône, le seul retour est"
echo "  le bip — c'est exactement la situation d'avant M6."
echo -n "  Entrée quand c'est fait : "; read -r _
echo -n "  Le texte a-t-il été inséré ? : "; read -r rep_dictee
echo "  → dictée sans icône : $rep_dictee"
echo -n "recording-state : "; curl -sS "http://127.0.0.1:8765/api/recording-state"; echo ""

echo ""
echo "--- 6/6 remise en état ---"
kill "$SRV" 2>/dev/null; sleep 2; kill -9 "$SRV" 2>/dev/null
"$PY" -m pip install -e ".[macos]" 2>&1 | tail -3
"$PY" -c "import rumps; print('rumps de retour :', getattr(rumps, '__version__', '?'))"
nohup "$PY" -m aparte desktop --no-browser > desktop.log 2>&1 < /dev/null &
sleep 6
pgrep -f "aparte desktop" >/dev/null && echo "serveur relancé" || echo "serveur NON relancé"
echo -n "  l'icône est-elle revenue ? : "; read -r rep_retour
echo "  → icône après réinstallation : $rep_retour"

echo ""
echo "=== étape 5 terminée — M6 est passée sur cette machine ==="
