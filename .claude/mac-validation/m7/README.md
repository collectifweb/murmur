# M7-0 sur un vrai Mac — la porte de décision

Montage inchangé : `.claude/mac-validation/README.md`. Ici, seulement le contenu des
étapes.

**Ce n'est pas une validation, c'est une décision.** M7-0 répond à une question dont
dépend tout le lot : *une `.app` qui lance Python reçoit-elle les fenêtres
d'autorisation à son nom ?* Aujourd'hui elles disent « Terminal ». Si elles continuent,
le bundle ne sert à rien et **les lots M7c à M7h ne seront pas écrits** — on repensera
la distribution.

Deux autres questions se décident en même temps, et par la mesure plutôt que par
l'argument, comme M8 l'a fait pour le nombre d'événements par appui :

- **`exec` ou processus enfant ?** Le lanceur peut remplacer son image par Python, ou
  le lancer et l'attendre. Le second garde vivant un processus dont l'exécutable est
  *dans* le bundle — le cas non ambigu — mais coûte la transmission des signaux.
- **Signature ad-hoc ou certificat local ?** L'ad-hoc accroche l'autorisation à
  l'empreinte du code : si le bundle change, macOS oublie — **en laissant la case
  cochée**, donc en silence. Un certificat persistant l'accrocherait au certificat.

## Côté Linux, pour chaque étape

```bash
cd .claude/mac-validation
tar czf serve/src.tar.gz -C ../../src aparte     # à refaire dès que le code change
cp m7/sonde.py m7/construire-sonde.py serve/     # servis tels quels
SUM=$(sha256sum serve/src.tar.gz | cut -d' ' -f1)
sed -e "s/IP-DU-POSTE-LINUX/192.168.2.11/" -e "s/SHA256-DE-L-ARCHIVE/$SUM/" \
    m7/etape1.sh > serve/step.sh                 # puis etape2.sh, etape3.sh
```

Seule l'étape 1 télécharge du code, donc seule elle porte les deux marqueurs ; le `sed`
sur un fichier sans marqueur ne fait rien, la même commande convient aux trois.

## Ce que chaque étape mesure

| Étape | Ce qu'elle décide | Ce que l'humain doit regarder |
|-------|-------------------|-------------------------------|
| 1 | La variante `exec` : **le nom dans les deux fenêtres**. Plus la quarantaine (`xattr`) sur un bundle construit sur place. | le nom exact écrit dans la fenêtre du micro, puis celle de l'accessibilité, puis dans les Réglages Système — avec quelle icône |
| 2 | La variante « enfant », puis les scénarios **A** (recompilation identique → cdhash identique ?) et **B** (binaire différent → autorisations perdues ?) | si une fenêtre réapparaît après chaque recompilation, et si la case reste cochée alors qu'elle redemande |
| 3 | Le scénario **C**, certificat local. **À ne lancer que si B a fait tomber les autorisations** ou si A s'est révélé non déterministe. | le temps et les blocages pour créer le certificat à la main — c'est son vrai coût |

Le scénario B est celui qui rend le tout concluant : sans lui, on ne saurait pas si A a
tenu grâce au cdhash identique ou parce que macOS s'en moquait.

## Ce qui a déjà été prouvé sous Linux, et qui ne se remesure pas

Le montage entier a été répété ici avec `clang` et `codesign` remplacés par des
doublures : la seule chose qui manque sur cette machine est macOS lui-même.

- Les quatre combinaisons (deux variantes × avec et sans le changement du scénario B)
  **compilent sans le moindre avertissement**.
- `construire-sonde.py` produit un bundle complet et bien formé — `Info.plist`
  lisible par `plistlib` (13 clés, `LSUIElement`, la phrase du micro), l'icône en
  place, le source C retiré du bundle livré.
- Le lanceur compilé **lance vraiment la sonde**, qui écrit son journal : la chaîne
  lanceur → interpréteur → `macos_permissions` tient de bout en bout. Ici tout
  répond « unknown », ce qui est le comportement voulu hors d'un Mac.
- **Les deux variantes sont bien deux choses différentes**, et c'est ce que l'étape 2
  va départager : en `exec`, la chaîne de processus est `bash → python3`, le lanceur
  a disparu ; en « enfant », c'est `aparte → python3`, un processus vivant dont
  l'exécutable est *dans* le bundle.
- **La variante « enfant » transmet ses signaux** : un `SIGTERM` au lanceur est reçu
  par l'interpréteur, qui sort, sans laisser d'orphelin. C'est le prix de cette
  variante, et il est payé.
- Le scénario B **change réellement le binaire** — sinon il ne prouverait rien.
- Deux compilations du même source donnent un binaire **identique à l'octet** (avec
  `gcc` ici ; c'est `clang` sur le Mac que le scénario A confirme).

Ces cinq faits sont dans la suite de tests (`tests/test_macos_desktop.py`,
`LauncherCompilesTest` et `LauncherRunsTest`), pas seulement dans ce fichier.

## Les deux pièges qui ont failli passer

La première version du lanceur appelait `snprintf` sans `<stdio.h>`. Sous `gcc` c'est un
avertissement ; sous le `clang` d'un Xcode récent, c'est une **erreur**, et
`aparte install-app` aurait échoué sur tout Mac à jour. Aucun test de chaîne ne l'aurait
vu — c'est en compilant le C généré qu'on l'a trouvé. Le test est maintenant dans la
suite (`tests/test_macos_desktop.py`, `LauncherCompilesTest`).

Le second était dans ce montage-ci. `construire-sonde.py` ajoutait `src/` au chemin
d'import en comptant un nombre fixe de `.parent` — juste depuis
`.claude/mac-validation/m7/`, faux depuis `~/aparte/.claude-m7/` où l'étape 1 le
copie : il désignait `/Users/src`. L'installation éditable du Mac aurait sauvé la
mise, mais si elle avait manqué, l'étape 1 serait morte sur une erreur d'import
après le `tccutil reset` — donc en ayant déjà effacé les autorisations qu'on voulait
observer. Le dossier se cherche maintenant en remontant jusqu'à trouver
`src/aparte`.

## Après

Ranger chaque journal dans `../journaux/` sous `m7-0-etape*.log`, puis écrire le verdict
dans `docs/plan-portage-macos-m7.md`. Les lots M7c à M7h partent de là — ou pas.
