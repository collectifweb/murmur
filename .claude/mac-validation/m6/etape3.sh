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
echo "--- 0/5 deux choses vues de trop loin à l'étape 2 ---"
echo ""
echo "  L'étape 2 a laissé deux doutes, et aucun journal ne peut les lever :"
echo "  le minuteur semblait REMPLACER l'icône, et le « … » de la transcription"
echo "  n'a pas été vu. On refait une dictée, en regardant précisément."
echo ""
echo "  Cette fois, dis une phrase LONGUE — au moins quinze secondes, lis un"
echo "  paragraphe si tu veux. Plus la dictée est longue, plus la transcription"
echo "  qui suit dure, et plus le « … » a le temps de se voir."
echo ""
echo "   1. appuie ⌃⌥D,"
echo "   2. pendant que tu parles, REGARDE juste à gauche des chiffres,"
echo "   3. appuie ⌃⌥D,"
echo "   4. et continue de regarder pendant la transcription."
echo ""
echo -n "  Entrée quand la dictée est finie ET le texte inséré : "; read -r _
echo ""
echo "  a) Pendant que tu parlais : y avait-il un ROND NOIR PLEIN juste à gauche"
echo "     du minuteur, ou seulement les chiffres, tout seuls ?"
echo -n "  Réponse : "; read -r rep_rond
echo "  → rond pendant l'enregistrement : $rep_rond"
echo ""
echo "  b) Et si le rond était là : les trois barres, elles, avaient bien disparu"
echo "     le temps de l'enregistrement ? (c'est voulu — le rond les remplace)"
echo -n "  Réponse : "; read -r rep_barres
echo "  → trois barres pendant l'enregistrement : $rep_barres"
echo ""
echo "  c) Juste après le second appui, pendant la transcription : as-tu vu"
echo "     trois points « … » à côté des trois barres revenues ?"
echo -n "  Réponse : "; read -r rep_points
echo "  → « … » pendant la transcription : $rep_points"

echo ""
echo "--- 1/5 ce que le serveur sait du raccourci ---"
echo -n "hotkey-state : "; curl -sS "http://127.0.0.1:8765/api/hotkey-state"; echo ""
# load_config() rend un dict, pas un Settings — la première écriture de cette
# ligne appelait .hotkey dessus et levait un AttributeError dans le journal.
echo -n "config       : "; "$PY" -c "from aparte.config import load_config; print(repr(load_config().get('hotkey')))"

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
