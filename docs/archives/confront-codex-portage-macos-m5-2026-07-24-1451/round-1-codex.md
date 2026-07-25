# Round 1 - Analyse Codex du plan M5

## 1. Ce que j'approuve

### Le cadrage in-process du raccourci macOS

Je valide le choix de ne pas reproduire `session.py` sur macOS. Le code actuel confirme que le chemin Linux repose encore sur des sessions/PID côté CLI, alors que `RecordingController` vit déjà en mémoire serveur dans `src/aparte/macos_recording.py`. Pour `RegisterEventHotKey`, le processus résident est donc le bon lieu d'exécution.

Je valide aussi l'interdiction d'une route HTTP de bascule ou d'insertion système. `desktop.py` a déjà la garde Darwin sur `/api/paste`, `/api/copy` et `/api/update/apply` (`_DARWIN_DISABLED_POST_ROUTES`), et M5 doit rester cohérent avec ce modèle : le raccourci appelle le contrôleur en direct, pas une route locale.

### La façade `macos_hotkey.py`

Le module dédié est le bon découpage. Le code Linux `hotkey.py` est une façade de bureau Linux, pas un module abstrait multi-OS ; le miroir macOS évite de polluer les conventions gsettings avec Carbon/AppKit.

L'injection du backend pour les tests est indispensable. La machine de dev est Linux, donc les tests M5 ne prouveront pas Carbon, mais ils peuvent verrouiller le contrat : parsing, inscription press-only, conservation du handle, propagation d'une erreur d'inscription avec un statut exploitable.

### Une run loop AppKit sur le fil principal

Le plan a raison de ne pas réutiliser la branche `tray is None -> server.serve_forever()` pour macOS. Aujourd'hui `run_desktop()` met le serveur sur le fil principal en absence de tray (`desktop.py:99-100`), mais un hotkey Carbon a besoin d'une boucle CF/AppKit vivante. La branche macOS avant la branche tray est donc justifiée.

Le serveur HTTP sur thread secondaire est aussi le bon sens : GTK possède déjà le fil principal quand le tray Linux existe (`tray.py:150-156`), et macOS aura la même contrainte avec AppKit/rumps.

### Le câblage de `shutdown()`

Je valide la contrainte : dès que M5 rend `RecordingController.toggle()` déclenchable, `run_desktop()` doit appeler `controller.shutdown()` au shutdown. Le contrôleur sait déjà abandonner proprement une capture live sans transcription de dernière seconde (`macos_recording.py:162-172`). Ne pas le câbler laisserait un stream PortAudio et un timer vivants jusqu'à la mort du process.

### Le réglage de fichier pour la combinaison

Le choix de ne pas exposer `hotkey` dans l'UI web est raisonnable en M5. La combinaison clavier est une intégration système, pas un réglage web immédiat. L'ajouter à `DEFAULT_CONFIG` et à `Settings`, sans `EDITABLE_FIELDS`, colle au style actuel de `max_recording_seconds`.

### La preuve par mocks, avec réserve explicite Mac

Le plan est honnête sur la limite : les tests Linux mockés ne valideront ni TCC, ni Carbon, ni PortAudio réel, ni AppKit. Pour un lot de câblage dans ce repo, c'est acceptable si la doc ne prétend pas que le comportement Mac réel est prouvé avant la smoke suite.

## 2. Ce que je désapprouve

### Un fil daemon par appui n'est pas le bon primitif

Je désapprouve ce choix. Le fait que `toggle()` ait un lock et un debounce ne suffit pas.

Le problème concret : le debounce est évalué quand le thread entre dans `toggle()`, pas quand l'événement clavier est reçu. Si le premier appui bloque dans `_start_locked()` sur import `sounddevice`, ouverture PortAudio, bip ou `Timer.start()` (`macos_recording.py:148-232`), les répétitions clavier ou doubles événements peuvent s'empiler en threads. Quand elles prendront le lock plus tard, plus de 250 ms peuvent s'être écoulées, et une répétition initiale peut devenir un stop légitime. Le verrou sérialise, il ne filtre pas l'intention utilisateur.

Autre problème : un thread daemon par appui est non borné. Une touche maintenue, un bug de backend ou une séquence d'événements répétés crée autant de threads que d'événements. Même si chacun finit par être debouncé, on a introduit une file implicite non maîtrisée, sans observabilité, sans fermeture propre, et avec des exceptions perdues sauf si `toggle()` les absorbe toutes.

La primitive M5 devrait être un dispatcher unique et borné, pas un thread par appui. Par exemple : un worker résident `HotkeyDispatcher`, une file de capacité 1 ou une coalescence `pending`, un flag `closing`, et un test prouvant que 100 triggers rapides ne produisent pas 100 threads et ne peuvent pas transformer une répétition de start en stop retardé. Si on veut garder le debounce dans `RecordingController`, le dispatcher doit au moins empêcher l'accumulation pendant qu'un toggle est déjà en cours.

### Relire `_recording_controller` depuis la classe n'est pas une propriété explicite

Je désapprouve la recommandation "relire l'attribut de classe" comme solution de propriété. Elle est minimale, mais elle contredit la contrainte M4 : "le propriétaire naturel est le processus desktop / run loop".

Aujourd'hui, `handler_factory()` construit le contrôleur seulement parce qu'il possède `inference_lock`, `current_settings()` et `get_transcriber()` dans sa closure (`desktop.py:190-239`, `492-503`). L'attacher à `DesktopHandler._recording_controller` est acceptable tant que seul HTTP l'observe, mais faire ensuite de `run_desktop()` un lecteur de cet attribut privé de classe inverse l'ownership : le runner dépend d'un détail de handler.

Le bon compromis n'est pas forcément une grosse refonte. Il suffit de changer l'API de construction sans casser les appelants existants, par exemple `handler_factory(settings, *, return_controller=False)` ou un petit `build_desktop_components(settings)` qui retourne `(HandlerClass, controller)`. `run_desktop()` reçoit alors explicitement le contrôleur, le passe au hotkey, et le handler garde une référence d'observation. Les tests existants peuvent continuer à appeler `handler_factory(Settings())` sans tuple.

### Le `finally` proposé est incomplet

`controller.shutdown()` puis `server_close()` est nécessaire, mais pas suffisant dans la branche macOS proposée.

Sur macOS, le serveur tournera sur un thread secondaire. Si la run loop AppKit retourne, `server_close()` seul ne demande pas à `serve_forever()` de sortir proprement. Il faut distinguer les branches : quand le serveur a été démarré en arrière-plan, appeler `server.shutdown()` depuis le fil principal avant `server_close()`, puis éventuellement joindre brièvement le thread serveur. En revanche, il ne faut pas appeler `shutdown()` depuis le même fil que `serve_forever()` dans la branche Linux sans tray, car ce serait une autre classe de problème.

Il manque aussi la durée de vie du handle hotkey : garder une référence forte, puis unregister/dispose dans le `finally` avant ou pendant l'arrêt du dispatcher. Sinon un callback peut encore arriver pendant que `controller.shutdown()` ferme l'état.

Enfin, `RecordingController.shutdown()` ne traite que l'état `RECORDING`. Si l'état est `PROCESSING`, le worker daemon continue ou sera tué à la sortie du process. Ce peut être acceptable, mais le plan M5 ne doit pas faire semblant que "shutdown câblé" résout la fermeture pendant traitement. La décision abandon documenté vs join borné reste à trancher ou à documenter clairement.

### La promesse `OSStatus` est trop forte si `quickmachotkey` reste le backend réel

Je valide l'objectif de surfacer `OSStatus`, mais je désapprouve la formulation "adaptateur mince sur quickmachotkey, puis remplacement si pas assez de contrôle" comme base M5.

M5d dépend précisément de diagnostics d'échec de combinaison. Si la lib ne remonte pas le statut Carbon brut, alors la façade ne peut pas promettre `HotkeyError.status` autrement que par approximation. Il faut faire ce spike avant de figer M5a : soit `quickmachotkey` expose réellement l'information nécessaire, soit le binding PyObjC/ctypes interne est le backend M5 dès le départ. Garder l'alternative ouverte est bien ; construire le lot sur une promesse non vérifiée l'est moins.

### Le diagnostic cross-process repoussé à M6 est trop faible

Je désapprouve le report complet du statut réel à M6. Le problème n'est pas seulement le tray : `aparte doctor` est une CLI séparée, et le code actuel `collect_diagnostics()` lit `get_active_session()` et `hotkey_info()` Linux (`diagnostics.py:303-313`). Sur macOS, cela ne verra ni l'état du contrôleur in-process, ni l'échec d'enregistrement du hotkey dans le serveur résident.

Une notification critique au démarrage ne suffit pas. Elle est éphémère, non scriptable, et l'utilisateur lancera naturellement `doctor` après avoir constaté que le raccourci ne marche pas. M5 devrait ajouter une surface read-only de statut résident, par exemple `/api/hotkey-state` ou une extension de `/api/recording-state`, puis faire que `doctor` interroge le serveur déjà lancé quand il existe. Ce n'est pas une route à effet système ; elle respecte l'invariant Darwin.

## 3. Ce qui manque

### Un contrat de dispatcher testable

Les tests proposés doivent aller au-delà de "le trigger atteint `controller.toggle()` hors du fil appelant". Il faut prouver :

- aucun thread non borné par répétition d'événements ;
- pas de toggle retardé qui transforme une répétition de start en stop ;
- fermeture propre : trigger ignoré après `closing=True` ;
- exceptions de `controller.toggle()` capturées et notifiées/loggées, même si elles ne devraient pas sortir souvent ;
- unregister du handle au shutdown.

Sans ces tests, M5 valide seulement "pas sur la run loop", pas "dispatch correct".

### La sémantique de `--remove` et `--target` sur macOS

Le plan couvre `--print` et l'installation par défaut, mais pas `--remove`. Or l'option existe déjà dans le parser (`cli.py:207-208`). Sur macOS, elle doit avoir une sémantique explicite : supprimer la clé de config, écrire `null`, revenir au défaut, ou dire que la suppression n'a pas de sens. Ne rien définir donnera une asymétrie confuse avec Linux.

Même problème pour `--target`. Le parser accepte `paste`, `copy`, `stdout` (`cli.py:200-204`), mais le worker macOS livre aujourd'hui toujours vers `"paste"` (`macos_recording.py:297-304`). Si M5 persiste seulement la combinaison, `aparte install-hotkey --target copy` sera accepté mais sans effet sur le raccourci résident. Il faut soit rejeter `--target != paste` sur macOS avec un message clair, soit ajouter un réglage de cible et l'utiliser dans `RecordingController._deliver()`.

### La forme exacte du champ `hotkey` dans `Settings`

Ajouter `hotkey` à `DEFAULT_CONFIG` ne suffit pas. Il faut ajouter le champ à la dataclass `Settings`, le charger dans `Settings.from_env()`, décider d'un éventuel override `APARTE_HOTKEY`, et définir la valeur vide : `None`, chaîne vide, ou défaut. Cette distinction compte pour `--remove`, `doctor`, et pour savoir si le serveur doit tenter un enregistrement.

Il faut aussi éviter de mélanger les formats Linux et macOS. Le Linux actuel utilise des accélérateurs gsettings comme `<Super>space`; le plan macOS parle de `mod+mod+touche`. Les deux formats peuvent cohabiter, mais le nom générique `hotkey` risque de suggérer une compatibilité qui n'existe pas. Je préférerais un format canonique documenté pour macOS et des helpers `normalize_hotkey()` / `hotkey_label()`.

### Le comportement en cas d'échec d'import ou d'inscription du hotkey

Le plan dit "notification critical sur échec de register_hotkey", mais il doit préciser si le serveur continue. À mon avis, il doit continuer : l'UI web et la dictée navigateur restent utiles. L'échec du hotkey doit mettre un état observable `registered=false`, `error`, `status`, `configured_key`, puis laisser le serveur en vie.

Cas à tester : extra `[macos]` absent, PyObjC absent, `quickmachotkey` absent, combinaison invalide, combinaison réservée, backend qui lève sans `OSStatus`.

### La configuration AppKit minimale

Le plan identifie l'incertitude, mais il manque des décisions de base pour l'implémentation :

- appel à `NSApplication.sharedApplication()` avant inscription du hotkey ;
- activation policy pour une app sans fenêtre (`accessory` ou autre choix explicite) ;
- stratégie SIGINT/KeyboardInterrupt avec `AppHelper.runEventLoop()`;
- fonction injectable de run loop qui ne force pas l'import PyObjC dans les tests Linux ;
- emplacement du runner : probablement un module dédié `macos_runloop.py`, pas `macos_hotkey.py`, pour ne pas mélanger inscription hotkey et cycle de vie applicatif.

### La preuve de non-régression Linux

Le plan dit "branche Linux inchangée", mais M5 va toucher `desktop.py`, `cli.py`, `config.py` et `diagnostics.py`, donc la preuve doit inclure des tests Linux existants sur :

- `run_desktop()` sans tray : serveur encore sur fil principal ;
- `run_desktop()` avec tray : serveur sur fil secondaire et `tray.run()` ;
- `install-hotkey` Linux : comportement gsettings inchangé ;
- `doctor` Linux : `hotkey_info()` Linux inchangé.

## 4. Ce que je remettrais en question

### Le report de validation Mac réelle à M8

Je comprends la contrainte de machine Linux, mais M5 est précisément le lot qui dépend d'une run loop AppKit et de Carbon. Dire "M5 livré" sans aucun smoke Mac réel est fragile. Si M8 reste le lot de smoke complet, M5 devrait au minimum être formulé comme "implémenté et mock-testé, comportement natif non validé". Sinon, un défaut fondamental de cohabitation `NSApplication` + `RegisterEventHotKey` pourrait contaminer les lots M6/M7.

### Le non-réenregistrement à chaud

Je peux accepter le redémarrage requis en M5, mais je ne le traiterais pas comme équivalent à `max_recording_seconds`. `max_recording_seconds` est relu par `settings_provider()` à chaque capture (`macos_recording.py:191-194`), alors que la combinaison hotkey ne serait lue qu'au démarrage. La comparaison est donc imparfaite.

Le redémarrage est acceptable si `install-hotkey` le dit explicitement, si `doctor` affiche "configurée, serveur lancé avec ancienne combinaison" quand il peut le savoir, et si le choix n'empêche pas M6 de faire un réenregistrement propre dans le même processus.

### Le choix `quickmachotkey` vs binding interne

Je ne suis pas opposé à `quickmachotkey`, surtout derrière une façade. Mais si les exigences M5 sont "press-only" et "`OSStatus` exact", le binding interne peut être plus simple que de dépendre d'une lib puis de contourner ses abstractions. Le round suivant devrait trancher sur preuve : API réelle de la lib, accès au statut, gestion du handle, désinscription, comportement sur conflit.

### La combinaison par défaut

Le plan laisse le défaut en placeholder, et c'est correct à ce stade. Je mettrais cependant ce point dans les décisions bloquantes de M5, pas dans les détails. Un raccourci par défaut macOS doit éviter Spotlight, Input Source, Mission Control, Finder, captures d'écran, dictée système Apple, et les combos très fréquentes des apps d'écriture. Tant qu'il n'est pas choisi, les tests peuvent vérifier la plomberie, mais pas l'expérience d'installation.

### La portée de `doctor`

Je remettrais en question la séparation "doctor statique M5, statut riche M6". Le statut du hotkey est une condition de fonctionnement du lot M5 lui-même. Le tray M6 peut enrichir l'affichage, mais `doctor` devrait déjà pouvoir répondre à la question minimale : "le serveur résident a-t-il enregistré la combinaison configurée ?". C'est petit, testable par mocks, et beaucoup plus utile qu'une notification perdue.

### Conclusion technique

Le plan est globalement bien orienté : in-process, pas de route HTTP privilégiée, run loop AppKit sur le fil principal, façade hotkey testée, shutdown du contrôleur. Je ne le validerais pas tel quel avant correction de deux choix structurants : remplacer le thread daemon par appui par un dispatcher borné/coalescent, et sortir le contrôleur de l'attribut de classe comme source de vérité pour `run_desktop()`. J'ajouterais aussi un statut hotkey read-only consultable par `doctor` dès M5.
