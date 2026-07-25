# Round 1 — Plan M5 (Claude)

## Contexte

Aparté est une application de dictée vocale **Linux d'abord, français d'abord**,
Python 3.10+, sans framework (`src/aparte/`). Un portage macOS est mené comme
**compagnon** (« Aparté tourne aussi sur Mac »), jamais un pivot ; le code Linux
existant et testé ne doit **pas** être déstabilisé. Les lots M0–M4 sont livrés,
prouvés et poussés sur `feat/portage-macos`.

**M4** a livré le `RecordingController` (`src/aparte/macos_recording.py`) :
l'enregistrement macOS vit **en mémoire du serveur résident** (pas de sous-processus,
pas de fichier de session, pas de `/proc` — contrairement à Linux/`session.py`).
Le contrôleur est aujourd'hui **dormant** : rien ne l'appelle. Il a été durci
(contre-expertise M4) : capsule `_Capture` par capture + callback en fermeture,
bip avant `stream.start()`, polissage dans le worker via `polish_for_delivery`,
stop robuste (jamais d'état `PROCESSING` collé), fermeture du stream sur erreur de
start.

**M5 donne au contrôleur son vrai déclencheur** : un raccourci clavier global
(`RegisterEventHotKey`, API Carbon) qui, à chaque appui, appelle
`controller.toggle()` **en in-process**, sans passer par aucune route HTTP
(invariant Darwin M3 : aucune route POST à effet système sur macOS).

La machine de dev est sous **Linux** : PyObjC / Carbon / PortAudio ne sont pas
testables ici. Tout M5 est prouvé par **tests mockés** ; l'effet réel sur un vrai
Mac est renvoyé à **M8** (smoke suite manuelle).

### État du code pertinent (à vérifier dans le workspace)

- `src/aparte/desktop.py::run_desktop` (l.78-107) : construit le
  `ThreadingHTTPServer`, appelle `build_tray(...)` ; si `tray is None` →
  `server.serve_forever()` sur le fil principal, sinon serveur sur fil daemon +
  `tray.run()` (GTK possède le fil principal). `finally: server.server_close()`.
- `src/aparte/desktop.py::handler_factory` (l.190-505) : referme
  `inference_lock`, `current_settings`, `get_transcriber`. Sur `is_macos()`
  (l.492-503), construit le `RecordingController` et l'attache en **attribut de
  classe** `DesktopHandler._recording_controller`. La route lecture-seule
  `GET /api/recording-state` (l.273-282) lit `controller.state`.
- `src/aparte/tray.py::build_tray` : rend `None` si PyGObject/AppIndicator absents
  (donc **None sur Mac** : GTK indisponible). `Tray.run()` installe SIGINT par
  défaut puis `Gtk.main()`.
- `src/aparte/hotkey.py` : la **façade Linux** (gsettings/Cinnamon/GNOME).
  `install_hotkey()`, `remove_hotkey()`, `hotkey_info()`, `HotkeyUnsupported` avec
  `.instructions()` (repli manuel imprimable). Patron à refléter côté mac.
- `src/aparte/cli.py::handle_install_hotkey` (l.490-511) : dispatch de la commande
  `install-hotkey` (`--print`, `--remove`, défaut).
- `src/aparte/macos_recording.py::RecordingController.toggle()` : sous `_lock`,
  applique un debounce de 250 ms, puis `_begin_locked()` / `_stop_locked()` /
  `_notify_busy()`. `toggle()` **garde `_lock` pendant de l'I/O** (import
  `sounddevice`, `stream.start()`, `Timer.start()`, bips). `shutdown()` fait un
  discard propre (stop+close, pas de transcription à l'arrachée).

### Les 4 contraintes datées M5 (consensus M4, § Reporté de `docs/plan-portage-macos-m4-durcissement.md`)

1. **`toggle()` tient le lock pendant de l'I/O** → le callback Carbon/AppKit doit
   **dispatcher hors run loop** avant d'appeler `toggle()`, sinon il bloque la run loop.
2. **Référence explicite au contrôleur** : le propriétaire naturel est le processus
   desktop / run loop. M5 garde une référence explicite dans `run_desktop()` et la
   passe au hotkey ; le handler HTTP ne fait qu'observer.
3. **Câbler `shutdown()`** : `run_desktop()` doit appeler `shutdown()` au shutdown
   applicatif (aujourd'hui son `finally` ne fait que `server_close()`).
4. **Sémantique du debounce** : garder le 250 ms global ; le restreindre à
   `IDLE/ERROR → RECORDING` se décide **après** avoir observé si
   `RegisterEventHotKey` duplique les événements (M8).

## Approche proposée

Découpage en 5 sous-lots, chacun prouvé sous Linux par mocks. Tout le neuf est sous
`is_macos()` ou dans des modules `macos_*` ; le chemin Linux reste byte-identique.

### M5a — Façade `macos_hotkey.py`
Nouveau module, patron de `hotkey.py`.
- `register_hotkey(key_spec, on_trigger, *, backend=…) -> HotkeyHandle` : abonné
  **au seul événement « pressé »** (`kEventHotKeyPressed`), retourne un handle ou
  lève `HotkeyError` **portant l'`OSStatus`** (combinaison réservée / déjà prise).
- Backend réel = adaptateur mince sur `quickmachotkey` (PyPI 2025.7.28), **injecté**
  pour les tests. S'il ne donne pas assez de contrôle sur les conflits, on le
  remplace par un binding ctypes/PyObjC interne **sans changer les appelants**.
- Parsing/validation d'une combinaison normalisée (`mod+mod+touche` → keycode + masque).
- Tests (`tests/test_macos_hotkey.py`) : succès → handle ; backend OSStatus ≠ 0 →
  `HotkeyError` avec le status ; abonnement pressé-only ; parse valide / rejet invalide.

### M5b — Run loop AppKit unique + câblage `run_desktop`
Modifie `desktop.py::run_desktop`.
- Nouvelle **branche macOS avant la branche tray** (sur Mac `build_tray` rend déjà
  `None`) : serveur sur fil daemon, run loop AppKit minimale (`NSApplication` +
  `AppHelper.runEventLoop()`) sur le fil principal.
- **Référence explicite** : `run_desktop` relit `DesktopHandler._recording_controller`
  et la garde en local ; le handler continue de l'observer pour la route lecture-seule.
- **Dispatch hors run loop** : le `on_trigger` passé à `register_hotkey` lance un
  **fil daemon** → `controller.toggle()` (le verrou + le debounce internes gèrent
  la sérialisation des double-appuis).
- **`finally`** : `controller.shutdown()` puis `server_close()`.
- Le lanceur de run loop est **injectable** pour que les tests ne bloquent pas.
- Tests (`tests/test_desktop.py`) : `is_macos()` patché + run loop mockée → serveur
  sur fil secondaire, raccourci enregistré avec la bonne combi, le trigger atteint
  `controller.toggle` **hors du fil appelant**, `shutdown()` appelé au `finally`.
  Régression Linux : branche Linux inchangée.

### M5c — `install-hotkey` macOS + réglage de fichier
Modifie `cli.py::handle_install_hotkey` + `config.py`.
- Nouveau réglage **de fichier** `hotkey` dans `DEFAULT_CONFIG` (**pas** dans
  `EDITABLE_FIELDS` — même statut que `max_recording_seconds` : ni contrôle web, ni
  route). Lu au démarrage de la run loop pour enregistrer la combi.
- `handle_install_hotkey` branche sur `is_macos()` :
  - `--print` : montre la combi + « actif uniquement quand Aparté tourne » + Plan B
    documenté (`skhd`, non intégré) ;
  - défaut : valide la combi, l'écrit dans `config.json`, indique qu'elle est prise
    en compte au **(re)démarrage** de l'app ;
  - asymétrie assumée vs Linux : ici « installer » = persister le choix ; l'échec
    d'une combi réservée se découvre au **runtime** (M5d), pas à l'install.
- Tests (`tests/test_cli.py`) : dispatch mac, `--print`, persistance + validation.

### M5d — Diagnostics d'échec de combinaison
Modifie `diagnostics.py`.
- Entrée `doctor` macOS pour le raccourci : combinaison configurée + prérequis
  « serveur résident obligatoire ». **`detail` dynamique, sans clé i18n statique**
  (invariant : une clé statique écraserait un détail variable ; cf. le check
  `config`), libellé neutre.
- Échec de `register_hotkey` au démarrage → **notification `critical` immédiate**
  in-process (sinon le raccourci ne marcherait pas en silence). La surface d'état
  riche cross-processus (OSStatus détaillé dans le tray) reste **M6**.
- Tests : présence de l'entrée mac, détail dynamique, notification sur échec.

### M5e — Docs + invariants + preuve
- `CLAUDE.md` (run loop AppKit unique ; dispatch hors run loop avant `toggle()` ;
  raccourci in-process qui exige l'app lancée ; `shutdown()` câblé ; combi = réglage
  de fichier), `CHANGELOG.md` §M5, `tasks/todo.md` §M5.
- Suite verte : `PYTHONPATH=src python3 -m unittest discover -s tests -t tests`
  (313 verts aujourd'hui + les tests neufs M5a–d).

## Décisions (recommandations)

1. **Propriété du contrôleur** : `run_desktop` **relit** `_recording_controller`
   depuis la classe handler (diff minimal), plutôt que de changer la signature de
   `handler_factory` pour renvoyer `(HandlerClass, controller)`. → *le plus simple*.
2. **Persistance de la combi** : réglage de fichier `hotkey` lu au démarrage ;
   changer la combi demande un **redémarrage** (pas de ré-enregistrement à chaud en
   M5). Cohérent avec `max_recording_seconds`.
3. **Dispatch** : **un fil daemon par appui** → `toggle()`, plutôt que GCD
   `dispatch_async`. Plus simple ; déjà couvert par le verrou + le debounce internes.
4. **Diagnostics M5** : statique (combi + prérequis) + **notification** à l'échec ;
   statut riche cross-processus → tray **M6**.
5. **Combinaison par défaut** : placeholder à confirmer sur Mac (Cmd+Espace =
   Spotlight, donc exclu).

## Points sensibles (zones d'incertitude assumées)

- **Cohabitation run loop AppKit + RegisterEventHotKey** : le plan global la désigne
  comme « le point technique le plus incertain ». Conçue mais non prouvable sous
  Linux → M8. Risque : est-ce que `NSApplication` + `AppHelper.runEventLoop()` suffit
  sans `NSApplicationActivationPolicy` particulier pour une app sans fenêtre ?
- **Un fil daemon par appui** : est-ce le bon primitif de dispatch ? Deux appuis
  rapides lancent deux fils qui sérialisent sur `_lock` ; le debounce interne à
  `toggle()` absorbe le second. Correct mais indirect — faut-il un dispatch dédié ?
- **pressé-only vs debounce** : si la façade s'abonne bien à `kEventHotKeyPressed`
  seul, la correction ne dépend plus du debounce ; mais key-repeat matériel pourrait
  encore refeu. Le debounce 250 ms reste un garde secondaire. Décision finale = M8.
- **Réglage de fichier `hotkey` non ré-enregistrable à chaud** : `install-hotkey`
  sur un serveur **déjà lancé** ne prend effet qu'au redémarrage. Acceptable ?
  Faut-il au moins signaler « redémarre Aparté » clairement ?
- **Diagnostics cross-processus** : `doctor` (process CLI séparé) ne voit pas le
  résultat d'enregistrement du serveur résident. En M5 le doctor est donc **statique**
  (combi + prérequis) ; le statut réel (enregistré/échoué/OSStatus) n'est visible
  que dans le process résident (notification à l'échec + tray M6). Est-ce un manque ?
- **Où vit le lanceur de run loop ?** : dans `macos_hotkey.py` (couplé au besoin de
  run loop du hotkey) ou un module dédié ? En M6, rumps prendra la run loop et
  appellera `register_hotkey` pendant son init — donc la *registration* est stable,
  le *run-loop-running* est M5-transitoire.

## Alternatives écartées

- **Event tap `CGEventTap`/`pynput`** : demande la permission « Surveillance de
  l'entrée » (la pire) ; `RegisterEventHotKey` n'en demande aucune.
- **Transposer `session.py`** sur Mac (enregistreur détaché, `/proc`) : plus de code
  pour reproduire une architecture dont la raison d'être disparaît (le raccourci a
  déjà un processus résident).
- **Route HTTP de bascule** : interdit par l'invariant Darwin M3 (proxy de privilèges).
- **`osascript keystroke`** pour l'insertion (hors M5, mais lié) : invite
  Automatisation + massacre les caractères français.
- **Changer la signature de `handler_factory`** pour sortir le contrôleur : plus
  invasif que relire l'attribut de classe ; touche les appelants de test.
- **Ré-enregistrement à chaud de la combi** : plomberie supplémentaire (exposer un
  hook de ré-enregistrement au runner) pour un gain marginal ; redémarrage suffit en M5.
