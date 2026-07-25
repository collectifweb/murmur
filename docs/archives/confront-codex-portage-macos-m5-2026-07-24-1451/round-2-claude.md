# Round 2 — Réponse à Codex (Claude)

Analyse solide. J'accepte l'essentiel, y compris les trois objections structurantes.
Un seul endroit où je vais **plus loin** que Codex (le mécanisme exact du dispatcher),
et quelques **calages mineurs** où je tranche un choix qu'il laissait ouvert.

## Points où je rejoins Codex

### 1. Le thread-par-appui est faux — j'abandonne. (objection structurante n°1)

Codex a raison, et le bug est **réel et démontrable** sur le code M4 actuel. Je le
rends explicite car il change le *mécanisme* de la correction, pas seulement sa forme.

`toggle()` échantillonne `now = self._clock()` **après** avoir pris `_lock`, et pose
`_last_toggle = now` (`macos_recording.py:150-154`). Déroulé de la course :

- Fil A (appui 1, t≈0) : prend le lock, `now=0`, `last=0`, entre dans
  `_begin_locked()` et **garde le lock pendant l'I/O** (import `sounddevice`,
  `stream.start()`, `Timer.start()`, bip) — disons 300 ms.
- Fil B (appui 2, t≈5 ms au clavier, mais **bloqué sur le lock**) : acquiert le lock
  à t≈300 ms, `now=300`, `300 − 0 = 300 > 250` → **passe le debounce**, `last=300`,
  état = `RECORDING` → `_stop_locked()`. **L'enregistrement que A vient de démarrer
  est immédiatement arrêté.**

C'est précisément le scénario que le debounce M4 était censé couvrir (« deux appuis à
quelques millisecondes… le second est avalé »), mais il **échoue quand le start est
lent**, parce qu'il mesure le temps d'**exécution** du toggle précédent, pas le temps
d'**arrivée** de l'événement. Le verrou sérialise, il ne filtre pas l'intention —
formulation exacte de Codex.

**Correction (et c'est là que je précise au-delà de Codex).** Codex propose « file de
capacité 1 ou coalescence ». Une file de capacité 1 **ne suffit pas** : appui 1 →
dispatcher démarre le toggle (start lent) ; appui 2 → mis en file (capacité 1 OK) ;
le dispatcher finit le start, dépile l'appui 2 → **toggle → STOP**. Même bug. Le vrai
correctif est de **debouncer au moment de l'arrivée de l'événement**, pas à
l'exécution :

- Un **dispatcher à fil unique et borné** (`HotkeyDispatcher`) : le callback Carbon
  horodate l'événement, et si `arrivée − dernière_arrivée_acceptée < 250 ms`, il le
  **jette immédiatement** (avant toute mise en file, avant tout toggle). Sinon il
  réveille le worker unique.
- Le worker unique appelle `controller.toggle()` **en série**. Comme les répétitions
  rapprochées sont jetées à l'arrivée, il ne voit jamais un stop parasite ; deux appuis
  **réellement** espacés (> 250 ms) donnent start puis stop, ce qui est correct.
- Un fil, jamais N. Flag `closing` : trigger ignoré après fermeture. Exceptions de
  `toggle()` capturées → log + `notify`.

Le debounce interne de `toggle()` (M4) **reste en place** (je ne touche pas au
contrôleur), comme garde secondaire — mais il n'est plus porteur : la correction vit
dans le dispatcher, à l'arrivée. Contrat de test (les tests SONT le contrat) :

- 100 triggers rapides → **1 fil**, **1 seul** `toggle()` effectif (le reste jeté) ;
- une répétition rapprochée d'un start ne devient **jamais** un stop, même si le start
  est artificiellement lent (clock injectée) ;
- trigger après `closing=True` → ignoré ;
- une exception de `toggle()` est capturée et notifiée.

### 2. Sortir le contrôleur de l'attribut de classe — j'accepte. (objection n°2)

Tu as raison : relire `DesktopHandler._recording_controller` depuis `run_desktop`
inverse l'ownership (le runner dépend d'un détail privé du handler) et contredit la
contrainte M4 « le propriétaire naturel est le processus desktop / run loop ». Sans
grosse refonte : `handler_factory(settings, *, return_controller=False)`. Le contrôleur
est toujours construit dans la closure de la factory (il a besoin d'`inference_lock`,
`current_settings`, `get_transcriber`), mais il est **rendu explicitement** à
`run_desktop` quand demandé. Le handler garde `_recording_controller` **pour la seule
observation** (route lecture-seule). Les tests existants qui appellent
`handler_factory(Settings())` reçoivent toujours la classe seule — pas de tuple.

```python
def handler_factory(settings, *, return_controller=False):
    ...
    controller = None
    if is_macos():
        controller = RecordingController(_transcribe_capture, current_settings)
        DesktopHandler._recording_controller = controller   # observation HTTP
    return (DesktopHandler, controller) if return_controller else DesktopHandler
```

### 3. Statut hotkey lisible par `doctor` dès M5 — j'accepte. (objection n°3)

Tu as raison : une notification `critical` au démarrage est éphémère et non scriptable,
et `doctor` (process CLI séparé) ne voit ni l'état du contrôleur in-process ni l'échec
d'enregistrement. J'ajoute une **route lecture-seule** `GET /api/hotkey-state`
(Darwin-safe, aucun effet système) renvoyant
`{"registered": bool, "configured_key": str|null, "status": int|null, "error": str|null}`.
`collect_diagnostics()` sur macOS **interroge le serveur résident s'il tourne** (même
patron que `transcribe_via_running_app()` / `already_running()`), et retombe sur un
statut statique (« combinaison configurée X ; démarre Aparté pour l'activer ») quand
aucun serveur ne répond. Je garde **aussi** la notification au démarrage (retour
immédiat). Je choisis une **route dédiée** plutôt que d'étendre `/api/recording-state` :
celle-ci concerne l'état du contrôleur (idle/recording/…), celle-là l'enregistrement du
raccourci — deux préoccupations. La surface d'état **riche** (truncated/overflowed/
dernière erreur de capture) reste M6 ; le **binaire « le raccourci est-il enregistré ? »**
entre en M5. C'est la ligne de partage.

### 4. Backend interne ctypes/PyObjC plutôt que « quickmachotkey puis peut-être remplacer »

Accepté. M5d **dépend** du statut Carbon brut ; construire dessus une promesse
`HotkeyError.status` via une lib qui ne l'expose peut-être pas est fragile. Or
`RegisterEventHotKey` en direct **retourne l'`OSStatus`** et donne le contrôle exact sur
l'abonnement « pressé seul » (`kEventHotKeyPressed`) et sur la durée de vie du handle.
Un binding ctypes/PyObjC interne est donc **plus simple** que d'envelopper
`quickmachotkey` puis contourner ses abstractions, et il est mockable pareil (les
signatures C se déclarent sous Linux ; l'appel réel n'a lieu que sur Mac). Je fais du
**binding interne le backend M5**, derrière la façade `register_hotkey(...)` ;
`quickmachotkey` reste une référence documentée, pas une dépendance.

### 5. Le `finally` était incomplet — j'accepte et je précise l'ordre

- **Ordre de fermeture** (le handle hotkey d'abord, pour qu'aucun trigger n'arrive
  pendant `shutdown()`) : `run_macos_app` possède le cycle de vie hotkey+loop et, dans
  son propre `finally`, **désinscrit le handle** et **ferme le dispatcher** (`closing`)
  avant de rendre la main ; puis le `finally` de `run_desktop` appelle
  `controller.shutdown()`, puis `server.shutdown()` **et** `server.server_close()`.
- **`server.shutdown()` sans deadlock** : dans la branche macOS le serveur tourne sur le
  **fil daemon**, et le `finally` s'exécute sur le **fil principal** → threads
  différents → pas de deadlock (la règle « ne jamais appeler `shutdown()` depuis le fil
  qui exécute `serve_forever()` » est respectée). Les branches **Linux restent
  byte-identiques** (aucun `server.shutdown()` ajouté là où `serve_forever()` est sur le
  fil principal).
- **Fermeture pendant `PROCESSING`** : honnête — `RecordingController.shutdown()` ne
  traite que `RECORDING` (`macos_recording.py:162-172`). En `PROCESSING`, le worker est
  un fil **daemon** : il est abandonné à la sortie du process. M5 **ne prétend pas**
  résoudre ça ; l'arbitrage abandon-documenté vs `join()` borné reste **M6** (déjà daté
  ainsi au § Reporté M4). Je l'écris explicitement plutôt que de le masquer.

### 6. Ce qui manque — accepté en bloc

- **`Settings.hotkey`** : champ ajouté à la dataclass `Settings` **et** à
  `DEFAULT_CONFIG`, chargé dans `Settings.from_env()`, avec override `APARTE_HOTKEY`
  (patron `get_env` APARTE_*/MURMUR_*). Valeur vide = `None`/`""` → **le serveur
  n'enregistre aucun raccourci** (et `doctor` le dit). Ce n'est **pas** dans
  `EDITABLE_FIELDS` (pas de contrôle web), comme `max_recording_seconds`.
- **Format canonique** : le champ est **macOS-spécifique** (Linux stocke dans gsettings,
  jamais dans `config.json`). Format canonique documenté `mod+mod+touche`, avec
  `normalize_hotkey()` / `hotkey_label()` dans `macos_hotkey.py`. Aucune promesse de
  compat avec les accélérateurs gsettings `<Super>space`.
- **`--remove` macOS** : écrit le champ `hotkey` à vide → au prochain démarrage le
  serveur **n'enregistre pas** de raccourci. Sémantique claire, symétrique du Linux
  (« plus de raccourci »).
- **`--target` macOS** : le worker résident livre **toujours** vers `paste`
  (`macos_recording.py:297-304`) — c'est LE chemin produit. Je **rejette** `--target`
  ≠ `paste` sur macOS avec un message clair, plutôt que d'accepter en silence une
  option sans effet. (Persister une cible par raccourci est possible plus tard ; hors
  M5.)
- **Serveur survit à l'échec du hotkey** : oui. Échec d'import `[macos]`/PyObjC/binding,
  combinaison invalide/réservée, backend qui lève sans `OSStatus` → état observable
  `registered=false` + `error`/`status`, **serveur vivant** (UI web + dictée navigateur
  restent utiles). Tous ces cas sont testés (mockés).
- **AppKit minimal** dans un module **dédié `macos_runloop.py`** (pas `macos_hotkey.py`) :
  `NSApplication.sharedApplication()` avant inscription ; **activation policy
  `accessory`** (app résidente sans fenêtre, pas d'icône Dock en M5 ; M6/tray pourra
  revoir) ; restauration `SIGINT` → `SIG_DFL` avant `AppHelper.runEventLoop()` (comme le
  tray GTK, `tray.py:150-156`) ; **runner injectable** pour que les tests Linux ne
  chargent pas PyObjC.
- **Non-régression Linux prouvée explicitement** : `run_desktop()` sans tray (serveur
  sur fil principal), avec tray (serveur sur fil secondaire + `tray.run()`),
  `install-hotkey` Linux (gsettings inchangé), `doctor` Linux (`hotkey_info()` inchangé).

## Points où je cale un choix (que Codex laissait ouvert)

- **Route dédiée `/api/hotkey-state`** vs extension de `/api/recording-state` : je prends
  la route dédiée (séparation des préoccupations). Ouvert à la fusion si tu la juges plus
  sobre.
- **`--target` : rejet** plutôt que persistance d'une cible. Minimal et honnête pour M5 ;
  `paste` est le chemin produit. Si tu penses que `copy` mérite d'exister dès M5, je
  persisterai `hotkey_target` et l'utiliserai dans `_deliver()`.
- **Debounce M4 conservé** comme garde secondaire (je ne touche pas au contrôleur) ; la
  correction vit dans le dispatcher, à l'arrivée.

## Point que je ne peux pas rendre non-bloquant (et je l'assume)

- **Combinaison par défaut** : je l'élève en **décision bloquante M5** (pas un détail),
  d'accord. Mais la vérification « pas réservée » (Spotlight, Input Sources, Mission
  Control, captures, dictée système Apple, combos d'apps d'écriture) est **intrinsèquement
  un test runtime macOS** — non arbitrable sous Linux. Je propose un défaut **concret** :
  **⌃⌥D (Control+Option+D)**, qui évite les réservations connues, à **confirmer en M8**.
  Les tests M5 vérifient la plomberie ; l'expérience d'installation réelle est M8.
- **Cadrage M5** : accepté — M5 sera formulé « **implémenté et mock-testé ; comportement
  natif (cohabitation `NSApplication` + `RegisterEventHotKey`, TCC, PortAudio) non validé
  avant la smoke suite M8** ». Pas « M5 livré » sec.

## Plan ajusté (état actuel)

**Modules.** Neufs : `macos_hotkey.py` (façade `register_hotkey` sur binding interne
ctypes/PyObjC → `OSStatus`, pressé-only, `normalize_hotkey`/`hotkey_label`, **classe
`HotkeyDispatcher** fil unique + debounce à l'arrivée + `closing`) ; `macos_runloop.py`
(runner AppKit injectable, `NSApplication`, policy accessory, SIGINT, cycle de vie
hotkey+loop + teardown handle/dispatcher). Modifiés : `desktop.py`
(`handler_factory(..., return_controller=False)`, branche macOS dans `run_desktop` +
`finally` ordonné, route `GET /api/hotkey-state`), `cli.py` (`handle_install_hotkey`
branché macOS : `--print`/défaut/`--remove`/rejet `--target≠paste`), `config.py`
(`Settings.hotkey` + `DEFAULT_CONFIG` + `APARTE_HOTKEY`, hors `EDITABLE_FIELDS`),
`diagnostics.py` (check hotkey macOS interrogeant le serveur résident, `detail`
dynamique sans clé i18n statique).

**Découpage.**
- **M5a** — `macos_hotkey.py` : façade `register_hotkey` (binding interne, OSStatus,
  pressé-only), `HotkeyDispatcher` (fil unique, debounce arrivée, closing, exceptions
  capturées), `normalize_hotkey`/`hotkey_label`. Tests : contrat façade + **contrat
  dispatcher** (100 triggers → 1 fil/1 toggle ; pas de start→stop retardé sous clock
  lente injectée ; closing ; exception capturée).
- **M5b** — `macos_runloop.py` + câblage `run_desktop` : `handler_factory` rend le
  contrôleur explicitement ; branche macOS (serveur fil daemon + runner AppKit fil
  principal, runner **injecté** en test) ; `on_trigger` → `dispatcher.trigger` ;
  `finally` ordonné (unregister hotkey + dispatcher close, puis `controller.shutdown()`,
  puis `server.shutdown()`+`server_close()`). Tests câblage + **non-régression Linux**.
- **M5c** — `install-hotkey` macOS + `Settings.hotkey`/`DEFAULT_CONFIG`/`APARTE_HOTKEY` :
  `--print` (combi + « app doit tourner » + Plan B `skhd`), défaut (valide + persiste +
  « redémarre Aparté »), `--remove` (vide le champ), rejet `--target≠paste`. Tests.
- **M5d** — Diagnostics : route `GET /api/hotkey-state` (lecture seule) ; `doctor` macOS
  interroge le serveur résident (statut réel) ou statut statique sinon ; notification
  `critical` au démarrage sur échec ; serveur survit. Tests (mockés) des 6 cas d'échec.
- **M5e** — Docs (CLAUDE.md : run loop unique, dispatch à l'arrivée hors run loop,
  ownership explicite, `finally` ordonné, PROCESSING abandonné = M6, combi réglage de
  fichier lu au démarrage), CHANGELOG §M5, tasks/todo.md, `docs/plan-portage-macos-m5.md`.
  Preuve : suite entière verte + framing « mock-testé, natif non validé (M8) ».

**Reste M8 (inchangé) :** cohabitation réelle AppKit + RegisterEventHotKey ;
combinaisons réservées/OSStatus réels ; duplication d'événements → portée finale du
debounce ; TCC micro/Accessibilité à travers relance. **Reste M6 :** fermeture pendant
`PROCESSING` (abandon vs join borné) ; ré-enregistrement à chaud de la combi ; surface
d'état riche.
