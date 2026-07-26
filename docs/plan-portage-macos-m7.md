# M7 — L'installation macOS

_Plan consolidé après contre-expertise (`/confront-codex`, 3 rounds, consensus bilatéral
le 25/07/2026). Archives du débat :
`docs/archives/confront-codex-portage-macos-m7-2026-07-25-2303/`. Second avis initial :
`docs/archives/avis-codex-m7-empaquetage-2026-07-25.md`._

## Contexte

Ce qu'il a fallu faire pour qu'Aparté tourne sur un Mac pendant M8 : installer Python
3.11 depuis python.org, télécharger une archive, créer un environnement virtuel, lancer
`pip install --prefer-binary` avec les bons extras, attendre 500 Mo de modèle — tout en
ligne de commande. C'est le contraire de la promesse.

Et un défaut de fond, trouvé pendant M8 : les autorisations macOS sont accordées à
**Terminal**, pas à Aparté. La fenêtre dit « Terminal souhaite accéder au micro ».
L'utilisateur autorise son terminal à écouter, ce qui n'est ni ce qu'il veut ni ce qu'on
lui demande vraiment.

## Le fait nouveau

La décision initiale était : **cask Homebrew, sans compte développeur Apple**, en
s'appuyant sur le fait que Homebrew retire lui-même l'attribut de quarantaine.

**Ce n'est plus vrai.**

- Homebrew a **supprimé `--no-quarantine`** (version 5.1, mars 2026). Un cask pose
  désormais la quarantaine, sans option pour la refuser.
- Homebrew **retire tous les casks qui échouent au contrôle Gatekeeper le
  1er septembre 2026**. Leur audit exige signature **et** notarisation.
- Depuis macOS Sequoia, le clic droit → Ouvrir ne suffit plus : il faut passer par
  Réglages Système → Confidentialité et sécurité → Ouvrir quand même.

Un cask non signé n'entre plus dans le dépôt officiel, et dans un dépôt personnel il
installe une application que macOS refuse d'ouvrir en annonçant qu'elle est endommagée.

**Les formulas ne sont pas concernées.** La restriction ne vise que les casks.

Sources : [Homebrew/brew#20755](https://github.com/Homebrew/brew/issues/20755),
[discussion #6537](https://github.com/orgs/Homebrew/discussions/6537),
[Homebrew 5.0.0](https://brew.sh/2025/11/12/homebrew-5.0.0/).

## La décision

**Une formula Homebrew dans un dépôt personnel, et une `.app` construite sur la machine
de l'utilisateur.**

Trois faits la portent.

1. **Une formula n'est pas un cask** : pas d'audit Gatekeeper, pas de notarisation, pas
   de date butoir.
2. **La quarantaine est posée par ce qui télécharge.** Une application construite
   localement par la commande d'installation ne devrait pas la recevoir dans le flux
   Homebrew normal — affirmation **à vérifier** en M7-0 par `xattr -lr`, pas un axiome.
3. **Les autorisations TCC suivent l'application responsable**, celle que LaunchServices
   a démarrée. C'est pour ça qu'aujourd'hui c'est Terminal : c'est lui qui lance Python.

Le parcours réel, écrit sans l'arrondir :

```
brew install collectifweb/aparte/aparte
aparte install-app --open
(deux autorisations, au nom d'Aparté)
```

**Deux commandes, puis deux autorisations** — pas « installer → ouvrir ». Le cask aurait
donné une commande ; il est mort. `install-app --open` ouvre l'application à la fin, donc
la seconde commande *est* l'étape « ouvrir ». On perd une étape par rapport à la promesse
initiale, on gagne des autorisations qui disent enfin « Aparté ». C'est le meilleur
échange disponible, et il se dit tel quel dans la documentation.

Aucun compte Apple. Aucun Mac pour fabriquer les versions — la construction se fait chez
l'utilisateur, comme toute formula. Aucune intégration continue macOS.

**Ce que ça ne donne pas, et qu'il faut dire :** une signature ad-hoc n'est pas une
signature Apple. Aparté reste une application non notarisée, distribuée hors de l'App
Store, par un dépôt Homebrew personnel.

## M7-0 — la porte de décision

**Aucun autre lot ne commence avant sa réponse.** Le pari central du lot — « Aparté
devient le responsable TCC » — ne se vérifie que sur un vrai Mac, et M8 a montré ce que
coûte une hypothèse non observée (un `Segmentation fault` à la première exécution
native, invisible en test mocké). Si aucune variante ne donne les deux autorisations au
nom d'Aparté avec une conservation acceptable, **on ne construit pas derrière** : on
repense la distribution.

**Deux variantes de lanceur**, parce que la question ne se tranche pas par raisonnement :

| Variante | Le lanceur… | Pari |
|---|---|---|
| `execve` | remplace son image par Python | un seul processus, mais l'exécutable principal du bundle n'existe plus |
| enfant surveillé | lance Python et l'attend | le processus dont l'exécutable est *dans* le bundle reste vivant — cas non ambigu |

**Les deux autorisations**, pour chaque variante : micro par AVFoundation **et**
accessibilité par `AXIsProcessTrustedWithOptions`. La promesse produit en compte deux ;
n'en mesurer qu'une laisserait la moitié non vérifiée.

**Trois scénarios de signature**, parce que sans le B on ne saurait pas si le A a tenu
grâce au `cdhash` identique ou parce que TCC s'en moquait :

| # | Scénario | Attendu |
|---|---|---|
| A | ad-hoc, rebuild réellement identique | même `cdhash`, autorisations conservées |
| B | ad-hoc, rebuild volontairement différent, `CFBundleIdentifier` constant | `cdhash` différent, **autorisations perdues** |
| C | certificat local auto-signé, rebuild différent | exigence liée au certificat, autorisations conservées |

**Relevés, pour chaque combinaison** : le nom affiché dans la fenêtre, l'entrée et
l'icône dans Réglages Système, `codesign --verify --strict`, `codesign -d -r-`, le
`cdhash`, le mode de lancement (Finder ou `open`), et `xattr -lr` sur le bundle neuf.

**Isolation** : `tccutil reset Microphone` et `tccutil reset Accessibility` entre
scénarios, ou compte utilisateur neuf — sinon les résultats se contaminent. M8 a déjà
procédé ainsi pour prouver la demande de micro ; le montage se reprend tel quel.

**Ce que M7-0 décide :** la variante de lanceur, et ad-hoc contre certificat local. Si B
ne perd pas les autorisations, l'invariant « bundle stable » est inutilement contraignant
et on le relâche. Si C est nécessaire, le certificat local est adopté et l'invariant
disparaît avec lui.

## Approche

### 1. `macos_desktop.py` — la couture que M0 avait posée et qui n'a jamais servi

`platform_dispatch.desktop_integration()` lève `UnsupportedPlatformError` sur tout ce qui
n'est pas Linux. M7 lui donne sa seconde branche : sur Darwin, elle rend `macos_desktop`.

Le module reprend l'API de `linux_desktop` — `install_desktop_entry()`,
`install_autostart_entry()`, `remove_legacy_entries()` — pour que `cli.py` change le moins
possible. Ce que ces noms recouvrent diffère (un bundle au lieu d'un fichier `.desktop`,
un LaunchAgent au lieu d'une entrée `~/.config/autostart`), la forme non.

**Le comportement Linux ne bouge pas d'un octet.** La branche `is_linux()` est inchangée ;
la nouvelle est ajoutée avant le `raise`.

### 2. Le bundle : exécutable principal **Mach-O**, jamais un script

Apple DTS, [thread 678819](https://developer.apple.com/forums/thread/678819), mot pour
mot :

> *TCC expects its bundled clients — apps, app extensions, and so on — to use a native
> main executable. That is, it expects the `CFBundleExecutable` property to be the name
> of a Mach-O executable. If your product uses a script as its main executable, you're
> likely to encounter TCC problems.*

Donc `Contents/MacOS/aparte` est un petit exécutable écrit en C (≈ 60 lignes), **compilé
sur la machine de l'utilisateur** par la formula avec le `clang` des outils en ligne de
commande — que Homebrew exige déjà.

```
~/Applications/Aparté.app/
  Contents/
    Info.plist            ← identité stable, aucune version d'Aparté
    MacOS/aparte          ← exécutable Mach-O compilé localement
    Resources/aparte.icns ← l'icône, commitée
```

Ce que fait le lanceur : résoudre le chemin stable de l'interpréteur, vérifier qu'il
existe, **afficher une fenêtre d'erreur nommant la commande à retaper** s'il a disparu,
puis lancer Python. Une `.app` lancée depuis le Finder qui meurt ne laisse aucune trace
visible — pas de terminal, pas de message. C'est le pire mode de panne du lot.

`Info.plist`, les clés qui comptent :

| Clé | Valeur | Pourquoi |
|---|---|---|
| `CFBundleIdentifier` | `ca.collectifweb.aparte` | l'identité que voient TCC et les Réglages Système. **Définitive** : la changer après diffusion créerait une seconde application, et l'utilisateur devrait tout réautoriser sans comprendre. |
| `CFBundleName` / `CFBundleDisplayName` | `Aparté` | le nom dans la fenêtre d'autorisation |
| `LSUIElement` | `true` | pas d'icône du Dock, pas de fenêtre — Aparté vit dans la barre de menus (M6) |
| `NSMicrophoneUsageDescription` | la phrase montrée dans la fenêtre | obligatoire, sinon macOS tue le processus au lieu de demander |
| `CFBundleShortVersionString` | version **du lanceur**, fixe | pas celle d'Aparté (voir § 3) |

**Le chemin de l'interpréteur.** `sys.executable` donne à l'installation un chemin
contenant le numéro de version (`…/Cellar/aparte/1.1.1/libexec/bin/python3`) — il
disparaît au premier `brew upgrade`. Homebrew maintient à côté un chemin stable
(`…/opt/aparte/…`) : le lanceur écrit **celui-là**. La réécriture est une transformation
de chaîne, donc prouvée sous Linux, sans Mac.

### 3. Pourquoi le bundle ne doit pas changer d'une version à l'autre

Apple, même source :

> *If your code is unsigned, or signed ad hoc, the system can't tell that version N+1 of
> your code is the same as version N, and thus you'll encounter excessive prompts.*

Une signature ad-hoc n'a pas d'identité d'équipe : l'exigence enregistrée par TCC est
attachée à l'empreinte du code (`cdhash`). Si le bundle change, macOS **oublie les
autorisations** — et la case reste cochée dans les Réglages Système, ce qui rend la panne
silencieuse.

L'avertissement porte sur un code **qui change**. Le nôtre ne change pas dans le parcours
normal : le bundle ne contient ni la version d'Aparté, ni le code Python, ni un chemin
qui bouge. `brew upgrade` remplace le contenu du préfixe et **ne touche pas au bundle**.
Il n'y a pas de « version N+1 du lanceur ».

Là où le risque mord vraiment, c'est **la réinstallation**. Trois mesures :

1. **`install-app` est idempotent** : si le bundle en place est déjà celui qu'on
   produirait, il ne réécrit rien, ne recompile rien, ne re-signe rien.
2. **La compilation verrouille ses entrées** : pas de `__DATE__` ni `__TIME__`, pas
   d'infos de débogage portant des chemins temporaires, options fixes, cible de
   déploiement fixe. L'UUID du lieur est dérivé du contenu par défaut
   ([TN3178](https://developer.apple.com/documentation/technotes/tn3178-checking-for-and-resolving-build-uuid-problems)),
   donc le déterminisme est plausible — sans être garanti à travers une mise à jour des
   outils en ligne de commande.
3. **`--force` prévient avant de casser, pas après** : il compare le `cdhash` du bundle
   en place à celui qu'il produirait et, s'ils diffèrent, demande une confirmation
   explicite disant que les autorisations devront être redonnées. **Le `cdhash` de
   référence se range hors du bundle** (`~/.config/aparte/`) — le ranger dedans
   modifierait précisément ce qu'on prétend stabiliser.

`doctor` garde son rôle, mais pour ce qu'il sait faire : constater après coup qu'un
bundle a changé et le dire en clair.

**Le certificat local auto-signé est conçu, pas adopté.** Il ancre l'exigence sur le
certificat au lieu du `cdhash`, donc survit aux rebuilds ; il coûte une identité dans le
trousseau et une surface de support. Le scénario C de M7-0 décide.

### 4. `codesign` est un prérequis dur

Pas best-effort. Une installation qui rend un bundle mal signé en annonçant le succès est
pire que pas d'installation, et sur Apple Silicon le code natif exige une signature, même
ad-hoc. Si `codesign` manque ou refuse : message clair, **code de sortie non nul**, pas de
bundle « presque bon ».

### 5. `update.py` apprend l'installation Homebrew

Aujourd'hui `find_repo()` ne trouve pas de `.git` sur une installation Homebrew, l'état
retombe sur `manual`, et le menu annonce « Aparté ne tourne pas depuis un dépôt git ».
Pour quelqu'un qui a installé exactement comme on le lui a dit, c'est une réponse absurde.

Nouvel état `brew`, avec la commande à lancer. La détection lit le préfixe d'installation
— transformation de chaîne, testable ici.

| Installation | État | Ce que dit le menu |
|---|---|---|
| clone git (Linux, développeur) | inchangé | inchangé |
| clone git sur Mac (testeur) | inchangé | inchangé |
| Homebrew | `brew` | `brew upgrade collectifweb/aparte/aparte` |

**Rien du chemin Linux ne change.** L'état `brew` est ajouté à côté de `manual`, il ne le
remplace pas. `/api/update/apply` reste 404 sur Darwin (invariant M3).

### 6. Le modèle au premier lancement

Le modèle (~500 Mo) se télécharge à la première transcription — c'est déjà le
comportement. Le travail de M7 est de le **rendre visible**.

- Aparté appelle `snapshot_download` **lui-même**, sur un fil, au premier lancement quand
  le modèle manque : c'est l'application qui déclenche, **jamais une route HTTP**
  (invariant Darwin). L'interface ne fait qu'observer, par une route en lecture seule,
  comme `/api/recording-state` et `/api/tray-state`.
- La progression se lit en **sommant les fichiers `.incomplete` du cache** face à la
  taille attendue : ce que le disque montre réellement, sans dépendre d'un rappel de
  progression que la bibliothèque ne garantit pas.
- Si `huggingface_hub` n'est pas importable ou la taille inconnue : état **indéterminé et
  honnête**, sans pourcentage inventé.
- Échec réseau, proxy, somme de contrôle : un état d'erreur nommé.
- La phrase dit clairement qu'**Aparté ne dictera qu'à la fin**.
- `doctor` garde `model_ready` comme source de vérité persistante.

### 7. Le démarrage à l'ouverture de session

Sur Mac, le raccourci exige que l'application tourne. Un LaunchAgent, avec **un détail
qui décide de tout** : il lance `/usr/bin/open`, **jamais le lanceur directement**.
Exécuter le lanceur ferait de `launchd` le processus responsable, et on reperdrait
exactement l'attribution qu'on vient de gagner.

- `RunAtLoad` seul, **pas de `KeepAlive`** : le job sort tout de suite, il serait relancé
  en boucle ;
- **chemins absolus**, jamais de `~` — `launchd` ne fait pas d'expansion shell ;
- journaux vers `~/Library/Logs/Aparté/`, sinon un échec au login est indiagnosticable ;
- `open -b ca.collectifweb.aparte` contre chemin absolu : **tranché nativement** ;
- plist historique assumé **comme choix de compatibilité** avec Big Sur (validé en M8),
  pas comme le mécanisme Apple courant — `SMAppService` demande macOS 13.

Lot le moins prouvable ici, découpé en dernier, **reportable sans rien casser**.

### 8. La formula et le dépôt

Un **dépôt personnel** (`collectifweb/homebrew-aparte`) : le dépôt officiel demande une
notoriété (75 étoiles, 30 forks…) qu'Aparté n'a pas.

- **Python épinglé** : `depends_on "python@3.12"`, confirmé ou corrigé en M7-0 selon les
  roues réellement disponibles sur la machine de test.
- **Dépendances natives** déclarées : `portaudio` (pour `sounddevice`), `libsndfile`
  (pour `soundfile`) — plutôt que de parier sur les roues.
- **Extras** : `whisper`, `recording`, `macos`. **Jamais `cuda`** — il n'existe pas sur
  Mac et tirerait des paquets NVIDIA inutiles.
- **`brew test`** : `aparte --version`, l'import de `rumps`, `AppKit`, `sounddevice`, et
  la génération du bundle dans un répertoire temporaire (ce qui teste la compilation du
  lanceur sans toucher à `~/Applications`).
- **Caveats** : `aparte install-app --open`, `aparte install-hotkey`, le téléchargement du
  modèle au premier lancement, et `aparte uninstall-app` **avant** `brew uninstall`.

**Le `post_install` ne peut pas créer le bundle** : les blocs d'installation d'une formula
sont sandboxés et `HOME` y est remplacé par un répertoire temporaire. C'est pourquoi le
parcours garde sa commande intermédiaire.

**Ce que Homebrew ne possède pas** : la `.app` vit dans `~/Applications`, hors du préfixe,
donc `brew uninstall` la laissera en place. D'où `aparte uninstall-app` et sa mention dans
les caveats. Le compromis est nommé, pas caché.

## Étapes d'implémentation

Chaque lot a ses tests et son commit.

| Lot | Contenu | Prouvable sous Linux ? |
|---|---|---|
| **M7-0** | **Preuve TCC native.** Bundle sonde, lanceur Mach-O, deux variantes, deux autorisations, trois scénarios de signature, `xattr`, `cdhash`. **Porte de décision.** | non, c'est tout son objet |
| M7a | Le lanceur : source C générée, options de compilation, `Info.plist`, arborescence, réécriture `Cellar` → `opt`, déterminisme de l'entrée | oui |
| M7b | `aparte.icns` généré depuis `logo.svg` et **commité** (aucune étape de compilation pour un contributeur, comme les PNG de M6c), régénération documentée dans `DESIGN.md` | oui |
| M7c | `install-app` (idempotent, `--open`, `--force` qui prévient), `uninstall-app`, `desktop_integration()` sur Darwin, `codesign` **obligatoire**, checks `doctor` | oui |
| M7d | La formula, le dépôt personnel, `brew test`, caveats, `README` et doc du parcours Mac | partiellement |
| M7e | État `brew` dans `update.py`, libellés du menu (fr + en) et du panneau web | oui |
| M7f | Modèle visible au premier lancement, mécanisme du § 6, passage par `/impeccable` | oui |
| M7g | LaunchAgent. **Reportable** | oui, sauf le cycle `launchd` |
| M7h | Doc : `CLAUDE.md`, `CHANGELOG.md`, `tasks/todo.md`, `README.md` | — |

## Points de vigilance

- **Les faux Linux prouvent notre orchestration, jamais le comportement de la
  plateforme.** Tout ce qui touche à `codesign`, à LaunchServices et à l'attribution TCC
  ne se vérifie que sur le Mac.
- **M7-0 est une porte, pas une formalité.** Si elle ne s'ouvre pas, les lots suivants ne
  commencent pas.
- **`CFBundleIdentifier` est définitif.**
- **Le `cdhash` de référence vit hors du bundle.**
- **Ne pas promettre que la signature ad-hoc vaut une signature Apple.**
- **`rumps.notification()` exige un vrai bundle.** Il en existe un avec M7, mais on ne
  bascule pas dessus dans ce lot : `notify()` par `osascript` fonctionne, et changer ça
  ici mélangerait deux sujets.
- **Le déterminisme de `clang` n'est pas garanti** à travers une mise à jour des outils
  en ligne de commande. C'est ce qui rend `--force` bavard obligatoire.

## Checklist de validation native

Montage : `.claude/mac-validation/README.md`, étapes numérotées servies une par une,
somme de contrôle SHA-256 obligatoire sur l'archive servie, question explicite pour tout
ce qui ne laisse pas de trace dans un journal.

1. `aparte install-app --open` sur une installation neuve : le bundle apparaît dans
   `~/Applications`, le Finder montre l'icône, Spotlight le trouve.
2. Ouverture : **aucun avertissement Gatekeeper**, aucune fenêtre « application
   endommagée », aucun clic droit nécessaire. `xattr -lr` le confirme.
3. Les deux fenêtres disent **« Aparté »**, pas « Terminal », pas « Python ». Vérifier
   dans Réglages Système que c'est bien Aparté qui est listé, avec son icône.
4. L'icône de barre de menus apparaît, sans icône du Dock (`LSUIElement`).
5. Le raccourci fonctionne depuis une application lancée par le Finder.
6. **Le point qui décide du lot** : accorder les autorisations, faire un vrai
   `brew upgrade`, rouvrir. Relever SHA-256 du bundle, `cdhash`, `codesign -d -r-` et
   l'état TCC **avant et après**.
7. Lanceur cassé : renommer le préfixe Homebrew, ouvrir la `.app`, vérifier que la
   fenêtre d'erreur apparaît et nomme la commande.
8. `install-app --force` sur un bundle dont le `cdhash` changerait : la confirmation
   apparaît **avant** le remplacement.
9. `aparte uninstall-app` puis `brew uninstall` : rien ne reste.
10. Menu « Mettre à jour » : dit `brew upgrade`, ne tente ni `git` ni `pip`.
11. Premier lancement modèle absent : la progression est visible et la phrase dit
    qu'Aparté ne dictera qu'à la fin.
12. Démarrage à l'ouverture de session (si M7g est livré) : après redémarrage, l'icône
    est là **et** les autorisations tiennent — c'est là que `open` se prouve.

## Décisions explicitement écartées

- **Cask Homebrew, signé ou non** — les casks non signés disparaissent le 1er septembre
  2026 et `--no-quarantine` n'existe plus. Un cask signé demande un compte Apple à
  99 USD/an et un Mac pour signer chaque version.
- **Cask dans un dépôt personnel qui retire la quarantaine dans son `postflight`** —
  fonctionne encore, mais va contre la direction explicite de Homebrew, donc se casse au
  prochain durcissement. Et il faudrait fabriquer une `.app` reproductible à chaque
  version sans Mac.
- **Script shell comme `CFBundleExecutable`** — Apple dit explicitement que TCC attend un
  Mach-O et qu'un script « expose à des problèmes TCC ». C'est le bénéfice entier du lot
  qui en dépendait.
- **`post_install` qui crée le bundle** — les blocs d'installation d'une formula sont
  sandboxés et `HOME` y est temporaire. Le mécanisme n'écrirait pas où on croit.
- **`.app` autonome par py2app ou PyInstaller** — plusieurs centaines de mégaoctets,
  demande un Mac pour la construire, et introduit une chaîne de compilation que le projet
  s'interdit ailleurs.
- **Embarquer le modèle Whisper** — tranché : le paquet reste léger, le modèle se
  télécharge au premier lancement avec une progression visible.
- **Une formula sans `.app`** — la plus simple à maintenir, mais elle laisse les
  autorisations attribuées à Terminal, le défaut que ce lot existe pour corriger.
- **Mettre la version d'Aparté dans le bundle** — elle changerait l'empreinte du code à
  chaque version, et macOS oublierait les autorisations.
- **`codesign` best-effort** — un bundle mal signé présenté comme installé est pire que
  pas d'installation.
- **Faire lancer le LaunchAgent directement sur le lanceur** — `launchd` deviendrait le
  processus responsable et l'attribution TCC repartirait à zéro.
- **Le dépôt Homebrew officiel** — Aparté n'a pas la notoriété exigée ; un dépôt
  personnel ne coûte qu'un préfixe dans la commande d'installation.
