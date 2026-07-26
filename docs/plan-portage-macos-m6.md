# M6 — L'icône de barre de menus macOS

_Plan consolidé après contre-expertise (`/confront-codex`, 3 rounds, consensus
bilatéral le 25/07/2026). Archives du débat :
`docs/archives/confront-codex-portage-macos-m6-2026-07-25-1956/`._

## Contexte

Sur macOS, **rien n'indique que le micro est ouvert**. Pas d'icône, pas de fenêtre,
et l'application tourne en policy `accessory` — elle n'affiche donc rien.

Pendant la validation native M8 (25/07, macOS 11.7.11 Big Sur, Intel), le testeur a
appuyé sur le raccourci, n'a eu aucun retour, a cru que rien ne s'était passé, a
réappuyé — et **a arrêté l'enregistrement que le premier appui venait de lancer**. Le
filtre anti-répétition fonctionnait parfaitement ; c'est l'absence de retour qui a
fauté (`docs/plan-portage-macos-m8.md`, défaut G).

Le correctif provisoire livré en M8 — le bip actif par défaut sur macOS — est un
pansement : 90 ms de tonalité se manquent quand on est en train de parler. **M6 est le
remède.**

Périmètre annoncé par le plan initial (`docs/plan-portage-macos.md`, l. 331) : tray
`rumps`, menu, état lisible en permanence, article « Mettre à jour » in-process,
icônes PNG template.

### Décisions produit (Alexandre, 25/07)

1. **Le menu observe, il ne déclenche pas.** Pas d'article « Démarrer la dictée » en
   M6. Assumé : sur une installation neuve, `Settings.hotkey` est vide (le raccourci
   est opt-in via `aparte install-hotkey`), donc M6 ne rend pas une installation neuve
   pilotable depuis la barre de menus. Réversible plus tard.
2. **Icônes monochromes « template ».** macOS teinte lui-même : noir sur barre claire,
   blanc sur barre sombre. Motif : la barre de menus est **translucide sur le fond
   d'écran**, donc aucune couleur fixe n'y est vérifiable par calcul — la règle du
   calcul de `DESIGN.md` y est intenable (carmin `#b8245b` mesuré : 5,4:1 sur barre
   claire, 2,7:1 sur barre sombre, et rien ne dit ce qu'il y a derrière). La règle du
   projecteur garde son aplat carmin là où il est calculable : le bouton de
   l'interface web.
3. **Minuteur pendant l'enregistrement.** « 0:07 » à côté de l'icône. Des chiffres qui
   défilent s'attrapent du coin de l'œil mieux qu'un changement de forme statique.

## Approche

### 1. Une seule boucle AppKit — rumps la possède, `serve_macos` garde tout le reste

`rumps.App.run()` appelle `AppHelper.runEventLoop()`, c'est-à-dire exactement ce que
fait `_appkit_run_loop`. Les deux ne peuvent pas coexister.

**Le point d'injection qui existe depuis M5b est la jointure.** `serve_macos` reçoit
déjà `run_loop` en dépendance injectable ; le tray en fournit une implémentation. Le
contrat devient `run_loop(on_ready, on_quit=None)` — **second argument optionnel**,
sinon `run_hotkey_diagnostic()` (l'outil de validation native M8, qui partage le même
point d'injection) casse sur son chemin par défaut.

`serve_macos` continue de posséder : le `HotkeyDispatcher`, l'inscription du raccourci
dans `on_ready`, la publication de `HotkeyState`, et le démontage. Le tray n'y touche
pas. **Sans `rumps` installé**, la fabrique rend `None` et on retombe sur
`_appkit_run_loop` — comme le tray GTK absent sous Linux ne change rien au serveur.

**`on_ready` passe par un `rumps.Timer`** : `NSApplication` doit exister et la boucle
être vivante avant `RegisterEventHotKey`. Un timer planifié avant `app.run()` s'inscrit
sur la run loop principale et ne se déclenche qu'une fois celle-ci en marche. Comme
`rumps.Timer` **répète par construction**, le one-shot se fabrique : timer retenu sur
l'instance (sinon ramassé), `timer.stop()` en tête de callback, drapeau contre la
double exécution, et arrêt dans le démontage quoi qu'il arrive.

**SIGINT : on n'y touche pas sur le chemin rumps.** `App.run()` appelle
`AppHelper.installMachInterrupt()` juste avant la boucle, donc un `signal.signal()`
posé avant serait écrasé. Conséquence probable — à vérifier sur le Mac, **pas** à
écrire comme invariant : sous rumps, Ctrl-C arrête la boucle, donc `run()` rend la
main, donc le `finally` s'exécute. Le défaut D de M8 serait refermé sur ce chemin.

### 2. Le démontage doit être atteignable — « Quitter » ne revient jamais

`rumps.quit_application()` appelle `NSApplication.terminate_`, qui sort du processus
**sans revenir de `run()`**. Le `finally` de `serve_macos` ne s'exécuterait donc pas
sur le chemin de sortie normal. Même famille que le piège Ctrl-C trouvé en M8 — mais
cette fois il faut corriger, pas documenter : c'est la sortie *normale*.

Le corps du `finally` devient une fonction **idempotente**, protégée par un
`threading.RLock` (réentrant : « Quitter » → démontage → `quit_application()` →
`applicationWillTerminate_` → démontage, tout sur le fil principal ; un verrou non
réentrant s'y interbloquerait), **chaque étape dans son propre `try/except`** — un
`unregister()` qui lève ne doit pas emporter la fermeture du serveur.

Ordre, inchangé : arrêter les timers du tray → `handle.unregister()` →
`dispatcher.close()` → `controller.shutdown(timeout=2.0)` → `server.shutdown()` →
`server.server_close()`.

Trois chemins y mènent :

- l'article « Quitter » du menu, **avant** `rumps.quit_application()` ;
- `rumps.events.before_quit` (`applicationWillTerminate_`) **si la version installée
  l'expose** — garde de version, une bibliothèque plus ancienne ne l'a pas et un
  `AttributeError` au démarrage coûterait le tray entier ;
- le `finally` de `serve_macos`, pour les chemins où la boucle rend la main.

**`quit_button=None` est obligatoire** : `rumps.App` ajoute sinon son propre article
Quit câblé directement sur `quit_application()`, c'est-à-dire un chemin visible qui
contourne tout le démontage.

**Course avec un Quit très rapide** : `on_ready` étant devenu asynchrone, il sort
immédiatement si le démontage a déjà eu lieu, et teste ce drapeau **sous le même
verrou** que le démontage.

**Le gel possible.** `_start_locked()` appelle `ensure_microphone_access()` sous le
verrou du contrôleur, et cette demande attend la réponse TCC jusqu'à 30 s. Un
`shutdown()` bloquant gèlerait donc le fil principal jusqu'à ~35 s. D'où
`shutdown(timeout: float | None = None)` : acquisition bornée, le démontage passe
`2.0`. Le défaut reste bloquant (comportement et test actuels inchangés).
Implémentation : brancher entre `acquire()` et `acquire(timeout=…)` — `None` ne se
passe pas tel quel à `Lock.acquire`.

**« Quitter » quitte toujours.** Une capture vivante est abandonnée (comportement
actuel de `shutdown()`), une transcription en cours aussi — sur Mac Intel elle prend 10
à 40 s, une attente bornée n'aiderait presque jamais et gèlerait la barre de menus. Ce
n'est pas silencieux : la ligne d'état dit « Transcription en cours… » **juste
au-dessus** de l'article « Quitter ». Le `.wav` restant est ramassé par
`sweep_orphan_recordings()`. La **mise à jour**, elle, refuse tout état non `idle` —
elle n'a aucune urgence.

### 3. L'état s'observe sans verrou

Le tray lit `controller.recording_snapshot()` toutes les **0,25 s** via un
`rumps.Timer`, comme le tray GTK sonde `get_active_session()` via
`GLib.timeout_add_seconds`.

**0,25 s en permanence, pas de tic ralenti au repos** : la latence qui compte est
`repos → enregistrement`, celle qu'a vécue le testeur en M8. Elle est gouvernée par le
tic qui court **pendant le repos**. Le coût réel est un `NSTimer` à 4 Hz qui compare
deux chaînes.

**Sans prendre le verrou du contrôleur**, et c'est structurel : ce verrou est tenu
jusqu'à 30 s pendant la demande TCC, et le tray sonde depuis le **fil principal**. Un
sondage verrouillé gèlerait la barre de menus pendant la fenêtre d'autorisation micro,
c'est-à-dire au tout premier enregistrement d'une installation neuve — on remplacerait
un défaut d'usage par un pire.

La cohérence tient par **l'ordre d'écriture**, sous contrat explicite :

1. le tray lit **un seul** instantané par une méthode dédiée, jamais l'état et la durée
   séparément ;
2. `_started_at` est posé **avant** `_state = RECORDING` et effacé **après** la sortie
   de `RECORDING` — y compris sur les chemins erreur et démontage ;
3. le contrat reste petit : lectures atomiques de références immuables (atomiques sous
   le GIL, donc pas de valeur déchirée). **Si un lot futur enrichit cette surface**
   (`last_error`, `truncated`, `overflowed`), soit il publie une structure immuable en
   **une seule affectation**, soit la question du verrou se rouvre.

Pire cas : une transition tombe entre les deux lectures et le tray affiche l'icône
d'enregistrement sans le minuteur pendant **un tic de 250 ms**.

### 4. Ce que le tray affiche

**Deux icônes template**, silhouettes franchement différentes, reprises de la marque
(le logo est un carré carmin portant cinq barres blanches ; le tray GTK en garde trois,
cinq se réduisant à des traits d'un pixel et demi) : **repos** = les trois barres,
**enregistrement** = le disque plein. L'état se lit donc sans la couleur (« règle du
daltonien », `DESIGN.md`).

**Titre à côté de l'icône** : vide au repos, `0:07` pendant l'enregistrement, `…`
pendant la transcription — troisième état, signal non chromatique, sans prétendre que
le micro est encore ouvert.

**Menu** :

```
Prêt à dicter                      ← désactivé, dynamique (état)
Raccourci : ⌃⌥D                    ← désactivé, dynamique (inscription réelle)
───────────────
Ouvrir Aparté
Copier la dernière dictée
Réglages
───────────────
Rechercher une mise à jour…        ← dynamique
───────────────
Quitter
```

Les trois articles du milieu reprennent le tray GTK à l'identique, **y compris le
détail qui compte** : copier la dernière dictée part sur un fil, parce que la copie
passe par un outil externe et qu'un presse-papiers lent gèlerait tout le menu.

La ligne du raccourci est **dynamique**, pas statique : `serve_macos` publie déjà
`HotkeyState`, qui sait si l'inscription a **échoué**. Afficher « configuré » ne suffit
pas quand Carbon a refusé la combinaison. Le libellé passe toujours par
`safe_hotkey_label()`, jamais `hotkey_label()` nu — une config éditée à la main ne doit
pas faire tomber le tray.

### 5. Toutes les chaînes visibles (fr / en)

**État** — `Prêt à dicter` / `Ready to dictate` ; `Micro ouvert` / `Microphone open` ;
`Transcription en cours…` / `Transcribing…` ; `La dernière dictée a échoué` /
`The last dictation failed`.

**Raccourci** — `Raccourci : ⌃⌥D` / `Shortcut: ⌃⌥D` ; `Aucun raccourci —
aparte install-hotkey` / `No shortcut — aparte install-hotkey` ; `Raccourci
indisponible : ⌃⌥D` / `Shortcut unavailable: ⌃⌥D`.

**Articles** — `Ouvrir Aparté` / `Open Aparté` ; `Copier la dernière dictée` /
`Copy the last dictation` ; `Réglages` / `Settings` ; `Quitter` / `Quit`.

**Mise à jour, libellés d'article** — `Rechercher une mise à jour…` /
`Check for updates…` ; `Vérification…` / `Checking…` ; `Installer la version {v}` /
`Install version {v}` ; `Installation…` / `Installing…` ; `Mise à jour installée —
relance Aparté` / `Update installed — relaunch Aparté`.

**Mise à jour, notifications** — un état de `check_update` par ligne :

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
| échec | Mise à jour interrompue : {dernière ligne} | Update stopped: {last line} |
| refus | Une dictée est en cours — réessaie après. | A dictation is in progress — try again after. |

### 6. La mise à jour : deux temps, installe **sans relancer**

Sur Darwin, `/api/update/apply` est 404 par invariant — le tray est le seul chemin.

| Clic | Action | Retour |
|---|---|---|
| 1er | `check_update(fetch=True)` sur un fil (réseau seulement sur demande) | notification + libellé de l'article |
| 2e | `apply_update()` sur un fil | journal en notification, article figé |

Deux temps parce qu'une mise à jour réinstalle des paquets : un clic malencontreux ne
doit pas la déclencher, et l'interface web fait déjà pareil.

**Aucune relance.** `os.execv` relancerait l'interpréteur, pas l'application
responsable vue par TCC — question qui appartient à M7 (bundle / LaunchAgent,
`docs/plan-portage-macos.md:307-315`). La retirer de M6 évacue aussi le risque
« `execv` depuis un worker avec une run loop AppKit et un élément de barre de menus
vivants ». Le message est honnête : le processus tourne encore sur l'ancien code, et
on le dit. L'article « Quitter » est un centimètre plus bas.

**L'état « redémarrage requis », dans `update.py`.** Sans relance, `__version__` reste
périmé en mémoire : `check_update()` reproposerait la même mise à jour et un second
clic relancerait `git merge` + `pip install` pour rien.

- un drapeau **local au processus**, armé quand `apply_update()` émet `DONE_MARKER`,
  qui **mémorise la release cible** ;
- `check_update()` rend alors `{"state": "restart_required", …}` **avant** de toucher à
  git ou au réseau ;
- `apply_update()` refuse de repartir depuis cet état, **juste après** son appel
  initial à `check_update()`, au même niveau que `manual` / `no_upstream` / `error` /
  `current` — nécessaire, parce que la suite suppose `repo` et `release` ;
- l'état est **honnête** : il ne dit pas « la version exécutée est X », il dit « ce
  processus a installé X mais exécute encore l'ancien code ».

Placé là, le tray et le panneau web disent la même chose sans se parler. Le chemin
Linux n'est pas dégradé — si `os.execv` réussit, le processus et le drapeau
disparaissent ensemble ; si la relance **échoue**, « redémarrage requis » est
exactement ce qu'il faut afficher.

**`_installed_extras()` apprend `macos`** (`_has_module("rumps") or
_has_module("AppKit")`). Sémantique testée : préserver les extras **réellement
présents**, jamais « ajouter `macos` parce qu'on est sur Darwin ».

**Panneau web** : sur Darwin, plus de bouton d'application (la route est 404) mais une
phrase traduite qui renvoie à l'icône de barre de menus ; et `update.restart_required`
gagne sa chaîne fr + en dans `i18n.js` — `app.js` sait déjà rendre un état non
`available` sans bouton.

### 7. Un tray qui ne se construit pas ne doit pas échouer en silence

Sous Linux le tray est une commodité ; ici c'est **le correctif** du principal défaut
d'usage. Un `except Exception: return None` recréerait le bug que M6 ferme.

- dépendance absente (`ImportError`) → repli silencieux : c'est un choix d'installation ;
- échec **inattendu** → `stderr` + `notify()` ;
- plus un check `doctor` macOS `tray`, **jamais essentiel**, `detail` **dynamique sans
  clé i18n** (règle `CLAUDE.md` § Interface : un détail qui varie ne porte pas de clé
  statique, sinon elle l'écrase et peut contredire l'icône).

## Étapes d'implémentation

Chaque lot a ses tests et son commit.

1. **M6a — socle testable, zéro natif.** `src/aparte/macos_tray.py` : `LABELS` fr/en,
   `tray_view(...)` pure (icône, titre, ligne d'état, ligne de raccourci),
   `format_elapsed`. `RecordingController` : `_started_at` posé/effacé dans le bon
   ordre, `recording_snapshot()` sans verrou, `shutdown(timeout=None)` borné.
2. **M6b — cohabitation des boucles.** `MacTray` (liaison rumps mince,
   `quit_button=None`, timer one-shot retenu et arrêté, aucun `signal.signal`),
   `build_tray()`, `serve_macos(url=…, tray_factory=…)`, `run_loop(on_ready,
   on_quit=None)`, démontage sous `RLock` avec étapes best-effort, `on_ready` qui
   renonce après démontage, raccrochage à `rumps.events.before_quit` si disponible.
   Tests avec un faux `rumps` injecté dans `sys.modules` (patron du faux `sounddevice`
   de `test_macos_recording.py`).
3. **M6c — les deux icônes.** SVG monochromes + PNG 40 px **commités** (aucune étape de
   compilation pour un contributeur), commande de régénération documentée. Test : PNG
   valide, dimensions justes, aucun pixel coloré. Passage par `/impeccable`.
4. **M6d — « Mettre à jour ».** Décision pure par état, deux temps, refus si l'état
   n'est pas `idle`, installation sans relance, `restart_required` dans `update.py`,
   `_installed_extras()` élargi, panneau web.
5. **M6e — doc + check `doctor` `tray`.** `CLAUDE.md`, `DESIGN.md` (§ icône de barre de
   menus), `CHANGELOG.md`, `tasks/todo.md`. Retrait de `quickmachotkey` de l'extra
   `macos` (dette M8 : jamais importé, le pont Carbon est en `ctypes`).

## Points de vigilance

- **Les faux Linux prouvent notre orchestration, jamais le comportement de la
  plateforme.** M8 l'a montré : un `Segmentation fault` à la première exécution
  native, invisible en test mocké. Aucune hypothèse rumps n'est vérifiable ici.
- **La version de `rumps` réellement installée** peut différer de la branche `master`
  lue pendant la revue. D'où la garde de version sur `rumps.events.before_quit`.
- **Ne pas écrire d'invariant sur le Ctrl-C rumps** avant de l'avoir vu — c'est
  exactement l'erreur corrigée en M8.
- **Le contrat de l'instantané sans verrou** est fragile à l'extension. L'écrire dans
  `CLAUDE.md` comme invariant, pas comme note.
- **`rumps.notification()`** exige un bundle : la dette reste rattachée à M7. On garde
  `notify()` (osascript).
- **`aparte update` n'existe pas** dans le parser CLI. Ne plus le citer ; il reste à M7
  s'il est voulu.

## Checklist de validation native (reprise courte sur le Mac)

Outillage prêt : `.claude/mac-validation/README.md`.

1. L'icône apparaît au lancement, sans vol de focus.
2. Rendu template correct en barre **claire** et en barre **sombre**.
3. Premier appui : l'icône change en moins d'une demi-seconde ; le minuteur défile.
4. Relâche : titre `…` pendant la transcription, puis retour au repos.
5. Ligne de raccourci : conforme à l'état réel (inscrit / aucun / refusé).
6. « Quitter » : démontage dans l'ordre, aucun processus survivant, port libéré.
7. Ctrl-C sous rumps : noter le comportement réel (l'invariant s'écrit **après**).
8. Mise à jour refusée pendant une dictée ; après installation, l'article se fige sur
   « relance Aparté » et ne repropose plus rien.
9. Repli sans `rumps` : `pip uninstall rumps`, le serveur et le raccourci fonctionnent
   comme avant, `doctor` le signale.

## Décisions explicitement écartées

- **Construire `NSStatusItem` à la main en PyObjC** — plus de code natif non testable ;
  `rumps` est déjà dans l'extra `[macos]` depuis M0. C'est le repli si rumps déçoit.
- **Garder notre boucle et n'emprunter que l'élément de barre de rumps** (en appelant
  `_nsapp.initializeStatusBar()` nous-mêmes) — fouiller dans des internes non
  publiques, cassé au premier changement de version.
- **Faire tourner rumps sur un fil secondaire** — impossible, AppKit exige le fil
  principal.
- **Icône carmin** — la barre de menus est translucide, aucune couleur fixe n'y est
  vérifiable par calcul.
- **Article « Démarrer / Arrêter la dictée »** — décision produit, observation seule en
  M6. S'il revient, il passera par `dispatcher.trigger()` (rapide, non bloquant, déjà
  anti-répétition) et **jamais** par `controller.toggle()` en direct, qui garde son
  verrou pendant l'I/O de démarrage et gèlerait la run loop.
- **Sondage ralenti au repos** — optimiserait le mauvais segment : la latence qui
  compte naît pendant le repos.
- **Instantané lu sous le verrou du contrôleur** — gèlerait la barre de menus jusqu'à
  30 s pendant la demande d'autorisation micro.
- **`restart()` après installation** — relancerait l'interpréteur, pas l'application
  responsable vue par TCC. Appartient à M7.
- **Un seul clic pour mettre à jour** — trop expéditif pour une action qui réinstalle.
- **Attendre la fin d'une transcription au moment de quitter** — 10 à 40 s sur Mac
  Intel, la barre de menus gelée pendant ce temps.
