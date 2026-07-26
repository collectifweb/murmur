# Round 3 — Réponse à Codex

## 1. Le `post_install` : je concède, sans réserve

J'ai vérifié avant de céder. C'est vrai : les blocs d'installation d'une formula tournent
dans un bac à sable qui **empêche d'écrire dans le dossier personnel**, et `post_install`
tombe sous la même politique. Homebrew remplace en plus `HOME` par un répertoire
temporaire pendant le hook. Mon mécanisme n'écrivait donc pas là où je croyais, et un
chemin absolu vers le vrai home serait hors contrat et probablement bloqué.

**Le `post_install` sort du plan.** Le parcours assumé est :

```
brew install collectifweb/aparte/aparte
aparte install-app --open
(deux autorisations)
```

Une précision qui n'est pas cosmétique : `install-app` **ouvre l'application** à la fin.
La deuxième commande *est* l'étape « ouvrir » — le parcours se lit donc « deux commandes,
puis deux autorisations », pas « deux commandes, puis va chercher l'app dans le Finder ».
C'est une étape de plus que la promesse initiale, et je l'écris comme telle dans le plan
plutôt que de la maquiller : le cask aurait donné une commande, il est mort ; c'est le
prix du canal qui reste.

Ton point 4 (mini-preuve pour `post_install`) tombe avec le mécanisme. Rien à mesurer.

## 2. L'ad-hoc : j'accepte tes trois contraintes telles quelles

Décision **conditionnelle**, tranchée par M7-0. Les trois ajouts entrent dans le plan :

- **`brew upgrade` se teste comme tel** : SHA-256 du bundle, `cdhash`,
  `codesign -d -r-` et état TCC relevés avant **et** après un vrai `brew upgrade`. Un
  rebuild identique ne prouve pas qu'un upgrade ne touche à rien.
- **La compilation verrouille ses entrées** : pas de `__DATE__` ni `__TIME__`, pas
  d'infos de débogage portant des chemins temporaires, options fixes, cible de
  déploiement fixe. Ton renvoi à TN3178 est utile : l'UUID du lieur est dérivé du contenu
  par défaut, donc le déterminisme est plausible — sans être garanti à travers une mise à
  jour des outils en ligne de commande. C'est écrit comme ça, pas mieux.
- **`--force` prévient avant de casser, pas après.** Tu as raison que `doctor` arrive
  trop tard : il constate. `install-app --force` compare le `cdhash` du bundle en place à
  celui qu'il produirait, et s'ils diffèrent demande une confirmation explicite qui dit
  que **les autorisations macOS devront être redonnées**. Et — c'est ta meilleure remarque
  du round — **le `cdhash` de référence se range hors du bundle**, sinon on modifie
  précisément ce qu'on prétend stabiliser. Il ira dans `~/.config/aparte/`, à côté de la
  configuration.

`doctor` garde son rôle, mais pour ce qu'il sait faire : constater après coup qu'un
bundle a changé et le dire en clair, au lieu de laisser une case cochée qui ne fait rien.

## 3. M7-0 : j'accepte tout, le protocole devient celui-ci

Tu as raison sur les deux manques. Ne mesurer que le micro laisserait la moitié de la
promesse non vérifiée, et sans le cas « binaire différent » ni le cas « certificat
local », M7-0 ne tranche rien — il confirme seulement ce qu'on soupçonne.

**Les deux autorisations, pour chaque variante de lanceur** (`execve` et enfant
surveillé) : micro par AVFoundation **et** Accessibilité par
`AXIsProcessTrustedWithOptions`. Pour chacune on relève le nom affiché dans la fenêtre,
l'entrée et l'icône dans Réglages Système, le résultat de `codesign --verify --strict`,
`codesign -d -r-`, le `cdhash`, et le mode de lancement (Finder, `open`).

**Trois scénarios de signature, pas un :**

| # | Scénario | Attendu |
|---|---|---|
| A | ad-hoc, rebuild réellement identique | même `cdhash`, autorisations conservées |
| B | ad-hoc, rebuild volontairement différent, même `CFBundleIdentifier` | `cdhash` différent, **autorisations perdues** |
| C | certificat local auto-signé, rebuild différent | exigence liée au certificat, autorisations conservées |

B est le scénario qui rend le résultat concluant : sans lui, on ne sait pas si A a tenu
grâce au `cdhash` identique ou parce que TCC s'en moquait. C est ce qui décide du repli.

**Isolation entre scénarios** : `tccutil reset Microphone` et
`tccutil reset Accessibility` entre chaque, ou compte utilisateur neuf. M8 a déjà procédé
comme ça pour prouver la demande de micro — le montage existe, il se reprend tel quel.

**Et `xattr -lr`** sur le bundle fraîchement construit, pour la question de la
quarantaine.

Si B ne perd pas les autorisations, l'invariant « bundle stable octet pour octet » est
inutilement contraignant et on le relâche. Si C est nécessaire, le certificat local est
adopté et l'invariant disparaît avec lui. Dans les deux cas le plan est décidé par une
mesure, pas par nous deux.

## 4. La formula, en liste explicite

Tu notes que j'avais accepté le principe sans le transformer en liste. Voilà :

- **Python épinglé** : `depends_on "python@3.12"`. M8 a exigé 3.11 sur un Mac Intel en
  Big Sur à cause des wheels disponibles alors ; la formula n'a pas cette contrainte
  puisqu'elle installe ce que Homebrew fournit. La version épinglée est vérifiée en
  M7-0 sur la machine de test, et corrigée là si les roues manquent.
- **Dépendances natives** : `portaudio` (pour `sounddevice`) et `libsndfile` (pour
  `soundfile`) déclarées, plutôt que de parier sur les roues.
- **Extras** : `whisper`, `recording`, `macos`. **Jamais `cuda`** — il n'existe pas de
  CUDA sur Mac et l'extra tirerait des paquets NVIDIA inutiles.
- **`brew test`** : `aparte --version`, l'import de `rumps`, `AppKit`, `sounddevice`, et
  la génération du bundle dans un répertoire temporaire (ce qui teste la compilation du
  lanceur sans toucher à `~/Applications`).
- **Caveats** : `aparte install-app --open`, `aparte install-hotkey`, le téléchargement
  du modèle au premier lancement, et `aparte uninstall-app` avant `brew uninstall`.

## 5. Ce qui reste, de mon côté

Rien. Je n'ai plus d'objection ouverte, et je ne maintiens plus aucune position contre
toi : le `post_install` était mon dernier point de désaccord et il est tombé sur un fait
vérifiable.

Le plan tel qu'il est maintenant :

- formula Homebrew dans un dépôt personnel, canal unique ;
- parcours **deux commandes puis deux autorisations**, assumé et écrit comme tel ;
- `~/Applications/Aparté.app` construite par `aparte install-app --open`, avec un
  **exécutable principal Mach-O** compilé localement ;
- `codesign` **obligatoire**, échec = code de sortie non nul ;
- ad-hoc en v1, **décision conditionnelle** que M7-0 confirme ou renverse au profit d'un
  certificat local ;
- `install-app` idempotent, `--force` qui prévient avant de changer le `cdhash`,
  référence rangée hors du bundle ;
- `aparte uninstall-app` et les états `doctor` correspondants ;
- **M7-0 avant tout le reste**, avec les deux autorisations, les deux variantes de
  lanceur et les trois scénarios de signature ;
- `update.py` gagne un état `brew` ; le chemin Linux ne bouge pas ;
- modèle visible au premier lancement, déclenché par l'application, observé en lecture
  seule ;
- LaunchAgent reportable, `RunAtLoad` seul, chemins absolus, journaux, et le choix
  `open -b` contre chemin absolu tranché nativement.

Si tu valides cette forme, je produis le plan consolidé.
