# M7 — L'installation macOS

_Plan écrit le 25/07/2026, après un second avis de Codex
(`docs/archives/avis-codex-m7-empaquetage-2026-07-25.md`) et un fait nouveau qui a
rouvert la décision de distribution._

## Contexte

Ce qu'il a fallu faire pour qu'Aparté tourne sur un Mac pendant M8 : installer Python
3.11 depuis python.org, télécharger une archive, créer un environnement virtuel, lancer
`pip install --prefer-binary` avec les bons extras, attendre 500 Mo de modèle — tout en
ligne de commande. C'est le contraire de la promesse.

**La cible : installer → ouvrir → accorder deux autorisations. Rien d'autre.**

Et un défaut de fond, trouvé pendant M8 : les autorisations macOS sont aujourd'hui
accordées à **Terminal**, pas à Aparté. La fenêtre dit « Terminal souhaite accéder au
micro ». L'utilisateur autorise son terminal à écouter, ce qui n'est ni ce qu'il veut
ni ce qu'on lui demande vraiment.

## Le fait nouveau

La décision du 25/07 était : **cask Homebrew, sans compte développeur Apple**, en
s'appuyant sur le fait que Homebrew retire lui-même l'attribut de quarantaine, donc que
Gatekeeper ne bloque pas.

**Ce n'est plus vrai.**

- Homebrew a **supprimé `--no-quarantine`** (version 5.1, mars 2026). Un cask pose
  désormais la quarantaine, sans option pour la refuser.
- Homebrew **retire tous les casks qui échouent au contrôle Gatekeeper le
  1er septembre 2026** — dans cinq semaines. Leur audit exige signature **et**
  notarisation.
- Depuis macOS Sequoia, le clic droit → Ouvrir ne suffit plus à passer outre : il faut
  aller dans Réglages Système → Confidentialité et sécurité → Ouvrir quand même.

Un cask non signé n'entre donc plus dans le dépôt officiel, et dans un dépôt personnel
il installe une application mise en quarantaine, que macOS refuse d'ouvrir en annonçant
qu'elle est endommagée. La promesse de simplicité tombe exactement là où elle devait
tenir.

**Les formulas ne sont pas concernées.** La restriction ne vise que les casks.

Sources : [Homebrew/brew#20755](https://github.com/Homebrew/brew/issues/20755),
[Homebrew discussion #6537](https://github.com/orgs/Homebrew/discussions/6537),
[Homebrew 5.0.0](https://workbrew.com/blog/homebrew-5-0-0).

Le second avis de Codex recommandait `.app` + cask. Il a été rendu **sans ce fait** —
il traitait le retrait de la quarantaine comme « une bonne hypothèse pratique à
tester ». Le reste de son avis tient et est repris ci-dessous : le bundle vaut son coût
pour les autorisations (§ 1), et `update.py` ne doit plus proposer sa mise à jour
in-process sur une installation Homebrew (§ 5).

## La décision : une formula, et une `.app` construite sur la machine de l'utilisateur

Trois faits la portent.

1. **Une formula n'est pas un cask.** Rien de ce qui précède ne s'y applique : pas
   d'audit Gatekeeper, pas de notarisation, pas de date butoir.
2. **La quarantaine est posée par ce qui télécharge.** Un dossier assemblé sur place par
   un processus local ne la reçoit jamais. Si la `.app` est **construite** chez
   l'utilisateur au lieu d'être téléchargée, Gatekeeper n'a rien à examiner — il n'y a
   pas de « première ouverture d'une application venue d'internet ».
3. **Les autorisations suivent l'application qui lance.** macOS attribue une demande TCC
   au processus « responsable », c'est-à-dire au bundle que LaunchServices a démarré.
   C'est précisément pour ça qu'aujourd'hui c'est Terminal : c'est Terminal qui lance
   Python. Une `.app` qui lance Python devient responsable à sa place, et les deux
   fenêtres disent « Aparté ».

Le parcours devient :

```
brew install collectifweb/aparte/aparte     ← pose le venv, comme n'importe quelle formula
aparte install-app                          ← fabrique ~/Applications/Aparté.app
(ouvrir Aparté)                             ← « Aparté souhaite accéder au micro »
                                              « Aparté souhaite contrôler cet ordinateur »
```

Aucun compte Apple. Aucun Mac pour fabriquer les versions — la construction se fait chez
l'utilisateur, comme toute formula. Aucune intégration continue macOS. Et rien de tout
ça ne meurt le 1er septembre.

**Ce que ça ne donne pas, et qu'il faut dire :** une signature ad-hoc n'est pas une
signature Apple. Aparté reste une application non notarisée, distribuée hors de l'App
Store, par un dépôt Homebrew personnel. C'est honnête, ce n'est pas équivalent.

## Approche

### 1. `macos_desktop.py` — la couture que M0 avait posée et qui n'a jamais servi

`platform_dispatch.desktop_integration()` lève `UnsupportedPlatformError` sur tout ce
qui n'est pas Linux. M7 lui donne sa seconde branche : sur Darwin, elle rend
`macos_desktop`.

Le module reprend l'API de `linux_desktop` — `install_desktop_entry()`,
`install_autostart_entry()`, `remove_legacy_entries()` — pour que `cli.py` change le
moins possible. Ce que ces noms recouvrent diffère (un bundle au lieu d'un fichier
`.desktop`, un LaunchAgent au lieu d'une entrée `~/.config/autostart`), la forme non.

**Le comportement Linux ne bouge pas d'un octet.** La branche `is_linux()` de
`desktop_integration()` est inchangée ; la nouvelle branche est ajoutée avant le `raise`.

### 2. Le bundle : mince, et surtout **stable octet pour octet**

C'est l'invariant central du lot, et il n'est pas évident.

Une signature ad-hoc n'a pas d'identité d'équipe : macOS identifie l'application par
l'empreinte de son code (`cdhash`). **Si le bundle change, l'empreinte change, et macOS
oublie les autorisations accordées** — micro et accessibilité redemandés à chaque mise à
jour d'Aparté. Ce serait pire que l'état actuel : aujourd'hui l'utilisateur autorise
Terminal une fois, demain il réautoriserait Aparté à chaque version.

**Donc le bundle ne contient rien qui change d'une version à l'autre.** La version
d'Aparté n'y figure pas. Le bundle n'est pas Aparté : c'est son lanceur, et le lanceur
a sa propre version, fixe.

```
~/Applications/Aparté.app/
  Contents/
    Info.plist            ← identité stable, aucune version d'Aparté
    MacOS/aparte          ← le lanceur, quelques lignes de shell
    Resources/aparte.icns ← l'icône, commitée
```

`Info.plist`, les clés qui comptent :

| Clé | Valeur | Pourquoi |
|---|---|---|
| `CFBundleIdentifier` | `ca.collectifweb.aparte` | l'identité que voient TCC et les Réglages Système. **Ne jamais la changer** : ce serait une nouvelle application, sans ses autorisations. |
| `CFBundleName` / `CFBundleDisplayName` | `Aparté` | le nom dans la fenêtre d'autorisation |
| `LSUIElement` | `true` | pas d'icône du Dock, pas de fenêtre — Aparté vit dans la barre de menus (M6) |
| `NSMicrophoneUsageDescription` | la phrase montrée dans la fenêtre | obligatoire, sinon macOS tue le processus au lieu de demander |
| `CFBundleShortVersionString` | version **du lanceur**, fixe | pas celle d'Aparté : la faire varier casserait l'empreinte |

**Le chemin de l'interpréteur.** Le lanceur doit désigner le Python du venv Homebrew.
`sys.executable` donne au moment de l'installation un chemin qui contient le numéro de
version (`…/Cellar/aparte/1.1.1/libexec/bin/python3`) — il disparaît au premier
`brew upgrade`. Homebrew maintient à côté un chemin stable (`…/opt/aparte/…`) : le
lanceur écrit **celui-là**. La réécriture est une transformation de chaîne, donc prouvée
sous Linux par des tests, sans Mac.

**Le test qui garde l'invariant** : construire le bundle deux fois avec deux
`__version__` différents et vérifier que les fichiers produits sont identiques.

### 3. La signature ad-hoc

`codesign --force --sign - --identifier ca.collectifweb.aparte <bundle>`. Gratuite,
fournie par les outils en ligne de commande que Homebrew exige déjà.

Elle est **best-effort** : si `codesign` manque ou refuse, on le dit clairement et on
garde le bundle — sur Intel il fonctionne sans. Ce qu'elle apporte, c'est une identité
que macOS accepte partout, y compris sur Apple Silicon ; ce qu'elle n'apporte pas, c'est
la moindre garantie Apple.

### 4. Un lanceur qui échoue doit parler

Une `.app` lancée depuis le Finder qui meurt ne laisse **aucune trace visible** : pas de
terminal, pas de message, rien. C'est le pire mode de panne possible pour ce lot.

Le lanceur vérifie donc que l'interpréteur existe avant de l'exécuter, et s'il a disparu
(désinstallation, `brew uninstall`, dossier déplacé) affiche une fenêtre par `osascript`
qui nomme la commande à retaper. Trois lignes de shell, et la différence entre « ça ne
marche pas » et « voilà quoi faire ».

### 5. `update.py` apprend l'installation Homebrew

Aujourd'hui `find_repo()` ne trouve pas de `.git` sur une installation Homebrew, l'état
retombe sur `manual`, et l'article du menu annonce « Aparté ne tourne pas depuis un
dépôt git ». Pour quelqu'un qui a installé exactement comme on le lui a dit, c'est une
réponse absurde.

Nouvel état `brew`, avec la commande à lancer. La détection lit le préfixe
d'installation — encore une transformation de chaîne, testable ici. Les trois mondes
restent distincts :

| Installation | État | Ce que dit le menu |
|---|---|---|
| clone git (Linux, développeur) | inchangé | inchangé |
| clone git sur Mac (testeur) | inchangé | inchangé |
| Homebrew | `brew` | `brew upgrade collectifweb/aparte/aparte` |

**Rien du chemin Linux ne change.** L'état `brew` est ajouté à côté de `manual`, il ne
le remplace pas.

### 6. Le modèle au premier lancement

Le modèle (~500 Mo) se télécharge à la première transcription — c'est déjà le
comportement. Le travail de M7 est de le **rendre visible**, pas de le changer.

Une installation neuve ouvre l'interface, et l'interface dit, en français et en anglais :
le modèle se télécharge, voici où ça en est, **Aparté ne dictera qu'à la fin**. Sans ça,
la première dictée d'un Mac neuf ressemble à une application qui ne répond pas.

**Le téléchargement n'est déclenché par aucune route HTTP** — invariant Darwin. C'est
l'application qui le lance, sur un fil ; l'interface ne fait que **l'observer**, par une
route en lecture seule, comme `/api/recording-state` et `/api/tray-state`.

### 7. Le démarrage à l'ouverture de session

Sur Mac, le raccourci exige que l'application tourne : sans démarrage automatique,
l'utilisateur doit ouvrir Aparté à chaque session avant de pouvoir dicter.

Un LaunchAgent, avec **un détail qui décide de tout** : il lance
`/usr/bin/open -a ~/Applications/Aparté.app`, **jamais le lanceur directement**. Lancer
le lanceur ferait de `launchd` le processus responsable, et on reperdrait exactement
l'attribution qu'on vient de gagner. Passer par `open`, c'est demander à LaunchServices
de démarrer l'application, donc c'est l'application qui reste responsable.

C'est le lot le moins prouvable ici et le plus dépendant du Mac : il est découpé en
dernier, et il peut être reporté sans rien casser du reste.

### 8. La formula et le dépôt

Un **dépôt personnel** (`collectifweb/homebrew-aparte`), pas le dépôt officiel : celui-ci
demande une notoriété (75 étoiles, 30 forks…) qu'Aparté n'a pas, et l'y présenter
maintenant serait refusé.

La formula déclare Python, installe Aparté dans un venv avec les extras `whisper`,
`recording` et `macos`, expose la commande `aparte`, et sa note d'installation dit la
suite en deux lignes : `aparte install-app`, puis ouvrir Aparté.

La commande complète pour l'utilisateur reste **une seule ligne** :
`brew install collectifweb/aparte/aparte`.

## Étapes d'implémentation

Chaque lot a ses tests et son commit.

1. **M7a — le bundle, sans rien de natif.** `macos_desktop.py` : `build_info_plist()`,
   `build_launcher()`, la réécriture `Cellar` → `opt`, `install_desktop_entry()` qui
   écrit l'arborescence. Tests : contenu du plist, lanceur qui nomme le bon interpréteur,
   **stabilité octet pour octet entre deux versions**, dossier créé s'il manque.
2. **M7b — l'icône.** `aparte.icns` généré depuis `logo.svg` et **commité** (aucune
   étape de compilation pour un contributeur, comme les PNG de M6c), commande de
   régénération documentée dans `DESIGN.md`. Test : en-tête `icns` valide, tailles
   attendues présentes.
3. **M7c — la commande et la couture.** `aparte install-app` (`--force`, `--print`),
   `desktop_integration()` qui rend `macos_desktop` sur Darwin, signature ad-hoc
   best-effort, check `doctor` `app_bundle` (`detail` dynamique, **sans clé i18n**,
   jamais essentiel — règle `CLAUDE.md` § Interface).
4. **M7d — la formula.** `packaging/homebrew/aparte.rb`, le dépôt personnel, la note
   d'installation, le `README` et `docs/` réécrits pour le parcours Mac réel.
5. **M7e — la mise à jour Homebrew.** État `brew` dans `update.py`, détection par
   préfixe, libellés du menu de barre de menus (fr + en), phrase du panneau web.
6. **M7f — le modèle visible au premier lancement.** Téléchargement lancé par
   l'application sur un fil, route d'observation en lecture seule, écran d'accueil
   fr + en via `i18n.js`, passage par `/impeccable`.
7. **M7g — le démarrage à l'ouverture de session.** LaunchAgent via `open -a`,
   `aparte install-autostart` sur Mac, `remove_legacy_entries()`. Reportable.
8. **M7h — doc.** `CLAUDE.md` (les invariants ci-dessous), `CHANGELOG.md`,
   `tasks/todo.md`, `README.md`.

## Points de vigilance

- **Les faux Linux prouvent notre orchestration, jamais le comportement de la
  plateforme.** M8 l'a payé cash : un `Segmentation fault` à la première exécution
  native, invisible en test mocké. Ici, tout ce qui touche à `codesign`, à
  LaunchServices et à l'attribution TCC ne se vérifie que sur le Mac.
- **L'attribution TCC à travers une mise à jour est le vrai risque du lot.** La
  stabilité octet pour octet du bundle est une déduction, pas une observation : elle se
  vérifie en accordant les autorisations, en faisant un `brew upgrade`, et en regardant
  si elles sont toujours là.
- **`CFBundleIdentifier` est définitif.** Le changer après une première diffusion créerait
  une seconde application aux yeux de macOS, et l'utilisateur devrait tout réautoriser
  sans comprendre pourquoi.
- **La `.app` doit rester hors du venv.** Elle vit dans `~/Applications`, pas dans le
  préfixe Homebrew : un `brew uninstall` ne doit pas laisser une application fantôme,
  mais un `brew upgrade` ne doit pas l'effacer non plus.
- **Ne pas promettre que la signature ad-hoc vaut une signature Apple.** Elle ne la vaut
  pas, et c'est ce qu'on écrit.
- **`rumps.notification()` exige toujours un vrai bundle.** Avec M7 il en existe un —
  mais on ne bascule pas dessus dans ce lot : `notify()` par `osascript` fonctionne, et
  changer ça ici mélangerait deux sujets.

## Checklist de validation native

Montage : `.claude/mac-validation/README.md`, étapes numérotées servies une par une,
somme de contrôle SHA-256 obligatoire sur l'archive servie, et question explicite pour
tout ce qui ne laisse pas de trace dans un journal.

1. `aparte install-app` sur une installation neuve : le bundle apparaît dans
   `~/Applications`, le Finder montre l'icône, Spotlight le trouve.
2. Ouverture depuis le Finder : **aucun avertissement Gatekeeper**, aucune fenêtre
   « application endommagée », aucun clic droit nécessaire.
3. Les deux fenêtres d'autorisation disent **« Aparté »**, pas « Terminal », pas
   « Python ». Vérifier ensuite dans Réglages Système → Confidentialité et sécurité que
   c'est bien Aparté qui est listé, avec son icône.
4. L'icône de barre de menus apparaît, sans icône du Dock (`LSUIElement`).
5. Le raccourci fonctionne depuis une application lancée par le Finder.
6. **Le point qui décide du lot** : accorder les autorisations, faire un
   `brew upgrade`, rouvrir — les autorisations sont-elles conservées ?
7. Lanceur cassé : renommer le préfixe Homebrew, ouvrir la `.app`, vérifier que la
   fenêtre d'erreur apparaît et nomme la commande.
8. Menu « Mettre à jour » : dit `brew upgrade`, ne tente ni `git` ni `pip`.
9. Premier lancement modèle absent : la progression est visible et la phrase dit
   qu'Aparté ne dictera qu'à la fin.
10. Démarrage à l'ouverture de session (si M7g est livré) : après redémarrage, l'icône
    est là **et** les autorisations tiennent — c'est le point où `open -a` se prouve.

## Décisions explicitement écartées

- **Cask Homebrew, signé ou non** — les casks non signés disparaissent le 1er septembre
  2026 et `--no-quarantine` n'existe plus. Un cask signé demande un compte Apple à
  99 USD/an et un Mac pour signer chaque version.
- **Cask dans un dépôt personnel qui retire la quarantaine dans son `postflight`** —
  fonctionne encore aujourd'hui, mais va contre la direction explicite de Homebrew, donc
  se casse au prochain durcissement. Et il faudrait quand même fabriquer une `.app`
  reproductible à chaque version sans Mac.
- **`.app` autonome par py2app ou PyInstaller** — plusieurs centaines de mégaoctets,
  demande un Mac pour la construire, et introduit une chaîne de compilation que le projet
  s'interdit ailleurs. La construction locale par une formula donne le même bundle sans
  rien de tout ça.
- **Embarquer le modèle Whisper** — tranché : le paquet reste léger, le modèle se
  télécharge au premier lancement avec une progression visible.
- **Une formula sans `.app`** — la plus simple à maintenir, mais elle laisse les
  autorisations attribuées à Terminal, c'est-à-dire le défaut de fond que ce lot existe
  pour corriger.
- **Mettre la version d'Aparté dans le bundle** — elle changerait l'empreinte du code à
  chaque version, et macOS oublierait les autorisations. Le lanceur porte sa propre
  version, fixe.
- **Faire lancer le LaunchAgent directement sur le lanceur** — `launchd` deviendrait le
  processus responsable et l'attribution TCC repartirait à zéro. Il passe par
  `open -a`.
- **Le dépôt Homebrew officiel** — Aparté n'a pas la notoriété exigée ; un dépôt
  personnel ne coûte qu'un préfixe dans la commande d'installation.
