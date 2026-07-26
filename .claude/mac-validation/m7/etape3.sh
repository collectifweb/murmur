#!/bin/bash
# Aparté M7-0 · étape 3 : SCÉNARIO C — le certificat local auto-signé.
#
# À ne lancer QUE si le scénario B de l'étape 2 a fait tomber les autorisations, ou si
# le scénario A a montré une compilation non déterministe. Sinon l'ad-hoc suffit et
# cette étape est inutile : on ne paye pas un certificat dans le trousseau pour rien.
#
# Ce qu'on mesure : avec un certificat persistant, l'exigence enregistrée par macOS
# s'accroche au certificat au lieu du cdhash, donc un binaire différent devrait garder
# ses autorisations — exactement là où le scénario B les a perdues.
export PYTHONUNBUFFERED=1
APP="$HOME/aparte"
PY="$APP/.venv/bin/python"
SONDE="$APP/.claude-m7"
IDENTITE="Aparté Local"

echo "=== Aparté M7-0 · étape 3 : scénario C, certificat local ==="
cd "$APP" || { echo "introuvable : $APP"; exit 1; }

echo ""
echo "--- 1/5 le certificat existe-t-il déjà ? ---"
if security find-identity -v -p codesigning | grep -q "$IDENTITE"; then
  echo "  certificat « $IDENTITE » déjà présent"
else
  echo "  ABSENT. Il doit être créé À LA MAIN — c'est justement le coût de cette option,"
  echo "  et il faut le mesurer honnêtement. Marche à suivre :"
  echo ""
  echo "    1. Ouvre « Trousseaux d'accès » (Keychain Access)"
  echo "    2. Menu Trousseaux d'accès → Assistant de certification →"
  echo "       Créer un certificat…"
  echo "    3. Nom : $IDENTITE"
  echo "       Type d'identité : Auto-signée racine"
  echo "       Type de certificat : Signature de code"
  echo "    4. Crée, puis relance cette étape."
  echo ""
  echo "  Combien de temps ça t'a pris, et est-ce que quelque chose t'a bloqué ?"
  echo "  (c'est ce qui décidera si on impose ça aux utilisateurs ou pas)"
  echo -n "  Réponse : "; read -r rep_cert
  echo "  → création du certificat : $rep_cert"
  if ! security find-identity -v -p codesigning | grep -q "$IDENTITE"; then
    echo "  certificat toujours absent — étape interrompue."
    exit 1
  fi
fi
security find-identity -v -p codesigning | sed 's/^/  /'

echo ""
echo "--- 2/5 remise à zéro, puis bundle signé avec le certificat ---"
tccutil reset Microphone ca.collectifweb.aparte 2>&1 | sed 's/^/  /'
tccutil reset Accessibility ca.collectifweb.aparte 2>&1 | sed 's/^/  /'
rm -f "$HOME/aparte-m7-sonde.log"
"$PY" "$SONDE/construire-sonde.py" child "$HOME/Applications/Aparté-sonde-cert.app" \
      --identite "$IDENTITE" 2>&1 | sed 's/^/  /'
echo ""
echo "  exigence enregistrée (c'est elle qui change tout) :"
codesign -d -r- "$HOME/Applications/Aparté-sonde-cert.app" 2>&1 | sed 's/^/    /'
C1=$(codesign -dvvv "$HOME/Applications/Aparté-sonde-cert.app" 2>&1 | grep -i "^CDHash=" | head -1)
echo "  $C1"

echo ""
echo "--- 3/5 première ouverture : on accorde les deux autorisations ---"
open "$HOME/Applications/Aparté-sonde-cert.app"
echo ""
echo "  a) Fenêtre du MICRO : quel nom exact ?"
echo -n "  Réponse : "; read -r rep_micro
echo "  → fenêtre micro (certificat) : $rep_micro"
echo ""
echo "  b) Fenêtre de l'ACCESSIBILITÉ : quel nom exact ?"
echo -n "  Réponse : "; read -r rep_acces
echo "  → fenêtre accessibilité (certificat) : $rep_acces"

echo ""
echo "--- 4/5 le même changement que le scénario B, mais signé par le certificat ---"
"$PY" "$SONDE/construire-sonde.py" child "$HOME/Applications/Aparté-sonde-cert.app" \
      --identite "$IDENTITE" --variante "scenario-C" 2>&1 | tail -6 | sed 's/^/  /'
C2=$(codesign -dvvv "$HOME/Applications/Aparté-sonde-cert.app" 2>&1 | grep -i "^CDHash=" | head -1)
echo "  $C2"
if [ "$C1" = "$C2" ]; then
  echo "  → le binaire n'a pas changé : le scénario ne prouve rien, à corriger."
else
  echo "  → binaire bien différent, comme au scénario B."
fi

echo ""
echo "--- 5/5 les autorisations survivent-elles, là où B les avait perdues ? ---"
rm -f "$HOME/aparte-m7-sonde.log"
open "$HOME/Applications/Aparté-sonde-cert.app"
sleep 6
cat "$HOME/aparte-m7-sonde.log" 2>/dev/null | sed 's/^/    /' || echo "    (pas de journal)"
echo ""
echo "  c) Une fenêtre d'autorisation est-elle réapparue ? (oui / non)"
echo "     « non » = le certificat local règle le problème et on l'adopte."
echo "     « oui » = il ne le règle pas non plus, et l'invariant « bundle jamais"
echo "     modifié » reste la seule protection."
echo -n "  Réponse : "; read -r rep_c
echo "  → scénario C, fenêtre réapparue : $rep_c"

echo ""
echo "--- ménage : les sondes n'ont rien à faire dans ~/Applications ---"
rm -rf "$HOME/Applications/Aparté-sonde-"*.app && echo "  sondes retirées"
tccutil reset Microphone ca.collectifweb.aparte 2>&1 | sed 's/^/  /'
tccutil reset Accessibility ca.collectifweb.aparte 2>&1 | sed 's/^/  /'

echo ""
echo "=== étape 3 terminée — M7-0 est complet ==="
