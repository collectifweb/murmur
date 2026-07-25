# Plan : M5 — Raccourci global macOS + run loop AppKit (Aparté, portage macOS)

Consensus atteint après contre-expertise `/confront-codex` (2 rounds, archivés dans
`docs/archives/confront-codex-portage-macos-m5-2026-07-24-1451/`).

## Contexte

Sur macOS, l'enregistrement vit **en mémoire du serveur résident**
(`RecordingController`, `src/aparte/macos_recording.py`), livré et durci en M4. Il est
aujourd'hui **dormant** : rien ne l'appelle. M5 lui donne son vrai déclencheur — un
**raccourci clavier global** (`RegisterEventHotKey`, API Carbon) qui, à chaque appui,
appelle `controller.toggle()` **en in-process**, sans passer par aucune route HTTP
(invariant Darwin M3 : aucune route POST à effet système sur macOS).

Deux exigences techniques encadrent le lot :

1. **Une seule run loop AppKit sur le fil principal.** `RegisterEventHotKey` n'existe que
   si une run loop vivante peut lui livrer ses événements. Le serveur HTTP passe sur un
   fil secondaire (comme le fait déjà le tray GTK sur Linux).
2. **Le raccourci ne bloque jamais la run loop.** `toggle()` garde son verrou pendant de
   l'I/O (import `sounddevice`, `stream.start()`, `Timer.start()`, bips). Le callback
   Carbon doit donc **répartir hors run loop**, et **filtrer les répétitions à l'arrivée**
   de l'événement, avant tout appel à `toggle()`.

La machine de dev est sous **Linux** : PyObjC / Carbon / PortAudio n'y sont pas
testables. **M5 est implémenté et prouvé par tests mockés ; le comportement natif
(cohabitation `NSApplication` + `RegisterEventHotKey`, TCC, PortAudio, OSStatus réels)
n'est pas validé avant la smoke suite manuelle M8.** Cette formulation est le cadrage
honnête du lot, pas un détail.

## Approche

Découpage en 5 sous-lots, chacun prouvé sous Linux par mocks. Tout le neuf est sous
`is_macos()` ou dans des modules `macos_*` ; **le chemin Linux reste byte-identique**.
Les imports PyObjC/AppKit/Carbon réels restent **paresseux**, confinés au runner natif,
pour que les modules restent importables et testables sous Linux.

### Modules

**Neufs :**

- `src/aparte/macos_hotkey.py` — façade + répartiteur :
  - `register_hotkey(key_spec, on_trigger, *, backend=…) -> HotkeyHandle` : backend =
    **binding interne ctypes/PyObjC** sur `RegisterEventHotKey` (retourne l'`OSStatus`
    brut), abonné **au seul événement « pressé »** (`kEventHotKeyPressed`), conserve et
    libère explicitement le handle. Lève `HotkeyError` **portant l'`OSStatus`** sur échec.
    Le backend est **injecté** pour les tests. `quickmachotkey` reste une référence
    documentée, **pas** une dépendance.
  - `HotkeyDispatcher` : **fil worker unique et borné**, avec **debounce à l'arrivée**
    (voir « Le répartiteur » ci-dessous).
  - `normalize_hotkey()` / `hotkey_label()` : format canonique macOS `mod+mod+touche`,
    distinct des accélérateurs gsettings Linux (`<Super>space`).
- `src/aparte/macos_runloop.py` — runner AppKit **injectable** :
  `NSApplication.sharedApplication()` avant inscription du hotkey, **activation policy
  `accessory`** (app résidente sans fenêtre, pas d'icône Dock en M5), restauration
  `SIGINT → SIG_DFL` avant `AppHelper.runEventLoop()` (comme le tray GTK,
  `tray.py:150-156`). Possède le **cycle de vie hotkey + run loop** et son teardown.

**Modifiés :**

- `src/aparte/desktop.py` — `handler_factory(settings, *, return_controller=False)` ;
  branche macOS dans `run_desktop()` + `finally` ordonné ; route lecture-seule
  `GET /api/hotkey-state`.
- `src/aparte/cli.py` — `handle_install_hotkey` branché macOS.
- `src/aparte/config.py` — `Settings.hotkey` + `DEFAULT_CONFIG` + override `APARTE_HOTKEY`,
  **hors `EDITABLE_FIELDS`**.
- `src/aparte/diagnostics.py` — check hotkey macOS.

### Le répartiteur (`HotkeyDispatcher`) — cœur de la correction

Le problème que ça résout : un « fil par appui » est faux. `toggle()` échantillonne le
temps **après** avoir pris son verrou et le garde pendant l'I/O de démarrage. Deux appuis
rapprochés (double-tap, répétition) peuvent alors s'empiler en fils bloqués ; quand le
second acquiert le verrou après un start lent, plus de 250 ms se sont écoulées, il passe
le debounce interne, l'état est `RECORDING`, et il **arrête l'enregistrement que le
premier vient de démarrer**. Le verrou sérialise, il ne filtre pas l'intention. Une file
de capacité 1 ne corrige pas ça : le second événement mis en file est quand même exécuté
après le start et devient un STOP.

Correction — **filtrer à l'arrivée**, pas à l'exécution :

- Le callback Carbon appelle `dispatcher.trigger()`.
- `trigger()` prend le temps **monotone sous le verrou interne du dispatcher**, décide
  **accepte/rejette** (`arrivée − dernière_arrivée_acceptée < 250 ms` → jeté) **là**, et
  ne réveille le worker **que si accepté**.
- Un **worker unique** appelle `controller.toggle()` **en série**. Il ne recalcule
  **jamais** le debounce sur son heure d'exécution.
- Flag `closing` : trigger ignoré après fermeture. Exceptions de `toggle()` capturées →
  log + `notify`.
- `dispatcher.close()` : pose `closing=True` **puis fait un `join()` borné du worker
  actif**, pour garantir qu'aucun `toggle()` n'est encore en cours avant que
  `controller.shutdown()` ne commence.

Le debounce interne de `toggle()` (M4) **reste en place** (le contrôleur n'est pas
touché) comme garde secondaire ; il n'est plus le mécanisme porteur du raccourci.

### Propriété explicite du contrôleur

`handler_factory(settings, *, return_controller=False)`. Le contrôleur est construit dans
la closure de la factory (il a besoin d'`inference_lock`, `current_settings`,
`get_transcriber`), mais **rendu explicitement** à `run_desktop()` quand demandé. Le
handler garde `_recording_controller` **pour la seule observation** (route lecture-seule).
`run_desktop()` **possède** le contrôleur : il câble le trigger et appelle `shutdown()`.
Sur Linux, `handler_factory(settings)` reste strictement compatible, et
`handler_factory(settings, return_controller=True)` rend `(HandlerClass, None)` **sans**
importer de pièces natives.

### Branche macOS de `run_desktop()` + `finally` ordonné

Sur Mac, `build_tray()` rend déjà `None` (GTK absent). Une **branche macOS insérée avant
la branche tray** : serveur sur **fil daemon**, runner AppKit sur le **fil principal**.
Le runner (injecté en test) crée le dispatcher, enregistre le hotkey
(`on_trigger = dispatcher.trigger`), lance la run loop.

Fermeture, dans l'ordre (le handle hotkey d'abord, pour qu'aucun trigger n'arrive pendant
`shutdown()`) :

1. **désinscrire le handle hotkey** (plus de callback) ;
2. **`dispatcher.close()`** (closing + `join()` borné du worker) ;
3. **`controller.shutdown()`** (discard propre d'une capture `RECORDING`) ;
4. **`server.shutdown()` puis `server.server_close()`**.

`server.shutdown()` est sûr ici : le serveur tourne sur le fil daemon, le `finally`
s'exécute sur le fil principal → threads différents, pas de deadlock. **Les branches
Linux restent byte-identiques** (aucun `server.shutdown()` ajouté là où `serve_forever()`
est sur le fil principal).

**Fermeture pendant `PROCESSING`** : `RecordingController.shutdown()` ne traite que
`RECORDING`. En `PROCESSING`, le worker est un fil **daemon**, abandonné à la sortie du
process. M5 **ne prétend pas** résoudre ça ; l'arbitrage abandon-documenté vs `join()`
borné reste **M6**.

### Réglage de la combinaison

`Settings.hotkey` (str | None), ajouté à la dataclass `Settings`, à `DEFAULT_CONFIG`,
chargé dans `Settings.from_env()` avec override `APARTE_HOTKEY` (patron `get_env`
APARTE_*/MURMUR_*). **Hors `EDITABLE_FIELDS`** (pas de contrôle web ; réglage de fichier,
comme `max_recording_seconds`). Valeur **vide = aucun raccourci enregistré** (le serveur
n'appelle pas `register_hotkey`, et `doctor` le dit). Champ **macOS-spécifique** : Linux
stocke son raccourci dans gsettings, jamais dans `config.json`. Lu **au démarrage** de la
run loop : changer la combinaison demande un **redémarrage** de l'app en M5
(ré-enregistrement à chaud = M6).

### Diagnostics d'échec de combinaison

- **Route lecture-seule** `GET /api/hotkey-state` (Darwin-safe, aucun effet système),
  schéma `{"registered": bool, "configured_key": str|null, "status": int|null,
  "error": str|null}`.
- `collect_diagnostics()` sur macOS obtient le statut hotkey **réel** :
  - servi **dans** le serveur résident → le handler passe l'état hotkey **qu'il possède
    déjà** à `collect_diagnostics()` (pas d'auto-requête HTTP) ;
  - `aparte doctor` en **process CLI séparé** → auto-requête **bornée, court timeout**
    vers un serveur qui tourne (patron `already_running()`), repli **statique** propre
    si personne ne répond (« combinaison configurée X ; démarre Aparté pour l'activer »).
  - `detail` **dynamique, sans clé i18n statique** (invariant : une clé statique
    écraserait un détail variable ; cf. le check `config`), libellé neutre.
- **Serveur survit à l'échec du hotkey** : import `[macos]`/PyObjC/binding absent,
  combinaison invalide/réservée, backend qui lève sans `OSStatus` → état observable
  `registered=false` + `error`/`status`, **serveur vivant** (UI web + dictée navigateur
  restent utiles). Notification `critical` au démarrage sur échec (retour immédiat), qui
  **complète** la route, sans en être la seule preuve.

### `install-hotkey` sur macOS

`handle_install_hotkey` branche sur `is_macos()` :

- `--print` : montre la combinaison + « actif uniquement quand Aparté tourne » + Plan B
  documenté (`skhd`, non intégré) ;
- défaut : **valide** la combinaison (`normalize_hotkey`), l'**écrit** dans `config.json`,
  indique qu'elle est prise en compte au **(re)démarrage** de l'app ;
- `--remove` : **vide** le champ `hotkey` → au prochain démarrage, aucun raccourci
  enregistré ;
- `--target` ≠ `paste` : **rejeté** avec un message clair (le worker résident livre
  toujours vers `paste`, `macos_recording.py:297-304` ; accepter `copy`/`stdout` serait
  trompeur). Réouvrable plus tard si `copy` devient un vrai mode produit.

## Étapes d'implémentation

- **M5a — `macos_hotkey.py`** : façade `register_hotkey` (binding interne, `OSStatus`,
  pressé-only, handle explicite), `HotkeyDispatcher` (fil unique, debounce arrivée sous
  verrou, `closing`, `close()` avec join borné, exceptions capturées),
  `normalize_hotkey`/`hotkey_label`.
  *Tests* : contrat façade (succès → handle ; OSStatus ≠ 0 → `HotkeyError.status` ;
  pressé-only ; parse valide / rejet invalide) ; **contrat dispatcher** (100 triggers →
  1 fil et 1 seul `toggle()` ; répétition rapprochée ≠ stop retardé, avec clock lente
  injectée ; trigger après `closing` ignoré ; exception capturée ; `close()` joint le
  worker en cours avant de rendre).
- **M5b — `macos_runloop.py` + câblage `run_desktop`** : `handler_factory(...,
  return_controller=…)` ; branche macOS (serveur fil daemon + runner AppKit injecté) ;
  `finally` ordonné (unregister hotkey → `dispatcher.close()` → `controller.shutdown()` →
  `server.shutdown()`+`server_close()`).
  *Tests* : câblage (raccourci enregistré avec la combinaison configurée, trigger →
  `controller.toggle` hors du fil appelant, teardown ordonné, `toggle()` en cours terminé
  avant `shutdown()`) ; **non-régression Linux** (`run_desktop` sans tray = serveur sur
  fil principal ; avec tray = fil secondaire + `tray.run()` ;
  `handler_factory(settings)` compat).
- **M5c — `install-hotkey` macOS + `Settings.hotkey`** : `Settings.hotkey` +
  `DEFAULT_CONFIG` + `APARTE_HOTKEY` ; `handle_install_hotkey` macOS (`--print`, défaut,
  `--remove`, rejet `--target≠paste`).
  *Tests* : dispatch mac, `--print`, persistance + validation, `--remove` vide le champ,
  rejet `--target≠paste` ; **non-régression** `install-hotkey` Linux (gsettings inchangé).
- **M5d — Diagnostics** : route `GET /api/hotkey-state` ; `collect_diagnostics()` macOS
  (état passé par le handler in-process ; sinon auto-requête bornée ; sinon repli
  statique) ; notification `critical` au démarrage sur échec.
  *Tests* (mockés) : présence de l'entrée mac, `detail` dynamique, les 6 cas d'échec,
  serveur survit ; **non-régression** `doctor` Linux (`hotkey_info()` inchangé).
- **M5e — Docs + preuve** : `CLAUDE.md` (invariants ci-dessous), `CHANGELOG.md` §M5,
  `tasks/todo.md` §M5. Suite entière verte :
  `PYTHONPATH=src python3 -m unittest discover -s tests -t tests`.

## Points de vigilance

- **Importabilité Linux stricte** : imports PyObjC/AppKit/Carbon **paresseux**, confinés
  au runner natif. Parsing, dispatcher, types d'erreur testés sous Linux.
- **Debounce à l'arrivée, pas à l'exécution** : horodatage sous le verrou du dispatcher,
  décision avant de réveiller le worker ; le worker ne recalcule jamais le debounce.
- **`close()` avec join borné** avant `controller.shutdown()` : ferme la course
  résiduelle « toggle accepté encore en cours pendant le shutdown ».
- **`server.shutdown()` uniquement dans la branche macOS** (fil secondaire) ; jamais
  dans une branche Linux où `serve_forever()` est sur le fil principal.
- **`doctor` sans auto-requête fragile** quand il est servi par le résident : passer
  l'état déjà possédé à `collect_diagnostics()`.
- **`Settings.hotkey` vide = pas de raccourci** : le serveur n'enregistre rien, `doctor`
  l'affiche ; format canonique macOS distinct des accélérateurs gsettings.
- **Cadrage M5** : « implémenté et mock-testé ; natif non validé avant M8 ».

## Décisions explicitement écartées

- **Un fil daemon par appui** — bug de correction (double-tap → arrêt du start lent) ;
  remplacé par le dispatcher borné à debounce d'arrivée.
- **File de capacité 1 seule** — n'empêche pas un second événement d'être exécuté après
  le start et de devenir un STOP ; le filtrage doit être à l'arrivée.
- **Relire `DesktopHandler._recording_controller` depuis `run_desktop`** — inverse
  l'ownership (le runner dépend d'un détail privé du handler) ; remplacé par le retour
  explicite de `handler_factory`.
- **`quickmachotkey` comme backend M5** — ne garantit pas l'accès à l'`OSStatus` brut ;
  binding interne ctypes/PyObjC direct, plus simple et exact.
- **Étendre `/api/recording-state`** — préoccupations distinctes (état contrôleur vs
  enregistrement du raccourci) ; route dédiée `/api/hotkey-state`.
- **Notification au démarrage comme seule preuve d'échec** — éphémère, non scriptable ;
  complétée par la route lecture-seule que `doctor` lit.
- **Accepter `--target copy/stdout` sur macOS** — le worker résident livre vers `paste` ;
  l'accepter en silence serait trompeur → rejet clair.
- **Route HTTP de bascule** — interdit par l'invariant Darwin M3 (proxy de privilèges).
- **Event tap `CGEventTap`/`pynput`** — demande « Surveillance de l'entrée » ;
  `RegisterEventHotKey` n'en demande aucune.
- **Ré-enregistrement à chaud de la combinaison / fermeture pendant `PROCESSING` /
  surface d'état riche** — datés **M6**. **Validation native / confirmation `⌃⌥D` /
  duplication d'événements / TCC / PortAudio réel** — datés **M8**.

## Combinaison par défaut

**⌃⌥D (Control+Option+D)** en M5, **à confirmer en M8**. Évite les réservations connues
(`Cmd+Espace` Spotlight ; `Ctrl+Espace` / `Ctrl+Option+Espace` sources de saisie ; `Fn-D`
dictée système Apple ; `Maj+Cmd+3/4/5` captures) ; mnémonique pour « dictée » ; évite
`Cmd`, souvent chargé dans les apps. La vérification « pas réservée » est intrinsèquement
runtime macOS (M8) ; un échec d'enregistrement sera **observable** via
`/api/hotkey-state` et `doctor`, et l'utilisateur peut changer/supprimer par fichier/CLI.

## Invariants à écrire dans `CLAUDE.md`

- Une seule run loop AppKit sur le fil principal ; serveur HTTP sur fil secondaire.
- Le raccourci répartit **hors run loop** et **debounce à l'arrivée** de l'événement,
  jamais à l'exécution ; worker unique, jamais un fil par appui.
- `run_desktop()` **possède** le contrôleur (rendu par `handler_factory`) ; le handler
  HTTP ne fait qu'**observer**.
- `finally` ordonné : unregister hotkey → `dispatcher.close()` (join borné) →
  `controller.shutdown()` → `server.shutdown()`+`server_close()`. `server.shutdown()`
  **jamais** dans une branche Linux fil-principal.
- Le raccourci macOS **exige que l'app tourne** (prérequis utilisateur, signalé par
  `doctor` et la doc).
- `Settings.hotkey` = réglage de fichier lu **au démarrage** (redémarrage pour changer
  en M5), hors `EDITABLE_FIELDS` ; vide = aucun raccourci.
- Aucune route POST à effet système sur Darwin (rappel M3) ; `/api/hotkey-state` est
  lecture seule.
