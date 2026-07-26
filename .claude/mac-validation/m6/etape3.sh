#!/bin/bash
# Aparté M6 · étape 3 : le menu dit-il la vérité ?
# Points 5 et 8 : la ligne de raccourci reflète l'état réel de l'inscription, et
# la mise à jour refuse de partir pendant une dictée.
export PYTHONUNBUFFERED=1
APP="$HOME/aparte"
PY="$APP/.venv/bin/python"
cd "$APP" || exit 1

echo "=== Aparté M6 · étape 3 : les lignes du menu, et « Mettre à jour » ==="

echo ""
echo "--- 1/5 ce que le serveur sait du raccourci ---"
echo -n "hotkey-state : "; curl -sS "http://127.0.0.1:8765/api/hotkey-state"; echo ""
echo -n "config       : "; "$PY" -c "from aparte.config import load_config; print(repr(load_config().hotkey))"

echo ""
echo "--- 2/5 la ligne du menu doit dire la même chose ---"
echo ""
echo "  Clique l'icône et recopie la ligne du raccourci telle quelle."
echo "  (« Raccourci : ⌃⌥D », « Aucun raccourci… », « Raccourci indisponible… »)"
echo -n "  Réponse : "; read -r rep_ligne
echo "  → ligne raccourci : $rep_ligne"

echo ""
echo "--- 3/5 les autres articles ---"
echo ""
echo "  a) « Copier la dernière dictée » : clique, puis colle (⌘V) dans TextEdit."
echo "     Est-ce bien la dernière phrase dictée à l'étape 2 ?"
echo -n "  Réponse : "; read -r rep_copie
echo "  → copier : $rep_copie"
echo ""
echo "  b) « Réglages » : le navigateur s'ouvre-t-il sur la page d'Aparté,"
echo "     avec le tiroir des réglages déjà ouvert ?"
echo -n "  Réponse : "; read -r rep_reglages
echo "  → réglages : $rep_reglages"

echo ""
echo "--- 4/5 « Rechercher une mise à jour… » pendant une dictée ---"
echo ""
echo "  Enchaîne sans traîner :"
echo "   1. appuie UNE fois sur ⌃⌥D (le micro s'ouvre, le minuteur défile),"
echo "   2. ouvre le menu et clique « Rechercher une mise à jour… »,"
echo "   3. regarde la notification qui apparaît,"
echo "   4. appuie ⌃⌥D pour arrêter."
echo ""
echo -n "  Qu'a dit la notification ? : "; read -r rep_refus
echo "  → mise à jour pendant la dictée : $rep_refus"
echo ""
echo "  Attendu : « Une dictée est en cours — réessaie après. » Rien ne doit"
echo "  s'installer, et la dictée ne doit pas être perturbée."
echo ""
echo -n "  La dictée s'est-elle terminée normalement malgré le clic ? : "; read -r rep_dictee
echo "  → dictée intacte : $rep_dictee"

echo ""
echo "--- 5/5 « Rechercher une mise à jour… » au repos ---"
echo ""
echo "  Reclique l'article, cette fois sans dicter. La barre de menus doit rester"
echo "  cliquable pendant la vérification (elle interroge le réseau)."
echo ""
echo -n "  Qu'a dit la notification ? : "; read -r rep_check
echo "  → vérification au repos : $rep_check"
echo ""
echo -n "  Le menu est-il resté réactif pendant ce temps ? : "; read -r rep_fige
echo "  → barre figée ou non : $rep_fige"
echo ""
echo "  (Ce Mac reçoit son code par archive, pas par git : « ne suit aucune"
echo "  branche distante » ou « ne tourne pas depuis un dépôt git » sont des"
echo "  réponses justes. L'installation complète attend une vraie release, M7.)"

echo ""
echo "--- pour le journal : ce que le serveur répond à la même question ---"
curl -sS "http://127.0.0.1:8765/api/update/check"
echo ""
echo ""
echo "=== étape 3 terminée — le serveur reste allumé pour l'étape 4 ==="
