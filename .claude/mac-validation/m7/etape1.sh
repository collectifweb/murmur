#!/bin/bash
# Aparté M7-0 · étape 1 : la variante « exec » demande-t-elle au nom d'Aparté ?
#
# C'est LA question du lot. Si la fenêtre dit « Terminal » ou « Python », le bundle
# ne sert à rien et M7 s'arrête ici — les lots suivants ne seront pas écrits.
export PYTHONUNBUFFERED=1
RELAY=http://IP-DU-POSTE-LINUX:8010
APP="$HOME/aparte"
PY="$APP/.venv/bin/python"
SONDE="$APP/.claude-m7"

ARCHIVE_SHA=SHA256-DE-L-ARCHIVE

recuperer_le_code() {
  # Le relais parle en clair sur le réseau local, et ce qu'il sert ici devient le
  # code exécuté sur le Mac : la somme de contrôle est ce qui distingue notre
  # archive de n'importe quelle autre. Injectée au moment de servir l'étape.
  curl -fsS --connect-timeout 8 "$RELAY/src.tar.gz" -o src.tar.gz || return 1
  if ! echo "$ARCHIVE_SHA  src.tar.gz" | shasum -a 256 -c - >/dev/null 2>&1; then
    echo "SOMME DE CONTRÔLE FAUSSE — archive refusée, rien n'a été extrait."
    echo "attendue : $ARCHIVE_SHA"
    echo "reçue    : $(shasum -a 256 src.tar.gz | cut -d' ' -f1)"
    return 2
  fi
  tar xzf src.tar.gz -C src && echo "src/aparte mis à jour (somme vérifiée)"
}

echo "=== Aparté M7-0 · étape 1 : la variante « exec » ==="

echo ""
echo "--- 1/7 arrêt de ce qui tourne encore ---"
pkill -f "aparte desktop" 2>/dev/null && echo "ancien serveur arrêté" || echo "rien à arrêter"
sleep 1

echo ""
echo "--- 2/7 récupération du code ---"
cd "$APP" || { echo "introuvable : $APP"; exit 1; }
recuperer_le_code || { echo "sans le code, cette étape n'a rien à mesurer."; exit 1; }

echo ""
echo "--- 3/7 récupération des outils de la sonde ---"
mkdir -p "$SONDE"
for f in sonde.py construire-sonde.py; do
  curl -fsS --connect-timeout 8 "$RELAY/$f" -o "$SONDE/$f" && echo "reçu : $f" || echo "MANQUANT : $f"
done

echo ""
echo "--- 4/7 les outils en ligne de commande sont-ils là ? ---"
echo -n "clang    : "; xcrun -f clang 2>/dev/null || command -v clang || echo "ABSENT — xcode-select --install"
echo -n "codesign : "; command -v codesign || echo "ABSENT"
echo "architecture : $(uname -m)"
sw_vers

echo ""
echo "--- 5/7 état des autorisations AVANT toute demande ---"
# On repart d'une page blanche, sinon une autorisation déjà accordée à Terminal
# masquerait complètement le résultat.
echo "remise à zéro TCC pour l'identifiant de la sonde :"
tccutil reset Microphone ca.collectifweb.aparte 2>&1 | sed 's/^/  /'
tccutil reset Accessibility ca.collectifweb.aparte 2>&1 | sed 's/^/  /'
rm -f "$HOME/aparte-m7-sonde.log"

echo ""
echo "--- 6/7 construction du bundle sonde, variante « exec » ---"
cd "$APP" || exit 1
"$PY" "$SONDE/construire-sonde.py" exec "$HOME/Applications/Aparté-sonde-exec.app" 2>&1 | sed 's/^/  /'

echo ""
echo "la quarantaine a-t-elle été posée sur un bundle construit sur place ?"
echo "(c'est l'affirmation du plan : elle ne devrait PAS l'être)"
xattr -lr "$HOME/Applications/Aparté-sonde-exec.app" 2>&1 | sed 's/^/  /'
echo "  → si rien ne s'affiche au-dessus, aucun attribut étendu : c'est le résultat attendu"

echo ""
echo "empreinte du code (à comparer aux étapes suivantes) :"
codesign -dvvv "$HOME/Applications/Aparté-sonde-exec.app" 2>&1 | grep -iE "cdhash|identifier|signature|flags" | sed 's/^/  /'
shasum -a 256 "$HOME/Applications/Aparté-sonde-exec.app/Contents/MacOS/aparte" | sed 's/^/  binaire : /'

echo ""
echo "--- 7/7 à toi de jouer : le journal ne peut pas voir une fenêtre ---"
echo ""
echo "  Je vais ouvrir la sonde depuis le Finder (donc par LaunchServices,"
echo "  exactement comme un utilisateur double-cliquerait)."
echo "  DEUX fenêtres d'autorisation vont apparaître, l'une après l'autre."
echo ""
open "$HOME/Applications/Aparté-sonde-exec.app"
echo "  (ouverte — réponds OUI aux deux fenêtres, puis reviens ici)"
echo ""
echo "  a) La fenêtre du MICRO : quel nom exact était écrit dedans ?"
echo "     Recopie la phrase entière si tu peux."
echo -n "  Réponse : "; read -r rep_micro
echo "  → fenêtre micro : $rep_micro"
echo ""
echo "  b) La fenêtre de l'ACCESSIBILITÉ : quel nom exact ?"
echo -n "  Réponse : "; read -r rep_acces
echo "  → fenêtre accessibilité : $rep_acces"
echo ""
echo "  c) Ouvre Réglages Système → Confidentialité et sécurité → Microphone."
echo "     Quel nom est listé, et avec quelle icône (le carré carmin d'Aparté,"
echo "     une icône générique, un terminal) ?"
echo -n "  Réponse : "; read -r rep_reglages
echo "  → entrée dans les Réglages : $rep_reglages"

echo ""
echo "--- ce que la sonde a écrit de son côté ---"
cat "$HOME/aparte-m7-sonde.log" 2>/dev/null || echo "(pas de journal — la sonde n'a pas démarré)"

echo ""
echo "=== étape 1 terminée ==="
