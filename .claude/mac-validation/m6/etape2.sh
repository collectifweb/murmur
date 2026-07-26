#!/bin/bash
# Aparté M6 · étape 2 : une dictée, vue depuis la barre de menus.
# Points 3 et 4 : l'icône change en moins d'une demi-seconde, le minuteur défile,
# le titre passe à « … » pendant la transcription, puis tout revient au repos.
export PYTHONUNBUFFERED=1
APP="$HOME/aparte"
PY="$APP/.venv/bin/python"
cd "$APP" || exit 1

echo "=== Aparté M6 · étape 2 : l'icône pendant une dictée ==="

echo ""
echo "--- 1/4 le serveur de l'étape 1 tourne-t-il toujours ? ---"
pgrep -f "aparte desktop" >/dev/null && echo "oui" || { echo "NON — relance l'étape 1"; exit 1; }
echo -n "recording-state : "; curl -sS "http://127.0.0.1:8765/api/recording-state"; echo ""

echo ""
echo "--- 2/4 à toi de jouer ---"
echo ""
echo "  Quand tu appuies sur Entrée ci-dessous, ce script va noter l'heure et"
echo "  observer l'état du serveur pendant 20 secondes."
echo ""
echo "  Pendant ce temps :"
echo "   1. appuie UNE fois sur ⌃⌥D (Contrôle + Option + D),"
echo "   2. dis une phrase — par exemple « bonjour, ceci est un essai »,"
echo "   3. appuie UNE fois sur ⌃⌥D à nouveau,"
echo "   4. et surtout : REGARDE la barre de menus tout du long."
echo ""
echo "  N'appuie pas deux fois de suite pour « voir si ça a marché » : c'est"
echo "  exactement le geste qui a fait rater M8. Une pression, et tu regardes."
echo ""
echo -n "  Prêt ? Entrée pour lancer l'observation : "; read -r _

echo ""
echo "--- 3/4 observation (200 relevés, environ 20 s) ---"
# Le temps est compté en relevés, pas en secondes : le `date` de macOS n'a pas de
# millisecondes. C'est un ordre de grandeur — la latence qui compte vraiment est
# celle que tu vois, question (a) plus bas.
for i in $(seq 1 200); do
  ETAT=$(curl -sS --max-time 1 "http://127.0.0.1:8765/api/recording-state" 2>/dev/null)
  if [ "$ETAT" != "$PRECEDENT" ]; then
    echo "  relevé $i (~$((i / 10)) s) : $ETAT"
    PRECEDENT="$ETAT"
  fi
  sleep 0.1
done
echo "  (fin de l'observation)"

echo ""
echo "--- 4/4 ce que le journal ne peut pas voir ---"
echo ""
echo "  a) Au premier appui, en combien de temps l'icône a-t-elle changé ?"
echo "     (« tout de suite » / « un temps » / « pas changé du tout »)"
echo -n "  Réponse : "; read -r rep_latence
echo "  → latence appui → icône : $rep_latence"
echo ""
echo "  b) Le minuteur (0:01, 0:02, …) s'est-il affiché à côté de l'icône,"
echo "     et défilait-il régulièrement ?"
echo -n "  Réponse : "; read -r rep_minuteur
echo "  → minuteur : $rep_minuteur"
echo ""
echo "  c) Après le second appui, as-tu vu « … » à la place du minuteur"
echo "     pendant la transcription ?"
echo -n "  Réponse : "; read -r rep_points
echo "  → titre pendant la transcription : $rep_points"
echo ""
echo "  d) Et à la fin : l'icône est-elle revenue à sa forme de repos"
echo "     (trois barres, plus de minuteur) ?"
echo -n "  Réponse : "; read -r rep_repos
echo "  → retour au repos : $rep_repos"
echo ""
echo "  e) Le texte a-t-il été inséré quelque part, et la ligne d'état du menu"
echo "     dit-elle « Prêt à dicter » ? (clique l'icône pour voir)"
echo -n "  Réponse : "; read -r rep_texte
echo "  → texte livré / état du menu : $rep_texte"

echo ""
echo "--- l'historique vu par le serveur (dernière entrée) ---"
curl -sS "http://127.0.0.1:8765/api/history" 2>/dev/null | tail -c 400
echo ""
echo ""
echo "=== étape 2 terminée — le serveur reste allumé pour l'étape 3 ==="
