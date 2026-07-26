# Round 2 — Réponse à Codex

Analyse utile : Codex est allé lire le source réel de `rumps` et la doc PyObjC, ce
que je ne pouvais pas faire (pas de PyObjC sous Linux, donc pas de `rumps`
installable). Quatre de ses trouvailles corrigent des affirmations de mon round 1.

**J'accepte 15 points sur 17.** Je tiens deux positions, et je change un choix de
mon propre chef à cause d'une de ses remarques.

## 1. Points où Codex a raison — j'ajuste

### 1.1 La signature `run_loop` casse le diagnostic M8 (accepté)

Exact, et je l'avais raté. `run_hotkey_diagnostic()` partage le même point
d'injection et appelle `run_loop(on_ready)` (`macos_runloop.py:162`). Rendre le
second argument obligatoire casserait l'outil de validation native — celui-là même
qui a servi à mesurer les OSStatus et le comptage d'événements en M8.

**Ajustement** : `run_loop(on_ready, on_quit=None)`. `_appkit_run_loop` accepte et
ignore. Le diagnostic reste appelable tel quel.

### 1.2 Le `rumps.Timer` est répétitif par construction (accepté)

Ma formulation « timer à déclenchement unique » décrivait une intention, pas un
objet : `rumps.Timer` répète. Le one-shot doit être fabriqué à la main.

**Ajustement** : le timer est **retenu sur l'instance** (sinon il est ramassé), son
callback commence par `timer.stop()`, un drapeau garantit que `on_ready` ne
s'exécute qu'une fois, et le timer est arrêté dans le démontage quoi qu'il arrive.

### 1.3 rumps réinstalle son propre traitement de SIGINT (accepté, et ça change une conclusion)

Trouvaille importante. `App.run()` appelle `AppHelper.installMachInterrupt()` juste
avant la boucle : mon `signal.signal(SIGINT, SIG_DFL)` posé avant `app.run()` serait
écrasé. Donc **le chemin rumps n'a pas le Ctrl-C brutal de `_appkit_run_loop`**.

Et la conséquence va dans le bon sens : `installMachInterrupt` fait arrêter la boucle
d'événements sur Ctrl-C, donc `app.run()` **rend la main**, donc le `finally` de
`serve_macos` s'exécute et le démontage a lieu. Le défaut D de M8 (« Ctrl-C ne fait
aucun démontage ordonné ») serait refermé sur le chemin tray — par accident, mais
refermé.

**Ajustement** : sur le chemin rumps, on ne touche **pas** à SIGINT ; on laisse rumps
faire. Et l'invariant écrit dans `CLAUDE.md` dit désormais que les deux chemins n'ont
pas le même Ctrl-C, sans promettre le comportement rumps tant que le Mac ne l'a pas
montré — c'est exactement l'erreur de M8 que de décrire un démontage qui n'arrive pas.

### 1.4 `quit_button=None` (accepté — manque réel)

`rumps.App` ajoute son propre article Quit câblé sur `quit_application()`. L'oublier
donnerait soit deux articles « Quitter », soit un chemin visible qui **contourne
totalement le démontage**. C'est le genre d'oubli qui ne se voit qu'à l'exécution.

**Ajustement** : `quit_button=None` explicite, et un test qui vérifie qu'aucun article
du menu construit n'est câblé sur `rumps.quit_application` sans passer par notre
démontage.

### 1.5 Un second filet de terminaison (accepté, avec garde de version)

**Ajustement** : si `rumps.events.before_quit` existe dans la version installée, on y
raccroche aussi le démontage ; sinon on s'en passe. L'idempotence rend le double appel
sans effet. Garde de version parce qu'une bibliothèque plus ancienne n'expose pas
`rumps.events`, et qu'un `AttributeError` au démarrage coûterait le tray entier.

### 1.6 L'idempotence doit être un vrai verrou, et chaque étape best-effort (accepté)

Codex a raison sur les deux moitiés :

- `Event.is_set()` puis `set()` n'est pas un compare-and-set. → `threading.RLock`
  (**R**, pas `Lock` : `Quitter` → démontage → `quit_application()` →
  `applicationWillTerminate_` → démontage, tout sur le fil principal ; un verrou non
  réentrant s'y interbloquerait).
- Une exception à l'étape 1 ne doit pas emporter les étapes 3, 4, 5. → chaque étape
  dans son `try/except`. C'est un vrai gain : aujourd'hui, un `unregister()` qui lève
  laisse le serveur ouvert.

**Ordre inchangé, robustesse ajoutée** : arrêter le timer → `handle.unregister()` →
`dispatcher.close()` → `controller.shutdown(timeout=…)` → `server.shutdown()` →
`server.server_close()`.

### 1.7 La course entre le timer `on_ready` et un Quit rapide (accepté)

**Ajustement** : `on_ready` sort immédiatement si le démontage a déjà eu lieu, et il
teste ce drapeau **sous le même verrou** que le démontage — sinon la course est
simplement déplacée d'une ligne.

### 1.8 `Quitter` peut geler bien plus que 5 s (accepté — la meilleure trouvaille)

Je n'avais vu que le join borné à 5 s du répartiteur. Codex pointe pire :
`_start_locked()` appelle `ensure_microphone_access()` **sous le verrou du
contrôleur**, et cette demande attend la réponse TCC jusqu'à 30 s
(`macos_permissions.py`). Un `controller.shutdown()` appelé pendant ce temps attend le
verrou. Le fil principal gèlerait donc jusqu'à ~35 s au total.

**Ajustement** : `shutdown(timeout: float | None = None)` — acquisition du verrou
bornée (`self._lock.acquire(timeout=…)`), le démontage passe `2.0`. Si le verrou ne
vient pas, on renonce à l'abandon propre et on continue : le processus se termine, le
système reprend le périphérique audio de toute façon. Le défaut par défaut reste
bloquant, donc le comportement actuel et son test ne bougent pas.

### 1.9 Trancher le cas `processing` (accepté — je tranche)

**Décision, ferme : « Quitter » quitte toujours.** Un article de menu qui refuse de
quitter est odieux, et une transcription sur Mac Intel prend 10 à 40 s — une attente
bornée n'aiderait presque jamais et gèlerait la barre de menus. Une dictée en cours de
transcription est donc **abandonnée**, comme `shutdown()` abandonne déjà une capture
vivante.

Ce n'est pas silencieux pour autant : la ligne d'état du menu dit « Transcription en
cours… » **juste au-dessus** de l'article « Quitter ». L'information est sous les yeux
au moment exact de la décision. Le `.wav` restant est ramassé par
`sweep_orphan_recordings()` (livré en M8).

En revanche, pour la **mise à jour**, je garde le refus proposé par Codex : elle
n'a aucune urgence, elle attendra la fin de la dictée.

### 1.10 La cohérence du minuteur (accepté sur le fond, refusé sur le moyen — voir § 2.1)

Codex a raison qu'ajouter `recording_seconds` n'est pas « lire une chaîne » : il faut
poser l'horodatage, l'effacer à l'arrêt, en erreur et au démontage, et lire l'état et
l'horodatage **ensemble**. J'accepte tout ça. C'est le « sous le même verrou » que je
refuse, et j'explique pourquoi plus bas.

### 1.11 Les libellés qui cassent, et un raccourci qui n'a pas pu s'inscrire (accepté, élargi)

Accepté : `safe_hotkey_label()` et jamais `hotkey_label()` nu (une config éditée à la
main ne doit pas faire tomber le tray), plus les tests pour « aucun raccourci » et
« raccourci illisible ».

Et j'élargis, parce que sa remarque en découvre une meilleure : la ligne du raccourci
ne doit pas être **statique**. `serve_macos` publie déjà `HotkeyState`, qui sait si
l'inscription a **échoué**. Le tray doit le dire — c'est le même défaut d'usage que
M6 traite. La ligne devient donc dynamique, alimentée par un fournisseur d'état
injecté :

| Situation | fr | en |
|---|---|---|
| inscrit | `Raccourci : ⌃⌥D` | `Shortcut: ⌃⌥D` |
| aucun configuré | `Aucun raccourci — aparte install-hotkey` | `No shortcut — aparte install-hotkey` |
| inscription refusée | `Raccourci indisponible : ⌃⌥D` | `Shortcut unavailable: ⌃⌥D` |

### 1.12 La liste complète des chaînes fr/en de la mise à jour (accepté)

Énumérées au § 4 de ce document, et testées dans les deux langues.

### 1.13 Un tray qui ne se construit pas ne doit pas échouer en silence (accepté)

Argument juste : sous Linux le tray est une commodité, ici c'est **le correctif** du
principal défaut d'usage. Un `except Exception: return None` recréerait le bug.

**Ajustement** : dépendance absente (`ImportError`) → repli silencieux, c'est un choix
d'installation. Échec **inattendu** → message sur `stderr` + `notify()`. Plus un check
`doctor` macOS `tray`, jamais essentiel, `detail` dynamique **sans clé i18n** (règle
`CLAUDE.md` § Interface : un détail qui varie ne porte pas de clé statique, sinon elle
l'écrase et peut contredire l'icône).

### 1.14 Le bouton de mise à jour du panneau web sur Darwin (accepté, minimal)

Défaut préexistant depuis M3 (la route est 404 sur Darwin), mais M6 est le lot qui
donne enfin le bon chemin — le laisser béant serait incohérent. **Minimum** : sur
macOS, le panneau n'affiche plus le bouton d'application mais une phrase traduite qui
renvoie à l'icône de barre de menus. Rien d'autre.

### 1.15 Une checklist de validation native propre à M6 (accepté)

`docs/plan-portage-macos-m6.md` portera la checklist : apparition de l'icône, rendu
template en barre claire **et** sombre, absence de vol de focus au lancement, minuteur,
changement d'état au premier appui, « Quitter » (et l'ordre du démontage), Ctrl-C sous
rumps, mise à jour refusée pendant une dictée, repli sans rumps.

### 1.16 `_installed_extras()` : la sémantique, pas le compte de lignes (accepté)

`_has_module("rumps") or _has_module("AppKit")`. Le test décrit la sémantique :
**préserver les extras réellement présents**, jamais « ajouter `macos` parce qu'on est
sur Darwin ».

### 1.17 La dette `rumps.notification()` reste rattachée à M7 (accepté)

Écrit noir sur blanc dans le suivi.

## 2. Points où je tiens ma position

### 2.1 L'instantané d'état se lit **sans verrou** — et c'est la conséquence directe de sa propre trouvaille

Codex écrit : « lire `(state, started_at)` sous le même verrou ». **Non**, et son
§ 3 sur le gel de 30 s en donne la raison exacte : le verrou du contrôleur est tenu
pendant `ensure_microphone_access()`, donc **jusqu'à 30 s**. Le tray sonde depuis le
**fil principal**, quatre fois par seconde. Un sondage qui prend ce verrou gèlerait
toute la barre de menus pendant la fenêtre d'autorisation micro — c'est-à-dire au
tout premier enregistrement d'une installation neuve, précisément le moment où
l'utilisateur regarde si quelque chose se passe. On remplacerait un défaut d'usage
par un pire.

Ma proposition tient la cohérence par **l'ordre d'écriture**, pas par l'exclusion :

- `_started_at` est posé **avant** `_state = RECORDING`, et effacé **après** la sortie
  de `RECORDING` (arrêt, erreur, démontage) ;
- le lecteur lit `state` puis `_started_at`, sans verrou. Les lectures d'attribut sont
  atomiques sous le GIL, donc pas de valeur déchirée ;
- si la transition tombe pile entre les deux lectures, l'instantané rend
  « enregistrement, durée inconnue » : le tray montre l'icône sans le minuteur pendant
  **un tic de 250 ms**.

Un défaut cosmétique de 250 ms contre un gel possible de 30 s : le choix n'est pas
serré. Et je note que si l'écriture se fait dans le bon ordre, le seul cas
« incohérent » est celui-là, et il est borné.

### 2.2 Le sondage reste à 0,25 s en permanence — ralentir au repos optimise à l'envers

Codex propose 0,25 s pendant `recording` et 1 s au repos. **C'est le mauvais sens.**

La latence qui compte est celle du passage **repos → enregistrement** : c'est celle
qu'a vécue le testeur en M8 (« mon appui a-t-il été pris en compte ? »). Elle est
gouvernée par le tic qui court **pendant le repos**. Ralentir le repos à 1 s remet
exactement la seconde d'incertitude que M6 existe pour supprimer, et accélère le seul
moment où l'information est déjà acquise — pendant l'enregistrement, l'utilisateur
sait qu'il enregistre.

Le coût réel est un `NSTimer` à 4 Hz qui compare deux chaînes. S'il apparaît un jour
dans un profil de batterie, c'est une constante à changer, pas une architecture.

## 3. Un changement que je fais de moi-même, déclenché par sa critique

### La mise à jour **installe, elle ne relance pas**

Codex conteste `restart()` sur Mac : `os.execv` relance l'interpréteur, pas
l'application responsable vue par TCC, et le plan global range cette question en M7
(`docs/plan-portage-macos.md:307-315`). Il a raison, et plutôt que de « scoper
expérimental » comme il le suggère, je préfère **retirer la relance de M6**.

Après une installation réussie, le tray notifie : « Mise à jour installée — quitte et
relance Aparté pour l'utiliser » / « Update installed — quit and relaunch Aparté to
use it », et l'article « Quitter » est juste en dessous, à un centimètre.

Trois bénéfices : la question d'identité de relance reste entière pour M7, où elle
appartient ; le risque n°5 de mon round 1 (`os.execv` depuis un worker avec une run
loop AppKit et un élément de barre de menus vivants) **disparaît** au lieu d'être
assumé ; et le message est honnête — le processus tourne encore sur l'ancien code,
c'est vrai, et on le dit.

Corollaire accepté : la commande `aparte update` **n'existe pas** dans le parser CLI.
Je cesse de la citer ; elle reste à M7 si elle est voulue.

## 4. Les chaînes visibles, au complet (fr / en)

**État** — `Prêt à dicter` / `Ready to dictate` ; `Micro ouvert` / `Microphone open` ;
`Transcription en cours…` / `Transcribing…` ; `La dernière dictée a échoué` /
`The last dictation failed`.

**Raccourci** — les trois lignes du tableau § 1.11.

**Articles** — `Ouvrir Aparté` / `Open Aparté` ; `Copier la dernière dictée` /
`Copy the last dictation` ; `Réglages` / `Settings` ; `Quitter` / `Quit`.

**Mise à jour** — libellés d'article : `Rechercher une mise à jour…` /
`Check for updates…` ; `Vérification…` / `Checking…` ; `Installer la version {v}` /
`Install version {v}` ; `Installation…` / `Installing…`.

Notifications, un état de `check_update` par ligne :

| État | fr | en |
|---|---|---|
| `current` | Aparté {v} est à jour. | Aparté {v} is up to date. |
| `available` | Version {v} disponible. Reclique pour l'installer. | Version {v} available. Click again to install it. |
| `dirty` | Le dossier a des modifications non validées. | The checkout has uncommitted changes. |
| `manual` | Aparté ne tourne pas depuis un dépôt git. | Aparté does not run from a git checkout. |
| `no_upstream` | La branche ne suit aucune branche distante. | The branch tracks no remote branch. |
| `offline` | Impossible de joindre le dépôt distant. | Could not reach the remote. |
| `error` | Lecture du dépôt impossible. | Cannot read the checkout. |
| succès | Mise à jour installée — quitte et relance Aparté. | Update installed — quit and relaunch Aparté. |
| échec | Mise à jour interrompue : {dernière ligne du journal} | Update stopped: {last log line} |
| refus | Une dictée est en cours — réessaie après. | A dictation is in progress — try again after. |

Le minuteur n'est pas une chaîne traduisible (`0:07`). Le titre pendant `processing`
devient `…` — accepté depuis le § 4 de Codex, comme signal non chromatique de
troisième état.

## 5. Le plan ajusté — découpage final

- **M6a — socle testable, zéro natif.** `macos_tray.py` : `LABELS` fr/en,
  `tray_view(...)` pure (icône, titre, ligne d'état, ligne de raccourci),
  `format_elapsed`. `RecordingController` : `_started_at` posé/effacé dans le bon
  ordre, `recording_snapshot()` **sans verrou**, `shutdown(timeout=None)` borné.
- **M6b — cohabitation des boucles.** `MacTray` (liaison rumps mince,
  `quit_button=None`, timer one-shot retenu et arrêté, aucun `signal.signal`),
  `build_tray()` (repli silencieux sur dépendance absente, bruyant sur échec
  inattendu), `serve_macos(url=…, tray_factory=…)`, `run_loop(on_ready, on_quit=None)`,
  démontage sous `RLock`, chaque étape best-effort, `on_ready` qui renonce si le
  démontage a eu lieu, raccrochage à `rumps.events.before_quit` si disponible.
- **M6c — les deux icônes.** SVG monochromes + PNG 40 px commités, régénération
  documentée, test « PNG valide, dimensions justes, aucun pixel coloré ». `/impeccable`.
- **M6d — « Mettre à jour ».** Décision pure par état, deux temps, refus si la dictée
  n'est pas `idle`, **installation sans relance**, `_installed_extras()` élargi, et le
  panneau web qui renvoie à la barre de menus sur macOS.
- **M6e — doc + check `doctor` `tray`.** `CLAUDE.md`, `DESIGN.md`, `CHANGELOG.md`,
  `tasks/todo.md`, `docs/plan-portage-macos-m6.md` (dont la checklist native), retrait
  de `quickmachotkey` de l'extra `macos`.

## 6. Ce qui reste ouvert pour ce round

Une seule chose, et je la pose franchement : **je ne peux vérifier aucune de mes
hypothèses rumps sur cette machine.** Codex a lu le source de la branche `master` sur
GitHub ; la version réellement installée sur le Mac sera celle que `pip` a résolue en
M8. Les deux points où ça compte :

1. `rumps.events.before_quit` — d'où la garde de version.
2. Le comportement de `installMachInterrupt` sur Ctrl-C — d'où le refus d'écrire un
   invariant qui le promette avant de l'avoir vu.

C'est la leçon de M8, appliquée : les faux Linux prouvent notre orchestration, jamais
le comportement de la plateforme.
