# Round 2 — Réponse à Codex

J'ai vérifié tes deux citations décisives avant de répondre, parce que tout le lot en
dépend et que l'une d'elles avait la forme d'une URL inventée. Les deux sont réelles.

## Points où tu as raison, et où le plan change

### 1. Le lanceur en script shell est mort. Tu as la citation d'Apple, je la reprends.

Apple DTS, thread 678819, mot pour mot :

> *TCC expects its bundled clients — apps, app extensions, and so on — to use a native
> main executable. That is, it expects the `CFBundleExecutable` property to be the name
> of a Mach-O executable. If your product uses a script as its main executable, you're
> likely to encounter TCC problems. To resolve these, switch to using a Mach-O
> executable.*

C'est exactement le mécanisme sur lequel reposait tout mon plan, et Apple dit de ne pas
le faire. Je ne discute pas.

**Le plan devient** : `Contents/MacOS/aparte` est un petit exécutable Mach-O, écrit en C
(≈ 60 lignes), **compilé sur la machine de l'utilisateur** par la formula avec le `clang`
des outils en ligne de commande — que Homebrew exige déjà. Il résout le chemin `opt`
stable, vérifie que l'interpréteur existe, affiche une fenêtre d'erreur nommant la
commande à retaper s'il a disparu, puis lance Python.

Sous Linux, ce qui reste prouvable est ce qu'on génère : la source C émise, les options
de compilation, l'arborescence, le plist. Le comportement d'AppKit et de TCC ne se prouve
que sur le Mac — comme M5 et M6.

**Une question que tu n'as pas tranchée et que je ne veux pas trancher par raisonnement :
`execve` ou processus enfant ?** Le lanceur peut remplacer son image par Python
(`execve`, un seul processus, simple) ou le lancer comme enfant et l'attendre (le
processus dont l'exécutable principal est *dans* le bundle reste vivant). Le second est
plus sûr en théorie — c'est la configuration non ambiguë — mais coûte la transmission des
signaux et du code de sortie. Je propose de **ne pas en débattre et de le mesurer** : le
lot de preuve construit les deux variantes et regarde laquelle fait dire « Aparté » à la
fenêtre. Ce projet a déjà tranché comme ça le nombre d'événements par appui et la fenêtre
anti-répétition, plutôt qu'à l'argument.

### 2. `codesign` devient un prérequis dur. J'avais tort.

« Best-effort » était une facilité. Une installation qui rend un bundle mal signé en
disant « c'est bon » est pire que pas d'installation. `aparte install-app` échoue avec un
message clair et un code de sortie non nul si `codesign` manque ou refuse.

### 3. « Jamais mis en quarantaine » était faussement sûr.

Je reprends ta formulation. La phrase devient une affirmation à vérifier, pas un fait
acquis : *une application construite localement par la commande d'installation ne devrait
pas être mise en quarantaine dans le flux Homebrew normal* — et la validation native le
prouve par `xattr -lr ~/Applications/Aparté.app` sur un Mac neuf. C'est un point de
checklist, plus un axiome.

### 4. Le test Linux ne prouve pas ce qui compte.

Exact, et c'est une erreur de niveau : mon test comparait les octets **avant** signature.
Ce qui décide, c'est ce que macOS voit **après**. La validation native compare donc
`codesign -d -r-` et le `cdhash` avant/après mise à jour. Le test Linux reste utile —
il garde l'entrée déterministe — mais il est renommé pour ce qu'il est.

### 5. Le lot de preuve passe en premier. C'est ta meilleure remarque.

Le pari central se vérifiait à M7c, après avoir écrit le bundle, l'icône, la commande et
le check `doctor`. C'est exactement le défaut que M8 a puni. Il y a donc un **M7-0**, avant
tout le reste, dont le seul livrable est une réponse :

1. bundle minimal, exécutable principal Mach-O, signé ad-hoc ;
2. deux variantes : `execve` et enfant surveillé ;
3. il demande le micro par AVFoundation ;
4. ouverture par le Finder ;
5. **la fenêtre dit-elle « Aparté » ?** capture d'écran, et l'entrée dans Réglages
   Système ;
6. `xattr -lr` : quarantaine, oui ou non ;
7. recompiler à l'identique, re-signer, rouvrir : les autorisations tiennent-elles ?
   noter le `cdhash` et `codesign -d -r-` des deux côtés.

Si le point 5 échoue, M7 s'arrête là et on repense la distribution — sans avoir écrit
six lots.

### 6. La désinstallation, le LaunchAgent, la formula, la progression du modèle

Tout accepté, sans réserve :

- **`aparte uninstall-app`**, plus un état `doctor` pour « formula présente, app
  absente », « app présente, préfixe Homebrew disparu », « LaunchAgent vers une app
  absente ». Tu as raison de dire que mes deux phrases sur la désinstallation ne
  tenaient pas ensemble.
- **LaunchAgent** : pas de `KeepAlive` (le job sort tout de suite, il serait relancé en
  boucle), `RunAtLoad` seul, **chemins absolus** (`launchd` ne fait pas d'expansion, donc
  jamais de `~`), journaux vers `~/Library/Logs/Aparté/`. Plist historique assumé
  **comme choix de compatibilité** avec Big Sur, pas comme le mécanisme Apple courant —
  `SMAppService` est le moderne, il demande macOS 13.
- **La formula tranche** : version de Python épinglée, dépendances natives vérifiées,
  extras `whisper,recording,macos` et jamais `cuda`, `brew test` minimal, caveats.
- **La progression du modèle** a besoin d'un mécanisme, pas d'une intention. Voir plus
  bas : je le spécifie.

## Points où je tiens ma position

### La signature ad-hoc reste le choix de la v1 — mais pour une raison que ton objection ne touche pas

Ta citation d'Apple est juste :

> *If your code is unsigned, or signed ad hoc, the system can't tell that version N+1 of
> your code is the same as version N, and thus you'll encounter excessive prompts.*

Elle porte sur le cas où **le code change**. Or la conception fait que le bundle **ne
change pas d'une version d'Aparté à l'autre** : il ne contient ni la version, ni le code
Python, ni un chemin qui bouge — il pointe le chemin `opt` que Homebrew garde stable.
Un `brew upgrade` remplace le contenu du préfixe et **ne touche pas au bundle**. Il n'y a
donc pas de « version N+1 du bundle » dans le parcours normal. Version N+1 d'Aparté,
oui ; du lanceur, non.

Là où ton objection mord vraiment, et où j'ajoute une protection : **la réinstallation**.
`install-app --force` recompilerait le lanceur, et un `clang` différent peut produire un
binaire différent, donc un autre `cdhash`, donc des autorisations perdues — **en
silence**, avec la case toujours cochée dans les Réglages Système. C'est le piège que
décrit l'article que tu cites, et c'est un mauvais mode de panne. Trois mesures :

1. **`install-app` est idempotent** : si le bundle en place est déjà celui qu'on
   produirait, il ne réécrit rien, ne recompile rien, ne re-signe rien.
2. **La compilation est déterministe** dans ce qu'on contrôle : options fixes, pas de
   `__DATE__` ni de chemins absolus embarqués.
3. **`doctor` compare** le `cdhash` du bundle à celui relevé à l'installation et dit, en
   toutes lettres, que les autorisations ont été oubliées et qu'il faut les redonner.
   Une panne diagnostiquée au lieu d'une panne silencieuse.

**Le certificat auto-signé est pré-conçu, pas adopté.** Tu as raison qu'il ancre
l'exigence de signature sur le certificat au lieu du `cdhash`, et c'est plus robuste. Mais
il ajoute une identité dans le trousseau, une étape de création qui peut demander une
autorisation de trousseau, et une surface de support (« mon certificat a disparu ») pour
un projet qui tient à l'installation la plus simple possible. Je ne veux pas payer ça
avant de savoir si c'est nécessaire.

**Et je n'ai pas à en décider par argument** : le point 7 du lot de preuve mesure
exactement ça. S'il montre que les autorisations tombent au rebuild malgré une
compilation déterministe, on bascule sur le certificat local — la conception est écrite,
prête à être branchée. Sinon, on ne l'a pas payée. C'est la même méthode que pour
`execve` vs enfant : mesurer plutôt que trancher.

### « Installer puis ouvrir » : je ne concède pas la commande intermédiaire, je l'élimine

Tu écris qu'une formula ne donne pas « installer puis ouvrir » mais « installer, lancer
une commande de post-install, puis ouvrir ». C'est vrai du parcours que j'avais écrit, et
c'est une vraie perte face à la promesse.

Mais le `post_install` d'une formula tourne comme l'utilisateur, avec son `HOME`. Il peut
créer le bundle. Donc :

- `post_install` crée `~/Applications/Aparté.app` **s'il n'existe pas** — jamais s'il
  existe, ce qui préserve le `cdhash` à travers tous les `brew upgrade` ;
- `aparte install-app` reste le chemin explicite, pour réparer ou après un déplacement.

Le parcours redevient **`brew install` → ouvrir → deux autorisations**, et l'invariant
« l'upgrade ne touche pas au bundle » est renforcé, pas affaibli. Le prix, que je nomme :
un `brew uninstall` laisse l'application en place, d'où `aparte uninstall-app` et sa
mention dans les caveats.

## Ce que je spécifie, puisque tu notes que ça manquait

**La progression du modèle (M7f).** `faster-whisper` télécharge par `huggingface_hub`.
Le mécanisme retenu :

- Aparté appelle `snapshot_download` **lui-même**, sur un fil, au premier lancement quand
  le modèle manque — donc c'est l'application qui déclenche, jamais une route HTTP
  (invariant Darwin) ;
- la progression se lit en **sommant les fichiers `.incomplete` du cache** face à la
  taille attendue : c'est ce que l'écriture sur disque montre réellement, sans dépendre
  d'un rappel de progression que la bibliothèque ne garantit pas ;
- si `huggingface_hub` n'est pas importable ou si la taille attendue est inconnue,
  l'état est **indéterminé et honnête** — « téléchargement en cours » sans pourcentage
  inventé ;
- échec réseau, proxy, somme de contrôle : un état d'erreur nommé, et la phrase qui dit
  qu'Aparté ne dictera pas tant que ce n'est pas fini ;
- `doctor` garde son check `model_ready`, qui devient la source de vérité persistante.

## Découpage révisé

| Lot | Contenu | Prouvable sous Linux ? |
|---|---|---|
| **M7-0** | **Preuve TCC native.** Bundle sonde, lanceur Mach-O, deux variantes `execve`/enfant, signature ad-hoc, micro demandé, `xattr`, `cdhash` avant/après rebuild. **Aucun autre lot ne commence avant sa réponse.** | non, c'est tout l'objet |
| M7a | Le lanceur : source C générée, options de compilation, `Info.plist`, arborescence, réécriture `Cellar` → `opt`, déterminisme de l'entrée | oui |
| M7b | `aparte.icns` généré depuis `logo.svg`, commité, régénération documentée | oui |
| M7c | `install-app` (idempotent, `--force` qui prévient), `uninstall-app`, `desktop_integration()` sur Darwin, `codesign` **obligatoire**, checks `doctor` (bundle, `cdhash`, préfixe disparu) | oui |
| M7d | La formula : Python épinglé, extras, `post_install` idempotent, `brew test`, caveats, dépôt personnel, doc | partiellement |
| M7e | État `brew` dans `update.py`, libellés du menu et du panneau web | oui |
| M7f | Modèle visible au premier lancement, mécanisme ci-dessus | oui |
| M7g | LaunchAgent : `RunAtLoad` seul, pas de `KeepAlive`, chemins absolus, journaux. **Reportable** | oui, sauf le cycle `launchd` |
| M7h | Doc : `CLAUDE.md`, `CHANGELOG.md`, `tasks/todo.md`, `README.md` | — |

## Ce qui reste ouvert de mon côté

Rien de bloquant. Deux choix sont **délibérément renvoyés à la mesure** plutôt qu'à
l'argument — `execve` contre processus enfant, et ad-hoc contre certificat local — et le
lot M7-0 les tranche tous les deux avec des faits. Si tu penses qu'un des deux ne peut
pas se mesurer proprement ainsi, c'est le moment de le dire.
