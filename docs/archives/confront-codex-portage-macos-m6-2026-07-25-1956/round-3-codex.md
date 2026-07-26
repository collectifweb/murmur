# Round 3 - Contre-réponse Codex

**Points résolus depuis le round précédent**

Le manque que j'avais bloqué au round 2 est maintenant correctement fermé. Le drapeau `restart_required` doit vivre dans `update.py`, pas dans `macos_tray.py` : c'est le module qui sait qu'une installation a réussi alors que le processus exécute encore l'ancien code. Cette position centralisée donne bien la même vérité au tray et au panneau web, puisque le handler HTTP ne fait déjà que relayer `check_update()` pour `GET /api/update/check`.

Dans le code réel, la correction est implémentable telle quelle. `DONE_MARKER` existe déjà dans `src/aparte/update.py`, `apply_update()` est le seul endroit qui l'émet après `git merge --ff-only` et `pip install -e`, et `check_update()` compare bien la dernière release à `__version__` chargé en mémoire. Il suffit donc de stocker, au moment du succès, une petite donnée process-local du type "release installée en attente de relance", puis de faire répondre `check_update()` par `state: "restart_required"` avant `find_repo()`, avant Git, et avant tout fetch.

`apply_update()` doit explicitement refuser ce nouvel état. Ce n'est pas seulement propre : c'est nécessaire, parce que la fonction suppose ensuite que les états restants portent `repo` et `release`. Le refus doit arriver juste après l'appel initial à `check_update()`, au même niveau que `manual`, `no_upstream`, `error` et `current`, avec un message de log clair et sans appeler `_stream()`.

La forme proposée par Claude règle aussi l'incohérence web. `src/aparte/assets/app.js` sait déjà rendre un état `update.<state>` quand l'état n'est pas `available`, et n'affiche le bouton d'application que pour `available && !dirty`. Ajouter `update.restart_required` dans `i18n.js`, en français et en anglais, suffit pour que ce nouvel état n'offre plus de bouton et dise la vérité. La retouche macOS déjà acceptée au round 2 reste séparée : quand l'état est encore `available` sur Darwin, le panneau web ne doit pas proposer une route `POST /api/update/apply` qui est volontairement 404 ; quand l'état est `restart_required`, le modèle actuel cache déjà l'application.

Les tests proposés sont au bon endroit. `tests/test_update.py` couvre déjà `check_update()` et `apply_update()` avec des checkouts Git temporaires ; on peut y ajouter les cas "drapeau armé -> `check_update()` rend `restart_required` sans appeler Git", "`apply_update()` refuse depuis cet état", "échec de merge/pip -> pas de drapeau", et "succès -> drapeau armé au moment du `DONE_MARKER`". Le seul détail pratique est de réinitialiser ce drapeau entre tests, par helper interne ou `addCleanup`, pour ne pas polluer les cas existants.

Le détail `shutdown(timeout=None)` est aussi correctement repris : l'implémentation devra choisir entre `acquire()` bloquant et `acquire(timeout=...)`, pas passer `None` tel quel.

Le contrat de l'instantané sans verrou est maintenant assez borné pour être acceptable : une méthode dédiée, `_started_at` publié avant `RECORDING` et effacé après la sortie de cet état, et aucune extension future par objets mutables sans rouvrir la question.

**Points encore en débat**

Je n'ai plus de désaccord substantiel.

Deux précisions d'implémentation restent à garder dans le plan final, mais elles ne changent pas le verdict :

- le drapeau `restart_required` doit mémoriser la release cible au moment du succès, car `check_update()` ne doit pas relire Git une fois le drapeau armé ;
- le nouvel état doit rester process-local et volontairement honnête : il ne dit pas "la version exécutée est X", il dit "ce processus a installé X mais exécute encore l'ancien code".

Sur Linux, je ne vois pas d'effet de bord négatif. Le chemin existant reste `apply_update()` puis `restart()` depuis `_handle_update_apply()`. Si `os.execv` réussit, le processus disparaît et le drapeau disparaît avec lui. Dans la fenêtre d'une seconde avant la relance, ou si la relance échoue, `restart_required` est au contraire le meilleur état possible : il évite une deuxième installation inutile et explique pourquoi le backend ancien est encore vivant. Le comportement normal Linux n'est donc pas dégradé ; le comportement d'échec est amélioré.

La suite ciblée actuelle passe avant modification : `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest tests/test_update.py` -> 17 tests OK. Cela ne valide évidemment pas le code M6 futur, mais confirme que les tests existants autour d'update sont un bon point d'ancrage.

**Évaluation globale**

Le plan M6a-M6e amendé par le round 3 est prêt. Les réserves techniques restantes sont des contraintes d'implémentation et de validation native déjà identifiées, pas des désaccords d'architecture : `update.py` est le bon emplacement pour l'état post-installation, le chemin Linux reste cohérent, et le panneau web peut lire la même vérité que le tray sans liaison directe entre les deux.

Claude peut produire le plan final consolidé.

CONSENSUS_ATTEINT — aucun désaccord substantiel ne subsiste, le plan est validé en l'état, Claude peut produire le plan final consolidé.
