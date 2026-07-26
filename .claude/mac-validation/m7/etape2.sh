#!/bin/bash
# Aparté M7-0 · étape 2 : la variante « enfant surveillé », puis les scénarios A et B.
#
# Étape 1 a mesuré `execv`, qui remplace l'image du processus : l'exécutable du bundle
# n'existe plus au moment où la demande part. Ici le lanceur reste vivant comme parent —
# le cas non ambigu. Si les deux marchent, on prend `exec` (plus simple) ; si seul
# celui-ci marche, c'est lui.
#
# Puis les deux scénarios de signature qui décident ad-hoc contre certificat local :
#   A — même source, recompilé : le cdhash doit être identique, les autorisations tenir
#   B — binaire volontairement différent : le cdhash change, les autorisations doivent
#       tomber. Sans B, on ne saurait pas si A a tenu grâce au cdhash ou par hasard.
export PYTHONUNBUFFERED=1
APP="$HOME/aparte"
PY="$APP/.venv/bin/python"
SONDE="$APP/.claude-m7"

echo "=== Aparté M7-0 · étape 2 : variante « enfant », puis scénarios A et B ==="
cd "$APP" || { echo "introuvable : $APP"; exit 1; }

echo ""
echo "--- 1/6 remise à zéro et construction de la variante « enfant » ---"
tccutil reset Microphone ca.collectifweb.aparte 2>&1 | sed 's/^/  /'
tccutil reset Accessibility ca.collectifweb.aparte 2>&1 | sed 's/^/  /'
rm -f "$HOME/aparte-m7-sonde.log"
"$PY" "$SONDE/construire-sonde.py" child "$HOME/Applications/Aparté-sonde-child.app" 2>&1 | sed 's/^/  /'

echo ""
echo "--- 2/6 ouverture de la variante « enfant » ---"
open "$HOME/Applications/Aparté-sonde-child.app"
echo ""
echo "  a) Fenêtre du MICRO : quel nom exact ?"
echo -n "  Réponse : "; read -r rep_micro
echo "  → fenêtre micro (enfant) : $rep_micro"
echo ""
echo "  b) Fenêtre de l'ACCESSIBILITÉ : quel nom exact ?"
echo -n "  Réponse : "; read -r rep_acces
echo "  → fenêtre accessibilité (enfant) : $rep_acces"
echo ""
echo "--- ce que la sonde a écrit ---"
cat "$HOME/aparte-m7-sonde.log" 2>/dev/null || echo "(pas de journal)"

echo ""
echo "--- 3/6 SCÉNARIO A : recompiler à l'identique ---"
# Les autorisations viennent d'être accordées ci-dessus ; on ne remet PAS à zéro.
AVANT_CDHASH=$(codesign -dvvv "$HOME/Applications/Aparté-sonde-child.app" 2>&1 | grep -i "^CDHash=" | head -1)
AVANT_BIN=$(shasum -a 256 "$HOME/Applications/Aparté-sonde-child.app/Contents/MacOS/aparte" | cut -d' ' -f1)
echo "  avant : $AVANT_CDHASH"
echo "  avant : binaire $AVANT_BIN"
"$PY" "$SONDE/construire-sonde.py" child "$HOME/Applications/Aparté-sonde-child.app" 2>&1 | tail -6 | sed 's/^/  /'
APRES_CDHASH=$(codesign -dvvv "$HOME/Applications/Aparté-sonde-child.app" 2>&1 | grep -i "^CDHash=" | head -1)
APRES_BIN=$(shasum -a 256 "$HOME/Applications/Aparté-sonde-child.app/Contents/MacOS/aparte" | cut -d' ' -f1)
echo "  après : $APRES_CDHASH"
echo "  après : binaire $APRES_BIN"
if [ "$AVANT_CDHASH" = "$APRES_CDHASH" ]; then
  echo "  → VERDICT A : le cdhash est IDENTIQUE. La compilation est bien déterministe."
else
  echo "  → VERDICT A : le cdhash a CHANGÉ malgré un source identique."
  echo "    C'est le point qui condamnerait l'ad-hoc : même une réinstallation à"
  echo "    l'identique ferait oublier les autorisations. Le certificat local devient"
  echo "    nécessaire (scénario C, étape 3)."
fi

echo ""
echo "--- 4/6 les autorisations ont-elles survécu au scénario A ? ---"
rm -f "$HOME/aparte-m7-sonde.log"
open "$HOME/Applications/Aparté-sonde-child.app"
sleep 6
echo "  ce que la sonde a relu (sans redemander, si tout va bien) :"
cat "$HOME/aparte-m7-sonde.log" 2>/dev/null | sed 's/^/    /' || echo "    (pas de journal)"
echo ""
echo "  c) Une fenêtre d'autorisation est-elle réapparue ? (oui / non)"
echo -n "  Réponse : "; read -r rep_a
echo "  → scénario A, fenêtre réapparue : $rep_a"

echo ""
echo "--- 5/6 SCÉNARIO B : un binaire volontairement différent ---"
"$PY" "$SONDE/construire-sonde.py" child "$HOME/Applications/Aparté-sonde-child.app" \
      --variante "scenario-B" 2>&1 | tail -6 | sed 's/^/  /'
B_CDHASH=$(codesign -dvvv "$HOME/Applications/Aparté-sonde-child.app" 2>&1 | grep -i "^CDHash=" | head -1)
echo "  scénario B : $B_CDHASH"
if [ "$APRES_CDHASH" = "$B_CDHASH" ]; then
  echo "  → ATTENTION : le cdhash n'a pas bougé. Le scénario B n'a rien changé au"
  echo "    binaire, donc il ne prouve rien. À corriger avant de conclure."
else
  echo "  → le cdhash a bien changé : le scénario est valide."
fi

echo ""
echo "--- 6/6 les autorisations ont-elles survécu au scénario B ? ---"
rm -f "$HOME/aparte-m7-sonde.log"
open "$HOME/Applications/Aparté-sonde-child.app"
sleep 6
cat "$HOME/aparte-m7-sonde.log" 2>/dev/null | sed 's/^/    /' || echo "    (pas de journal)"
echo ""
echo "  d) Une fenêtre d'autorisation est-elle réapparue cette fois ? (oui / non)"
echo -n "  Réponse : "; read -r rep_b
echo "  → scénario B, fenêtre réapparue : $rep_b"
echo ""
echo "  e) Ouvre Réglages Système → Confidentialité et sécurité → Microphone."
echo "     La case d'Aparté est-elle toujours cochée, alors même que la fenêtre a"
echo "     peut-être redemandé ? (c'est le piège : cochée mais sans effet)"
echo -n "  Réponse : "; read -r rep_case
echo "  → case dans les Réglages après B : $rep_case"

echo ""
echo "=== étape 2 terminée ==="
