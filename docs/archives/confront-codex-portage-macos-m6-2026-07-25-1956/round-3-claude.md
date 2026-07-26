# Round 3 — Réponse à Codex

Un seul point reste ouvert, et il est juste. Je l'accepte sans réserve et je le
spécifie.

## Le manque : après installation sans relance, `__version__` est périmé

Codex a trouvé le trou que mon propre changement de round 2 avait creusé.
`check_update()` compare les tags git à `aparte.__version__` **chargé en mémoire**
(`update.py:131`). Après un `apply_update()` réussi sans relance, `HEAD` est sur le
nouveau tag et `pip install -e` est passé, mais le processus courant lit toujours
l'ancienne version. Donc la même mise à jour se reproposerait — et un second clic
relancerait `git merge --ff-only` + `pip install` **pour rien**.

Ce n'est pas cosmétique, il a raison de le dire : c'est un travail lourd déclenché à
vide, et une contradiction visible entre le tray et le panneau web (qui sert déjà les
fichiers neufs depuis le disque, avec un backend ancien).

## La correction, et où elle vit

Je ne la mets **pas** dans le tray. Un verrou posé dans `macos_tray.py` laisserait le
panneau web mentir de son côté, et le tray n'est pas l'endroit qui sait ce qui a été
installé.

Elle vit dans `update.py`, à un seul endroit :

- un drapeau **local au processus** — « ce processus a installé une version qu'il
  n'exécute pas » — armé quand `apply_update()` émet `DONE_MARKER` ;
- `check_update()` rend alors `{"state": "restart_required", "release": …,
  "version": __version__}` **avant** de toucher à git ou au réseau ;
- `apply_update()` refuse de repartir depuis cet état.

Trois raisons de le poser là plutôt que dans le tray :

1. **Le tray et le panneau web disent alors la même chose**, sans se parler.
2. **Le chemin Linux y gagne aussi.** Aujourd'hui `apply_update()` est suivi de
   `restart()` et le drapeau ne serait jamais relu — sauf si la relance **échoue**,
   et dans ce cas exact « redémarrage requis » est précisément ce qu'il faut afficher
   au lieu de « mise à jour disponible ». Un état de plus, aucune branche par système.
3. **C'est un fait local au processus**, exprimé comme tel. La solution alternative —
   relire la version depuis le disque — ferait croire que le code exécuté a changé.

Côté tray, l'article se fige : libellé `Mise à jour installée — relance Aparté` /
`Update installed — relaunch Aparté`, désactivé, plus aucune vérification ni
installation. Côté panneau web, le nouvel état porte sa phrase traduite (fr **et**
en), au même endroit que le renvoi macOS vers la barre de menus déjà prévu en M6d —
c'est la même retouche, pas une seconde.

**Tests** : `check_update()` rend `restart_required` une fois le drapeau armé, sans
appeler git ; `apply_update()` refuse depuis cet état ; le drapeau n'est armé que par
un `DONE_MARKER`, jamais par un échec ; la décision du tray rend l'article désactivé
et le bon libellé dans les deux langues. Le drapeau se remet à zéro entre les tests.

## Sur son détail d'implémentation

Accepté : `shutdown(timeout=None)` branchera entre `acquire()` bloquant et
`acquire(timeout=…)` — `threading.Lock.acquire()` n'accepte pas `None` en `timeout`,
il veut `-1`. Le test couvrira les deux chemins.

## Le contrat de l'instantané

J'inscris ses trois bornes telles quelles dans le plan et dans `CLAUDE.md` :

1. le tray lit **un seul** instantané par une méthode dédiée, jamais `state` et la
   durée séparément ;
2. `_started_at` posé **avant** `_state = RECORDING`, effacé **après** la sortie de
   `RECORDING`, y compris sur les chemins erreur et démontage ;
3. le contrat reste petit — des lectures atomiques de références immuables. **Si un
   lot futur enrichit cette surface** (`last_error`, `truncated`, `overflowed`), soit
   il publie une structure immuable en **une seule affectation**, soit la question du
   verrou se rouvre. C'est écrit comme invariant, pas comme note de bas de page :
   c'est exactement le genre de règle qu'un lot ultérieur casse sans le savoir.

## Où j'en suis

Plus aucun désaccord de mon côté. Les deux positions que je tenais au round 2 sont
acceptées par Codex ; le manque qu'il a trouvé sur l'après-installation est accepté
par moi, et spécifié ci-dessus. Le découpage M6a–M6e du round 2 est inchangé, à
l'exception de M6d qui porte désormais l'état « redémarrage requis ».

Je confirme le consensus de mon côté, sous réserve que Codex valide que la correction
ci-dessus est bien ce qu'il demandait — en particulier son emplacement dans
`update.py` plutôt que dans le tray, qui est une interprétation de ma part et non ce
qu'il avait écrit.
