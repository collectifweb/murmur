# Second avis M7 : empaquetage macOS Homebrew

## Avis court

Avis franc : les contraintes écrites ne tiennent pas toutes ensemble.

Le bon objet produit pour Aparté sur Mac est une vraie application `.app`. Mais le choix
"cask Homebrew sans compte développeur Apple, sans signature, sans notarisation" est mal
posé en 2026 si l'objectif est une distribution Homebrew durable et simple. Homebrew a
annoncé avec Homebrew 5.0.0 que les casks sans code signing sont dépréciés et que les
casks `homebrew/cask` qui échouent aux checks Gatekeeper seront désactivés en septembre
2026. La documentation Homebrew liste maintenant `:fails_gatekeeper_check` comme raison
de dépréciation d'un cask.

Donc, sous les contraintes réellement imposées ici -- pas de signature/notarisation, pas
de Mac mainteneur, pas de CI macOS acquise, update Homebrew attendue -- je recommanderais
une formula CLI comme paquet Homebrew honnête, mais en la nommant pour ce qu'elle est :
un canal technique/beta, pas l'expérience Mac finale.

Si le projet veut tenir la promesse M7 "utilisateur Mac normal", alors il faut choisir
`.app`, mais cela implique de rouvrir au moins une contrainte : signature/notarisation à
terme, CI macOS, artefacts de release et remplacement de l'update M6 par Homebrew.

## 1. TCC : le bundle vaut le coût

Oui, le bundle vaut le coût pour TCC. C'est même le meilleur argument pour `.app`.

Aujourd'hui, si l'utilisateur lance Aparté depuis Terminal, macOS demande ou affiche les
permissions pour Terminal, Python, ou un chemin technique. C'est exactement le mauvais
contrat mental : l'utilisateur veut autoriser Aparté à écouter le micro et à coller du
texte, pas autoriser son terminal à contrôler son Mac.

Dans ce dépôt, ce n'est pas cosmétique :

- le micro est demandé explicitement via AVFoundation ;
- l'insertion dépend d'Accessibilité ;
- le raccourci et le tray vivent dans un processus résident ;
- le serveur Darwin interdit déjà les routes HTTP à effet système parce que ce processus
  détient des permissions TCC.

Une formula CLI aggrave donc le flou. Elle peut fonctionner pour un développeur, mais pas
pour l'expérience utilisateur visée. Pour un utilisateur Mac normal, les réglages système
doivent montrer "Aparté", avec une icône, un nom, un `CFBundleIdentifier` stable et une
description micro dans l'`Info.plist`.

Nuance importante : un `.app` non signé n'est pas une base TCC aussi robuste qu'une app
signée/notarisée. L'attribution peut être plus fragile à travers les remplacements de
bundle. Mais même un bundle non signé avec identité stable est plus honnête et plus
lisible qu'une permission donnée à Terminal.

Conclusion de ce point seul : `.app`.

Conclusion globale : ce point ne suffit pas à rendre viable un cask non signé.

## 2. Artefact cask : c'est le vrai coût

Le point le plus dangereux de la décision "cask" n'est pas le code, c'est la discipline
de release.

Un cask Homebrew installe un artefact publié : zip ou dmg contenant l'app. Il ne construit
pas magiquement l'app depuis le source comme une formula. Donc chaque version publiée
d'Aparté devra produire au minimum :

- un `.app` reproductible ;
- une archive téléchargeable ;
- un checksum ;
- idéalement des variantes arm64 et Intel, ou un vrai universal build si les dépendances
  le permettent ;
- une smoke suite manuelle ou CI qui couvre lancement, tray, raccourci, micro,
  Accessibilité, téléchargement du modèle et update/relaunch.

Pour un mainteneur seul sans Mac, sans CI macOS et sans accès régulier à une machine de
test, ce n'est pas tenable. PyInstaller/py2app ne sont pas des opérations abstraites :
les wheels natives, PyObjC, CTranslate2/faster-whisper, les architectures et les chemins
de ressources se vérifient sur macOS.

Cet argument, lui, pousse vers la formula CLI si les contraintes mainteneur sont dures.
GitHub Actions macOS ou un Mac de validation deviennent une dépendance réelle dès qu'on
choisit `.app`.

## 3. Mise à jour M6 : Homebrew remplace le menu actuel

`update.py` est très clair : son monde est "clone git + pip install -e .". Il cherche
un `.git`, avance vers un tag, puis réinstalle les extras détectés dans l'environnement
courant.

Une installation Homebrew n'est pas ce monde, qu'elle soit cask ou formula.

Conséquence directe : dans une installation Homebrew, l'article "Mettre à jour" de
`macos_tray.py` ne doit plus appeler `apply_update()`. L'état actuel `manual` existe
déjà, mais ce serait une mauvaise expérience de menu : "Aparté ne tourne pas depuis un
dépôt git" n'aide pas un utilisateur qui a installé par Homebrew comme demandé.

Je traiterais le code d'update ainsi :

- Linux / installation développeur git : garder `update.py` tel quel ;
- macOS lancé depuis un checkout editable : garder le chemin actuel, utile pour testeur ;
- macOS empaqueté Homebrew : désactiver l'update in-process et afficher une action
  explicite du type `brew upgrade aparte` ou `brew upgrade --cask aparte`, selon le
  canal retenu.

`brew upgrade` devient l'unité de mise à jour. Le menu M6 ne doit pas essayer de refaire
un `git merge` ou un `pip install` dans une installation Homebrew.

## 4. rumps + PyObjC dans un bundle : faisable, mais pas gratuit

Je ne vois pas un bloqueur conceptuel dans `rumps` + PyObjC, mais il faut s'attendre à
des pièges de packaging réels :

- imports paresseux et dynamiques : `rumps`, `AppKit`, `PyObjCTools`, `Quartz`,
  `AVFoundation`, `ApplicationServices` devront probablement être déclarés
  explicitement selon l'outil ;
- ressources : les PNG/SVG de `assets/` doivent être dans le bundle et résolus
  correctement hors checkout ;
- `Info.plist` : `LSUIElement`, `CFBundleIdentifier`, `NSMicrophoneUsageDescription`,
  nom lisible et icône ne sont pas optionnels ;
- sortie : le code M6 a déjà contourné le piège `rumps` du Quit qui bypass le teardown ;
  il ne faut pas le casser avec un template de bundle qui remet un menu Quit système
  inattendu ;
- taille : embarquer Python + dépendances natives + faster-whisper/CTranslate2 peut
  rendre l'app lourde même sans modèle Whisper.

Entre py2app et PyInstaller, je ne trancherais pas abstraitement sans prototype. Le
critère n'est pas "lequel est élégant", c'est : lequel produit un bundle qui lance le
tray, garde la run loop sur le thread principal, trouve les ressources, charge PyObjC,
charge faster-whisper, et survit à une validation sur compte utilisateur frais.

## 5. Carbon et serveur local : le bundle ne change pas le fond

`RegisterEventHotKey` ne devient pas un autre problème parce que l'app est bundlée. Le
besoin reste le même : une `NSApplication` et une run loop AppKit vivante sur le thread
principal. Le dépôt a déjà cette architecture dans `macos_runloop.py`, avec rumps qui
possède la boucle quand le tray existe.

Le bundle peut même rendre ce chemin plus propre : l'application a une identité, un mode
accessory via `LSUIElement`, et un lancement utilisateur normal. Mais il ne dispense pas
de la validation native des raccourcis réservés ou déjà pris ; le dépôt note déjà que
`RegisterEventHotKey` peut accepter des combinaisons qui ne se comportent pas comme prévu.

Le serveur HTTP local sur `127.0.0.1:8765` ne change pas substantiellement dans un bundle.
Il faudra surtout vérifier les cas opérationnels :

- app déjà lancée pendant un upgrade Homebrew ;
- ancienne version encore en mémoire après remplacement du bundle ;
- port occupé si l'utilisateur relance sans quitter ;
- ouverture du panneau depuis le menu ;
- absence de route HTTP privilégiée sur Darwin conservée.

Je ne vois pas de raison de préférer une formula CLI à cause de Carbon ou du serveur
local.

## Point à corriger dans la décision "cask sans compte Apple"

Homebrew peut rendre l'installation moins pénible qu'un zip téléchargé à la main. Mais il
ne transforme pas une app non signée en app signée, notarisée, avec hardened runtime.
Quarantaine, Gatekeeper, signature, notarisation et TCC ne sont pas le même sujet.

Surtout, la phrase "Homebrew retire la quarantaine, donc Gatekeeper ne bloquera pas" est
désormais trop fragile pour servir de décision M7. Homebrew a explicitement déprécié les
comportements de contournement Gatekeeper et les casks sans code signing. Apple dit de
son côté que les apps distribuées hors App Store doivent être signées Developer ID et
notarisées pour passer les réglages Gatekeeper par défaut.

Le vrai énoncé honnête serait :

> Distribution expérimentale par cask Homebrew, sans signature ni notarisation. Plus
> simple qu'un zip non signé ouvert depuis Finder si l'installation effective contourne
> Gatekeeper, mais non durable dans `homebrew/cask` et moins robuste qu'une app Developer
> ID notarisée. Les permissions TCC doivent être validées à chaque forme de bundle et
> après upgrade.

C'est acceptable pour un tap privé expérimental si c'est dit comme ça et testé, mais même
ce chemin a désormais une friction Homebrew propre : depuis Homebrew 6, les taps non
officiels doivent être explicitement approuvés/trustés. Ce ne serait pas acceptable de
laisser croire que Homebrew remplace le modèle de sécurité Apple ou que `homebrew/cask`
acceptera durablement une app qui échoue Gatekeeper.

## Recommandation nette

Sous les contraintes actuelles : choisir CLI formula.

Ce n'est pas le meilleur produit Mac. C'est le paquet Homebrew le plus honnête si le
projet refuse aujourd'hui compte Apple, signature/notarisation, artefacts `.app`
reproductibles et validation macOS régulière. La formula rend aussi la mise à jour
cohérente : `brew upgrade`, pas `git merge` depuis le tray.

Mais il faut être brutalement clair dans la doc : la formula CLI est une installation Mac
avancée, pas la promesse finale "Aparté.app". Les permissions resteront moins lisibles,
probablement attribuées au terminal ou au processus Python, et l'expérience TCC sera moins
propre.

La vraie cible produit reste `.app`. Le jour où le projet accepte la chaîne de release
macOS -- idéalement Developer ID/notarisation, au minimum CI macOS + smoke suite +
artefacts signés/ad-hoc testés -- il faudra basculer vers `.app` et cask. Mais avec la
décision "cask sans compte Apple" telle qu'écrite le 25/07, je ne la validerais pas.

## Sources externes vérifiées le 26 juillet 2026

- Homebrew 5.0.0 : casks sans code signing dépréciés ; désactivation des casks qui
  échouent Gatekeeper prévue en septembre 2026 :
  https://brew.sh/2025/11/12/homebrew-5.0.0/
- Homebrew docs : `:fails_gatekeeper_check` est une raison de dépréciation de cask :
  https://docs.brew.sh/Deprecating-Disabling-and-Removing
- Homebrew docs : les taps non officiels demandent une confiance explicite depuis
  Homebrew 6 :
  https://docs.brew.sh/Tap-Trust
- Apple Platform Security : Gatekeeper vérifie signature Developer ID et notarisation
  pour les logiciels téléchargés hors App Store :
  https://support.apple.com/guide/security/gatekeeper-and-runtime-protection-sec5599b66df/web
- Apple/Xcode : distribution hors Mac App Store, Developer ID, hardened runtime et
  notarisation :
  https://help.apple.com/xcode/mac/current/en.lproj/dev033e997ca.html
- PyInstaller/py2app : les deux permettent d'ajouter bundle identifier et `Info.plist`,
  donc techniquement le `.app` est possible mais doit être produit/testé sur macOS :
  https://pyinstaller.org/en/stable/usage.html
  https://py2app.readthedocs.io/en/latest/tweaking.html
