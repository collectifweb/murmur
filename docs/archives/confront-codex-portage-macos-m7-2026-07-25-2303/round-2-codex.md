## **Points résolus depuis le round précédent**

Sur le lanceur Mach-O, l'ajustement est exactement celui que je voulais. Le script shell
comme `CFBundleExecutable` sort du plan, et le bundle reçoit un exécutable principal
natif. Je valide aussi que le comportement TCC du lanceur ne soit plus déduit sous
Linux : il doit être observé sur Mac.

Je valide le passage de `codesign` en prérequis dur. C'est important : un bundle non
signé ou mal signé ne doit pas être présenté comme installé. La validation native doit
garder `codesign --verify --strict` et l'inspection de l'identité après signature, pas
seulement la réussite de la commande d'installation.

La reformulation sur la quarantaine est bonne. « Ne devrait pas être quarantiné dans le
flux normal » + preuve par `xattr -lr` est la formulation correcte. Ce n'est plus un
axiome.

Je valide le déplacement du lot de preuve en M7-0. C'était le point le plus important :
avant de produire l'icône, la commande, la formula et la doc, il faut savoir si le pari
TCC tient vraiment.

Je valide `aparte uninstall-app`, les états `doctor` associés, et le fait d'admettre
qu'un artefact dans `~/Applications` n'appartient pas proprement au cycle
`brew uninstall`.

Je valide les détails du LaunchAgent : pas de `KeepAlive`, `RunAtLoad` seul, chemins
absolus, logs dans `~/Library/Logs/Aparté/`, et plist historique assumé comme choix de
compatibilité Big Sur plutôt que comme mécanisme moderne. Le choix précis entre
`open -b ca.collectifweb.aparte` et `open /Users/.../Applications/Aparté.app` reste à
valider nativement, mais le cadrage est maintenant sain.

Je valide aussi que la formula doive verrouiller ses choix : version Python, dépendances
natives, extras exacts, absence de `cuda`, `brew test`, caveats. Claude a accepté le
point ; il faudra encore le transformer en liste explicite dans M7d, mais ce n'est plus
un désaccord.

Sur la progression du modèle, la spécification est assez concrète pour avancer. Observer
les fichiers `.incomplete` de `huggingface_hub` est acceptable si l'interface reste
honnête quand la taille attendue est inconnue. Ce point n'est plus bloquant pour le plan
d'installation macOS.

## **Points encore en débat**

### 1. Le `post_install` Homebrew ne peut pas créer fiablement `~/Applications/Aparté.app`

Je ne suis pas convaincu par l'argument de Claude ici ; je pense même qu'il est faux
dans l'état actuel de Homebrew.

La documentation Homebrew dit que `post_install` sert aux étapes d'initialisation et de
préparation de données, qu'il peut être rejoué par `brew postinstall`, et que les étapes
structurées s'exécutent avec la même politique de sandbox que `post_install`
(https://docs.brew.sh/Formula-Cookbook#running-commands-after-installation).

Plus décisif : la doc sécurité Homebrew dit que `post_install`, que l'installation vienne
d'une bouteille ou d'une compilation source, s'exécute dans le sandbox, avec filtrage de
l'environnement (https://docs.brew.sh/Homebrew-Security-and-Supply-Chain). Le code
documenté de `Formula#run_post_install` remplace `HOME` par un répertoire temporaire
`<formula>-postinstall-*` avant d'exécuter le hook
(https://docs.brew.sh/rubydoc/Formula.html, méthode `run_post_install`). Donc
`~/Applications` ne désigne pas le home utilisateur réel pendant `post_install`.

Même si on contournait `~` avec un chemin absolu vers `/Users/alexandre/Applications`,
ce serait en dehors du modèle normal de la formula : le hook est sandboxé et conçu pour
écrire dans les zones Homebrew, `var`, `etc`, cache/temp, pas dans le dossier applicatif
personnel. Homebrew refuse aussi `sudo brew`, et son modèle est mono-utilisateur mais pas
« les hooks écrivent dans tout le home réel »
(https://docs.brew.sh/FAQ#why-does-homebrew-say-sudo-is-bad).

Conclusion : le parcours `brew install -> ouvrir -> deux autorisations` ne peut pas
reposer sur `post_install` dans une formula. Le plan doit revenir à :

- `brew install collectifweb/aparte/aparte`
- `aparte install-app`
- ouvrir Aparté

ou choisir un autre canal pour créer l'app utilisateur. Les caveats peuvent rendre la
commande évidente, mais ils ne suppriment pas cette étape. Sur ce point, Claude ne
répare pas ma critique précédente ; il ajoute un mécanisme que Homebrew rend impropre.

### 2. L'ad-hoc comme choix v1 est défendable, mais pas encore assez prouvé

Je change partiellement d'avis : si le bundle ne change vraiment pas entre deux versions
d'Aparté, l'objection Apple sur « version N+1 » mord beaucoup moins dans le parcours
normal `brew upgrade`. Le raisonnement de Claude est solide sur ce sous-cas : la version
du code Python change, pas nécessairement celle du lanceur que TCC voit.

Mais j'ajoute trois contraintes.

D'abord, `brew upgrade` doit être testé comme tel : SHA-256 du bundle, `cdhash`,
`codesign -d -r-` et état TCC avant/après. Un simple rebuild identique ne prouve pas que
la formula ne touche pas au bundle, surtout si le plan gardait un `post_install`.

Ensuite, la compilation locale par `clang` peut être raisonnablement déterministe sur la
même machine et avec les mêmes outils, mais seulement si on verrouille les entrées :
pas de `__DATE__`, pas de debug info avec chemins temporaires, options fixes, cible de
déploiement fixe, pas de `-random_uuid`. Apple documente que le linker génère par défaut
un UUID fondé sur le contenu, précisément pour aider les builds reproductibles
(https://developer.apple.com/documentation/technotes/tn3178-checking-for-and-resolving-build-uuid-problems).
Donc oui, c'est plausible. Non, ce n'est pas une garantie à travers une mise à jour des
Command Line Tools ou un changement d'options.

Enfin, `doctor` seul est trop tardif pour `install-app --force`. Si `--force` va
remplacer un bundle signé par un autre `cdhash`, la commande doit le détecter avant
remplacement et afficher une confirmation explicite : « les autorisations macOS devront
être redonnées ». Le `cdhash` de référence doit être stocké hors du bundle, sinon on
risque de modifier ce qu'on prétend stabiliser.

Je peux donc accepter ad-hoc en v1, mais seulement comme décision conditionnelle :
M7-0 doit prouver que le parcours normal conserve les autorisations, et `install-app`
doit rendre bruyante toute opération qui change le `cdhash` avant de casser l'état TCC.

### 3. M7-0 doit mesurer davantage pour trancher réellement

L'idée de mesurer `execve` vs processus enfant est bonne. Le protocole proposé ne suffit
pas encore.

Il ne faut pas tester seulement la demande micro. La promesse produit est « deux
autorisations » : microphone et Accessibilité. Les deux variantes du lanceur doivent donc
déclencher et vérifier les deux chemins TCC, par exemple AVFoundation pour le micro et
`AXIsProcessTrustedWithOptions` pour Accessibilité. Pour chaque variante, il faut relever
le nom affiché dans la fenêtre, l'entrée dans Réglages Système, l'icône associée, le
résultat `codesign`, le `cdhash`, et le mode de lancement (`open`, Finder).

Pour trancher ad-hoc vs certificat local, M7-0 doit tester trois cas, pas un seul :

- ad-hoc, rebuild réellement identique, même `cdhash` attendu ;
- ad-hoc, rebuild volontairement différent mais même `CFBundleIdentifier`, perte
  d'autorisations attendue ;
- certificat local auto-signé, rebuild différent, pour vérifier si l'exigence TCC reste
  liée au certificat plutôt qu'au seul `cdhash`.

Il faut aussi réinitialiser proprement TCC entre scénarios ou utiliser un utilisateur de
test neuf, sinon les résultats peuvent se contaminer. Sans le cas « binaire différent »
et sans le cas « certificat local », M7-0 ne tranche pas ad-hoc vs certificat ; il prouve
seulement qu'un rebuild identique ad-hoc peut survivre, ce qu'on soupçonne déjà.

### 4. Le `post_install` doit sortir de M7-0 ou devenir une preuve séparée

Si Claude tient à maintenir `post_install`, il faut ajouter une mini-preuve indépendante :
formula de sonde, `post_install` qui tente de créer `ENV["HOME"]/Applications/Test.app`,
puis tentative par chemin absolu dans le home réel, avec logs sandbox. Mon attente est
que le premier cas écrive dans un home temporaire et que le second échoue ou soit hors
contrat. Si cette mesure contredit les docs et le code Homebrew actuels, je changerai
d'avis. En attendant, je considère ce point tranché contre le plan actuel.

## **Évaluation globale**

Il y a beaucoup moins de désaccords qu'au round précédent. Les corrections sur Mach-O,
`codesign`, quarantaine, test après signature, M7-0 en premier, `uninstall-app`,
LaunchAgent et formula verrouillée vont dans le bon sens.

Il reste deux désaccords bloquants :

- la promesse `brew install -> ouvrir` via `post_install` ne tient pas avec le
  fonctionnement actuel de Homebrew ;
- le protocole M7-0 ne mesure pas encore assez pour décider ad-hoc vs certificat local,
  ni pour valider les deux autorisations réellement promises.

La direction générale est bonne, mais le plan dans sa forme actuelle n'est pas prêt. Il
devient prêt si on retire la création du bundle de `post_install`, qu'on assume
`aparte install-app` comme étape explicite, et qu'on renforce M7-0 avec les cas ci-dessus.

CONSENSUS_REFUSE
