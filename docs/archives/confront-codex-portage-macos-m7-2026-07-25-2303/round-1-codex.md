# 1. Ce que j'approuve

## Sortir du cask Homebrew est la bonne décision

Je valide le rejet du cask comme canal principal sous les contraintes actuelles. Le fait nouveau est réel : Homebrew 5.0 annonce la dépréciation des casks sans signature et la désactivation des casks `homebrew/cask` qui échouent Gatekeeper en septembre 2026 ([Homebrew 5.0.0](https://brew.sh/2025/11/12/homebrew-5.0.0/)). Le retrait de `--no-quarantine` n'est pas une nuance cosmétique : Homebrew explique que ce drapeau servait à contourner Gatekeeper pour des apps non signées/non notarisées, et que ce contournement n'est plus une direction acceptée ([Homebrew/brew#20755](https://github.com/Homebrew/brew/issues/20755)). La discussion Homebrew confirme aussi qu'après retrait du mécanisme, les apps non signées installées par cask nécessitent du post-traitement `xattr` comme n'importe quel téléchargement manuel ([discussion #6537](https://github.com/orgs/Homebrew/discussions/6537)).

Donc : ne pas répéter `.app + cask` sans signature/notarisation est correct. Une formula dans un tap personnel est le canal Homebrew le plus honnête si le projet refuse un compte Apple, la notarisation et une chaîne CI macOS.

## Le bundle reste justifié par TCC

Je valide l'objectif produit : faire apparaître "Aparté" dans les demandes micro/Accessibilité au lieu de Terminal ou Python. Le dépôt a déjà une architecture où le processus résident macOS possède des permissions sensibles : micro via AVFoundation, insertion via Accessibilité, raccourci global, tray, et routes HTTP Darwin bridées. Avoir une identité d'application lisible n'est pas du polish ; c'est cohérent avec les invariants de sécurité déjà écrits dans `CLAUDE.md`.

Le plan a aussi raison de traiter `CFBundleIdentifier` comme définitif. Changer cet identifiant après diffusion créerait une nouvelle app aux yeux des réglages système et de TCC.

## Le traitement de `update.py` est nécessaire

Je valide l'ajout d'un état Homebrew distinct. `src/aparte/update.py` ne connaît aujourd'hui que le monde "checkout git + pip install -e ." ; une installation Homebrew retombera en `manual`, ce qui est faux du point de vue utilisateur. Le menu M6 dit déjà `manual` comme "ne tourne pas depuis un dépôt git" : ce message doit devenir `brew upgrade collectifweb/aparte/aparte` pour une formula.

Je valide aussi que `/api/update/apply` reste refusée sur Darwin. Une update par Homebrew est une action native/CLI/menu, pas une mutation déclenchée par le navigateur.

## La progression du modèle au premier lancement est dans le bon lot

Je valide le principe : le modèle ne doit pas être embarqué, mais le téléchargement initial doit devenir visible. C'est cohérent avec le produit et avec la mémoire du projet : ne pas confondre "rien ne sort de la machine pendant la dictée" avec "aucun modèle ne sera jamais téléchargé". Le plan respecte l'invariant Darwin s'il garde une route d'observation en lecture seule et ne déclenche pas le téléchargement depuis HTTP.

## La checklist native est bien ciblée

Les critères "les fenêtres disent Aparté", "Gatekeeper ne bloque pas", "les permissions survivent à `brew upgrade`" et "LaunchAgent via lancement applicatif" sont exactement les points qui doivent décider du lot. Le plan ne prétend pas que les mocks Linux prouvent LaunchServices/TCC, et c'est sain.

# 2. Ce que je désapprouve

## Je refuse le `CFBundleExecutable` en script shell comme hypothèse de base

Le point 2 du plan ne tient pas assez pour être construit dessus. Apple DTS écrit explicitement que TCC attend des clients bundle qu'ils utilisent un exécutable principal natif Mach-O, et qu'un script comme exécutable principal expose à des problèmes TCC ([Apple Developer Forums, "TCC and Main Executables"](https://developer.apple.com/forums/thread/678819)). Le même texte explique que les scripts sont problématiques parce que le système voit l'interpréteur, pas le script, et que "packager un script" n'est pas trivial pour le suivi MAC/TCC.

Donc je ne validerais pas :

```text
Contents/MacOS/aparte  <- script shell
exec /opt/homebrew/opt/aparte/libexec/bin/python3 ...
```

comme architecture M7. Le `exec` qui remplace l'image du processus par un Python hors bundle est précisément la situation à risque. Il est possible que le "responsible process" reste attaché au bundle dans certains cas, mais Apple dit assez clairement que ce chemin peut casser l'attribution. Ici, le bénéfice produit entier dépend de cette attribution. Ce n'est pas un détail.

Correction recommandée : mettre dans `Contents/MacOS/` un très petit lanceur Mach-O natif, compilé localement par la formula, qui résout le chemin `opt`, affiche l'erreur utilisateur si Python manque, puis `execve()` Python. Le code Python peut rester hors bundle ; l'exécutable principal du bundle, lui, doit être natif et signé.

## `codesign` ne doit pas être best-effort

Le plan dit : si `codesign` manque ou refuse, on garde le bundle. Je désapprouve.

Sur Apple Silicon, le code arm64 natif requiert une signature valide, même ad-hoc ; Apple documente qu'une signature ad-hoc suffit, mais qu'une signature est requise pour l'exécution native arm64 ([Apple Platform Security, Rosetta 2](https://support.apple.com/en-nz/guide/security/secebb113be1/web)). Surtout, toute l'histoire TCC du plan repose sur une identité de code stable ou au moins inspectable. Un bundle non signé ou mal signé ne doit pas être présenté comme installé avec succès.

`codesign` est un prérequis dur pour `aparte install-app` sur Mac. En cas d'échec : message clair, code non zéro, pas de bundle "presque bon".

## "Un bundle assemblé localement ne reçoit jamais la quarantaine" est trop catégorique

Le raisonnement est globalement plausible mais la formulation "jamais" est faussement sûre.

Apple documente que `LSFileQuarantineEnabled` vaut `false` par défaut pour les fichiers créés par une app, ce qui soutient l'idée qu'un bundle écrit localement par `aparte install-app` ne reçoit pas automatiquement `com.apple.quarantine` ([Launch Services Keys](https://developer.apple.com/library/archive/documentation/General/Reference/InfoPlistKeyReference/Articles/LaunchServicesKeys.html)). Mais Apple documente aussi que Gatekeeper suit la provenance des fichiers écrits par du logiciel téléchargé ([Gatekeeper and runtime protection](https://support.apple.com/guide/security/gatekeeper-and-runtime-protection-sec5599b66df/web)). Homebrew, de son côté, a du code explicite pour propager la quarantaine dans le monde cask ([Cask::Quarantine](https://docs.brew.sh/rubydoc/Cask/Quarantine.html)).

Je formulerais donc l'invariant ainsi : "une app construite localement par la commande d'installation d'une formula ne devrait pas être quarantinée dans le flux normal Homebrew CLI ; M7 doit le vérifier par `xattr -lr ~/Applications/Aparté.app` sur Mac neuf". Pas "ne reçoit jamais".

## La stabilité octet pour octet est nécessaire en ad-hoc, mais pas prouvée comme suffisante

Le plan a raison sur le risque : avec une signature ad-hoc, TCC ne peut pas s'appuyer sur une identité de développeur. Apple dit qu'une signature ad-hoc n'enregistre aucune identité cryptographique et identifie exactement le programme signé ([Code Signing Requirement Language](https://developer.apple.com/library/archive/documentation/Security/Conceptual/CodeSigningGuide/RequirementLang/RequirementLang.html)). Apple DTS dit aussi que le code unsigned/ad-hoc ne donne pas au système une identité stable entre versions, ce qui produit des prompts excessifs ([Apple Developer Forums](https://developer.apple.com/forums/thread/678819)). Les recherches TCC montrent que la base stocke une exigence de signature `csreq`, pas seulement un bundle id ([Microsoft Security](https://www.microsoft.com/en-us/security/blog/2022/01/10/new-macos-vulnerability-powerdir-could-lead-to-unauthorized-user-data-access/)).

Mais le test "deux builds identiques sous Linux" ne suffit pas. Ce qui compte est le résultat signé sur macOS :

- `codesign -d -r- ~/Applications/Aparté.app` doit être comparé avant/après ;
- le `cdhash` doit être comparé avant/après ;
- TCC doit être vérifié après `brew upgrade`, pas seulement le contenu de fichiers avant signature.

Si le projet garde l'ad-hoc, l'invariant "bundle stable" est un garde-fou utile. Mais il doit être prouvé sur Mac après `codesign`, pas seulement par bytes écrits par Python sur Linux.

## Le plan contredit son propre objectif de désinstallation

Le plan dit que la `.app` vit hors venv, dans `~/Applications`, et qu'un `brew uninstall` ne doit pas laisser une app fantôme. Ces deux phrases ne tiennent pas ensemble avec une formula standard.

Une formula Homebrew ne gère pas proprement un artefact installé dans le home utilisateur au moment de `brew uninstall`. Si `aparte install-app` écrit `~/Applications/Aparté.app`, `brew uninstall aparte` laissera probablement cette app en place, sauf si le projet fournit et documente une commande explicite `aparte uninstall-app`. Ce n'est pas bloquant, mais il faut l'admettre et le traiter dans M7.

# 3. Ce qui manque

## Un lot zéro de preuve TCC avant M7a

Le risque central est trop tard dans le découpage. M7a/M7b peuvent produire beaucoup de code avant que le pari "Aparté est le responsable TCC" soit testé. Je déplacerais la preuve avant le vrai bundle.

Lot proposé :

1. Générer un bundle minimal `ApartéTCCProbe.app`.
2. Utiliser un exécutable principal Mach-O natif, pas un script.
3. Depuis ce lanceur, déclencher une demande micro via AVFoundation ou une demande Accessibilité minimale.
4. Signer ad-hoc.
5. Ouvrir par Finder ou `open`.
6. Vérifier le nom dans la fenêtre et l'entrée dans Réglages Système.
7. Remplacer le bundle par un rebuild signé ad-hoc identique/non identique et observer TCC.

Sans cette preuve, M7 risque de construire une installation élégante qui réattribue encore les permissions à Python ou casse à chaque upgrade.

## Le lanceur natif doit devenir un artefact de premier ordre

Si on accepte le correctif Mach-O, il manque :

- source du trampoline, probablement `packaging/macos/aparte-launcher.c` ;
- compilation locale par la formula avec `clang` ;
- test de son comportement par inspection hors Mac, puis validation native ;
- décision sur architecture : binaire compilé localement donc natif à la machine, ou universal si un jour distribué ;
- signature du bundle après écriture complète ;
- `codesign --verify --deep --strict` dans la validation native.

Ce n'est pas une grosse app native. C'est justement la plus petite surface native capable de satisfaire TCC.

## Le plan ne spécifie pas le plist LaunchAgent

Le principe `open` au lieu du lanceur direct est bon, mais il manque les détails qui évitent les boucles :

- pas de `KeepAlive=true` pour un job dont `/usr/bin/open` rend la main ;
- `RunAtLoad=true` suffit probablement pour l'ouverture de session ;
- pas de `~` dans `ProgramArguments`, car `launchd` ne fait pas d'expansion shell ;
- préférer `open -b ca.collectifweb.aparte` ou `open /Users/.../Applications/Aparté.app` à `open -a ~/Applications/Aparté.app`, selon ce qui est validé ;
- logs stdout/stderr vers `~/Library/Logs/Aparté/` pour diagnostiquer les échecs de login.

Apple recommande `SMAppService` depuis macOS 13 pour les LaunchAgents/LoginItems, et documente aussi `AssociatedBundleIdentifiers` pour les plists legacy ([SMAppService](https://developer.apple.com/documentation/servicemanagement/smappservice?language=objc), [Updating helper executables](https://developer.apple.com/documentation/servicemanagement/updating-helper-executables-from-earlier-versions-of-macos)). Comme M8 a validé Big Sur Intel, on peut rester sur plist legacy, mais il faut l'écrire comme choix de compatibilité, pas comme le mécanisme Apple moderne.

## Le cycle uninstall/repair manque

Il faut des commandes et des états pour :

- `aparte uninstall-app` : retire `~/Applications/Aparté.app` et le LaunchAgent utilisateur ;
- `aparte install-app --force` : remplace proprement l'app ;
- `doctor` détecte "formula présente, app absente", "app présente, préfixe Homebrew disparu", "LaunchAgent pointe vers une app absente" ;
- message de `brew uninstall` ou caveat indiquant la commande de nettoyage.

Sinon le premier `brew uninstall` laissera exactement l'app fantôme que le plan veut éviter.

## La formula doit verrouiller plus de choses

Le plan dit "Python du venv Homebrew" mais ne tranche pas :

- version Python : le projet supporte `>=3.10`, mais M8 a nécessité Python 3.11 ; il faut décider si la formula dépend de `python@3.11`, `python@3.12`, ou du Python Homebrew courant ;
- dépendances natives : vérifier si `sounddevice`/`soundfile` nécessitent explicitement `portaudio`/`libsndfile` dans la formula ou si les wheels suffisent sur les cibles supportées ;
- extras exacts : `whisper`, `recording`, `macos` oui, `cuda` non sur macOS ;
- `brew test` minimal : `aparte --version`, imports PyObjC/rumps/sounddevice, construction du bundle si possible ;
- caveats : `aparte install-app`, `aparte install-hotkey`, ouverture depuis Finder, premier téléchargement du modèle.

## La progression du modèle n'a pas encore de mécanisme

"Observer une progression" est juste, mais il manque le backend. `faster-whisper` peut télécharger via des couches qui ne fournissent pas naturellement un état de progression uniforme. Il faut préciser si M7f :

- précharge explicitement le modèle avec une API contrôlée ;
- observe un fichier/cache Hugging Face ;
- affiche seulement un état indéterminé mais honnête ;
- gère offline/proxy/échec de checksum ;
- persiste l'état "modèle prêt" pour `doctor`.

Sans ça, M7f risque de promettre une progression fine que le moteur ne donne pas.

# 4. Ce que je remettrais en question

## Ad-hoc stable vs certificat local auto-généré

Le plan choisit ad-hoc + bundle octet stable. C'est défendable, mais ce n'est pas la seule option sans compte Apple.

Une identité de signature locale auto-signée, créée dans le trousseau utilisateur, pourrait donner une exigence de code plus stable qu'un `cdhash`, sans Developer ID et sans notarisation. Ce n'est pas équivalent à une signature Apple et ça ne règle pas Gatekeeper pour une app téléchargée, mais pour une app construite localement par formula, ça peut mieux servir TCC. Des retours terrain récents sur TCC/Accessibilité montrent précisément que l'ad-hoc colle au `cdhash`, tandis qu'une identité locale stabilise l'exigence de signature ([exemple documenté](https://nick-liu.com/posts/tcc-cdhash-trap/)).

Je ne dis pas qu'il faut l'adopter : créer un certificat local ajoute de la friction et une surface de support. Mais si l'équipe trouve la contrainte "bundle octet stable pour toujours" trop forte, c'est l'alternative à débattre avant d'empiler des contorsions.

## `~/Applications/Aparté.app` est bon pour l'utilisateur, mauvais pour Homebrew

Le chemin est logique pour Finder/Spotlight et pour l'identité mentale de l'app. Mais il sort du modèle Homebrew. Le compromis réel est :

- Homebrew installe le moteur et la commande ;
- `aparte install-app` installe un artefact utilisateur hors préfixe ;
- Homebrew ne possède plus totalement ce qui est lancé.

Ce compromis peut être acceptable, mais il faut le nommer comme tel. Une formula seule ne donne pas "installer puis ouvrir" ; elle donne "installer, lancer une commande de post-install utilisateur, puis ouvrir".

## Le versionnement du bundle n'est pas forcément interdit pour toujours

Si le projet reste en ad-hoc, ne pas changer le bundle est prudent. Si le projet bascule vers un certificat local stable ou Developer ID un jour, garder une version de lanceur dans `Info.plist` redevient possible et utile pour diagnostics. Je garderais l'invariant formulé comme : "ne rien faire varier dans le bundle tant que l'identité TCC est ad-hoc/cdhash". Pas comme une loi produit permanente.

## Le LaunchAgent est reportable, mais il doit être prouvé tôt si livré

Je suis d'accord que M7g est reportable. En revanche, s'il est livré, il doit avoir sa propre validation native stricte. Le piège n'est pas seulement TCC ; c'est aussi le cycle `open`/`launchd`. Apple documente que les jobs qui se détachent ou sortent peuvent être relancés selon leurs clés, et que `KeepAlive` change complètement la sémantique ([Creating Launch Daemons and Agents](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html)).

Donc : absent de M7 v1, c'est acceptable. Présent sans preuve native, non.

## Le plan est globalement bon, mais son pari central doit changer de forme

Mon jugement net : le plan est bon sur la stratégie de distribution, bon sur la séparation Linux/macOS, bon sur `update.py`, bon sur les validations à exiger. Il est insuffisant sur le mécanisme qui porte tout le lot : le bundle ne doit pas avoir un script shell comme exécutable principal.

La version que je validerais :

- formula Homebrew dans tap personnel ;
- `aparte install-app` construit `~/Applications/Aparté.app` ;
- exécutable principal Mach-O minimal dans le bundle ;
- signature obligatoire, pas best-effort ;
- preuve TCC native avant le reste ;
- `brew upgrade` ne modifie pas le bundle si ad-hoc, ou identité locale stable si on accepte cette friction ;
- LaunchAgent reporté ou spécifié sans `KeepAlive`, sans `~`, et validé sur Mac.

Avec ces corrections, la direction me paraît solide. Sans elles, le plan peut échouer exactement sur le point qu'il prétend résoudre : les autorisations macOS.
