# Round 1 — Plan M6 : l'icône de barre de menus macOS (tray `rumps`)

## 1. Contexte

**Aparté** est une application de dictée vocale locale, Linux d'abord, français
d'abord. Le portage macOS est découpé en lots M0 à M8 (`docs/plan-portage-macos.md`).
M0 à M5 et M8 sont livrés ; **M6 est le lot en cours**.

### L'état du portage macOS aujourd'hui

- **M4** — `RecordingController` (`src/aparte/macos_recording.py`) : machine d'état
  d'enregistrement **en mémoire du serveur résident** (PortAudio via `sounddevice`),
  quatre états observables `idle` / `recording` / `processing` / `error`. Pas de
  sous-processus, pas de fichier de session (contrairement à `session.py` sous Linux).
- **M5** — raccourci clavier global `RegisterEventHotKey` (pont Carbon en `ctypes`,
  `src/aparte/macos_hotkey.py`) + **run loop AppKit unique** sur le fil principal
  (`src/aparte/macos_runloop.py`, fonction `serve_macos`), serveur HTTP sur fil daemon.
  `HotkeyDispatcher` répartit hors run loop, sur un worker unique, avec filtrage des
  répétitions **à l'arrivée** de l'événement.
- **M8** — validation native le 25/07 sur macOS 11.7.11 (Big Sur), Intel, Python
  3.11.9. Compte rendu : `docs/plan-portage-macos-m8.md`. Quatre défauts trouvés et
  corrigés (signatures ctypes absentes → `Segmentation fault` ; micro jamais demandé
  → enregistrement silencieux ; `doctor` donnant un conseil Linux ; captures audio
  abandonnées sur le disque).

### Le problème que M6 doit résoudre (défaut G de M8)

Sur Mac, **rien n'indique que le micro est ouvert**. Pas d'icône de barre de menus,
pas de fenêtre, et l'application tourne en policy `accessory` — elle n'affiche donc
rien du tout. Pendant la validation, le testeur a appuyé sur le raccourci, n'a eu
aucun retour, a cru que rien ne s'était passé, a réappuyé — et **a arrêté
l'enregistrement que le premier appui venait de lancer**. Le mécanisme
anti-répétition fonctionnait parfaitement ; c'est l'absence de retour qui a fauté.

Correctif provisoire livré en M8 : le bip est actif par défaut sur macOS
(`_DEFAULT_BEEP = is_macos()`), parce qu'il était le seul signal existant. C'est un
pansement — 90 ms de tonalité se manquent facilement quand on est en train de parler.

**M6 est le remède : une icône de barre de menus dont l'état se lit en permanence.**

### Périmètre annoncé par le plan initial (`docs/plan-portage-macos.md`, l. 331)

> M6 | Tray rumps (menu + **item « Mettre à jour »** in-process + provider d'état +
> icônes PNG template) | 1–1,5 j

### Décisions produit déjà tranchées par Alexandre, avant ce plan (25/07)

1. **Le menu observe, il ne déclenche pas.** Pas d'article « Démarrer / Arrêter la
   dictée » en M6, bien que l'invariant Darwin l'autoriserait explicitement (« Les
   actions natives Mac passent par la CLI, le raccourci in-process ou le tray »).
   Argument contraire écarté sciemment : sur une installation neuve, `Settings.hotkey`
   est **vide** (le raccourci est opt-in via `aparte install-hotkey`), donc le menu
   serait alors le seul déclencheur natif. Alexandre a tranché pour l'observation
   seule ; c'est réversible plus tard.
2. **Icônes monochromes « template ».** macOS teinte lui-même l'image : noir sur barre
   claire, blanc sur barre sombre. Motif : la barre de menus est **translucide sur le
   fond d'écran de l'utilisateur**, donc aucune couleur fixe ne peut être vérifiée par
   calcul contre son fond — or `DESIGN.md` impose la « règle du calcul » (aucune
   couleur n'entre sans contraste calculé, seuil 4,5:1). Mesures faites sur le carmin
   de marque `#b8245b` : 5,4:1 sur barre claire, **2,7:1** sur barre sombre. La règle
   du projecteur garde son aplat carmin là où il est calculable : le bouton
   d'enregistrement de l'interface web.
3. **Minuteur pendant l'enregistrement.** « 0:07 » affiché à côté de l'icône, seulement
   pendant la capture. Des chiffres qui défilent s'attrapent du coin de l'œil bien
   mieux qu'un changement de forme statique — c'est précisément ce qui a manqué en M8.

## 2. Contraintes non négociables

Tirées de `CLAUDE.md` (§ Serveur, § Interface) et de la méthode du projet :

- **Une seule run loop AppKit sur le fil principal.** `RegisterEventHotKey` n'existe
  que si une run loop vivante lui livre ses événements, et `NSApplication` doit exister
  **avant** l'inscription.
- **`run_desktop()` possède le contrôleur** (rendu par
  `handler_factory(return_controller=True)`). Le handler HTTP ne fait qu'observer.
- **Sur Darwin, aucune route POST ne réalise d'effet système** (`_DARWIN_DISABLED_POST_ROUTES`).
  Le critère est « effet système déclenché par HTTP », pas « permission TCC ».
- **Le callback Carbon ne bloque jamais la run loop** ; le filtrage des répétitions se
  fait à l'arrivée de l'événement, jamais à l'exécution.
- **`finally` ordonné** : désinscrire le raccourci → `dispatcher.close()` (join borné)
  → `controller.shutdown()` → `server.shutdown()` + `server_close()`.
- **Les tests tournent sous Linux avec des faux.** Ni PyObjC, ni Carbon, ni PortAudio,
  ni `rumps` n'existent sur la machine de développement.
- **Aucune étape de compilation, aucune bibliothèque front.** Un contributeur doit
  pouvoir modifier un fichier et rafraîchir — donc les PNG sont **commités**, pas
  générés à l'installation.
- **Toute chaîne visible existe en français et en anglais.** Le tray GTK Linux
  (`src/aparte/tray.py`) porte déjà ce patron : un dictionnaire `LABELS` fr/en et un
  `_labels()` qui lit la langue du bureau (`LC_ALL` / `LC_MESSAGES` / `LANG`).
- **Piège de tests connu** : tout test qui laisse un chemin natif macOS appeler le vrai
  `notify()` empoisonne l'interpréteur (`notify.py` importe `gi`, qui échoue ici et
  laisse le module cassé pour les tests suivants). Il faut stubber `notify` au niveau
  du module dans le `setUp`.

## 3. Approche proposée

### 3.1 Le point dur n°1 — la cohabitation des deux boucles

**Fait technique** : `rumps.App.run()` appelle `AppHelper.runEventLoop()` en interne,
c'est-à-dire **exactement** ce que fait déjà `_appkit_run_loop` dans
`src/aparte/macos_runloop.py`. Les deux ne peuvent pas coexister : il n'y a qu'une
boucle d'événements et qu'un fil principal.

**Résolution** : **rumps devient la boucle**, et le point d'injection qui existe déjà
depuis M5b devient la jointure. `serve_macos` a été écrit avec cette couture :

```python
def serve_macos(server, controller, settings, *, register=register_hotkey, run_loop=None):
    if run_loop is None:
        run_loop = _appkit_run_loop
    ...
    run_loop(on_ready)
```

`run_loop` est déjà une dépendance injectable (les tests y passent un faux). Le tray
fournit donc **sa propre implémentation de `run_loop`** :

```python
class MacTray:
    def run_loop(self, on_ready, on_quit):
        NSApplication.sharedApplication().setActivationPolicy_(ACCESSORY)
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        self._schedule_once(on_ready)     # rumps.Timer déclenché une seule fois
        self._schedule_refresh()          # rumps.Timer 0,25 s → icône + titre
        self._app.run()
```

`serve_macos` continue de posséder :
- le `HotkeyDispatcher` et l'inscription du raccourci dans `on_ready` ;
- la publication de `HotkeyState` sur la classe du handler (lue par `doctor` et par
  `GET /api/hotkey-state`) ;
- le démontage ordonné.

Le tray ne touche à rien de tout ça. **Si `rumps` est absent** (import raté, extra
`[macos]` non installé), la fabrique rend `None` et `serve_macos` retombe sur
`_appkit_run_loop` — exactement comme `build_tray()` rend `None` sous Linux quand
PyGObject manque, et le serveur tourne comme avant.

**Pourquoi `on_ready` doit passer par un `rumps.Timer`** : `NSApplication` doit exister
et la boucle doit être vivante avant `RegisterEventHotKey`. Un `rumps.Timer` planifié
**avant** `app.run()` s'inscrit sur la run loop principale et ne se déclenche qu'une
fois celle-ci en marche. C'est le seul point d'accroche « après le lancement » que
rumps expose sans toucher à ses internes.

### 3.2 Le point dur n°2 — « Quitter » ne revient jamais

**Fait technique** : `rumps.quit_application()` appelle `NSApplication.terminate_`, qui
**sort du processus sans revenir de `run()`**. Le `finally` ordonné de `serve_macos` ne
s'exécuterait donc jamais sur le chemin de sortie normal.

C'est la même famille de piège que celui trouvé en M8 (le Ctrl-C : `_appkit_run_loop`
remet SIGINT à `SIG_DFL`, donc `Ctrl-C` tue le processus net, sans `KeyboardInterrupt`
et sans `finally`). La différence est décisive : le Ctrl-C a été **documenté** parce
qu'il est sans dégât et que c'est une sortie brutale assumée. Le « Quitter » du menu,
lui, est la sortie **normale** — il doit démonter proprement.

**Résolution** : le corps du `finally` devient une fonction **idempotente** passée à la
boucle.

```python
def serve_macos(server, controller, settings, *, url, register=..., run_loop=None, tray_factory=...):
    ...
    torn = threading.Event()

    def teardown():
        if torn.is_set():
            return
        torn.set()
        if handle is not None:
            handle.unregister()
        dispatcher.close()
        controller.shutdown()
        server.shutdown()
        server.server_close()

    try:
        run_loop(on_ready, teardown)
    except KeyboardInterrupt:
        print("\nStopping desktop server.")
    finally:
        teardown()
```

L'article « Quitter » du menu appelle `teardown()` **puis** `rumps.quit_application()`.
Le `finally` reste en place pour les chemins où la boucle rend la main (absence de
tray, tests). L'idempotence rend le double appel sans effet.

**Conséquence de signature** : `run_loop(on_ready)` devient `run_loop(on_ready, on_quit)`.
`_appkit_run_loop` accepte le second argument et l'ignore (aucun article « Quitter »
n'existe sur ce chemin ; seul le Ctrl-C en sort, et il tue net). Les faux des tests
existants (`tests/test_macos_runloop.py`) sont mis à jour.

### 3.3 Ce que le tray affiche

**Deux icônes, monochromes template**, silhouettes franchement différentes, reprises de
la marque existante (le logo est un carré carmin portant cinq barres blanches ; le tray
GTK en garde trois, parce que cinq se réduiraient à des traits d'un pixel et demi) :

- **repos** : les trois barres ;
- **enregistrement** : le disque plein.

C'est la même distinction que celle déjà retenue pour le tray Linux, et elle satisfait
la « règle du daltonien » de `DESIGN.md` : l'état se lit sans la couleur.

**Titre à côté de l'icône** : vide au repos, `0:07` pendant l'enregistrement (le
minuteur tranché par Alexandre). Rien pendant `processing` — ou plutôt un caractère
d'attente ? **Point ouvert, je penche pour rien**, la ligne de menu suffit.

**Le menu** :

```
Prêt à dicter                      ← désactivé, dynamique (l'état)
Raccourci : ⌃⌥D                    ← désactivé, statique
───────────────
Ouvrir Aparté
Copier la dernière dictée
Réglages
───────────────
Rechercher une mise à jour…        ← dynamique (voir 3.5)
───────────────
Quitter
```

Libellés d'état, fr / en : `Prêt à dicter` / `Ready to dictate` ; `Micro ouvert` /
`Microphone open` ; `Transcription en cours…` / `Transcribing…` ; `La dernière dictée
a échoué` / `The last dictation failed`.

Si aucun raccourci n'est configuré, la deuxième ligne dit `Aucun raccourci —
aparte install-hotkey` / `No shortcut — aparte install-hotkey`. (PRODUCT.md, principe 4 :
la commande équivalente reste affichée.)

Les trois articles du milieu reprennent le tray GTK à l'identique, y compris le détail
qui compte : **copier la dernière dictée part sur un fil**, parce que la copie passe par
un outil externe et qu'un presse-papiers lent gèlerait tout le menu.

### 3.4 Comment le tray lit l'état — sondage, pas rappel

Le tray lit `controller.state` (lecture d'une chaîne, atomique) toutes les **0,25 s**
via un `rumps.Timer`, exactement comme le tray GTK lit `get_active_session()` toutes les
secondes via `GLib.timeout_add_seconds`. 0,25 s plutôt que 1 s parce que la question à
laquelle l'icône répond est « est-ce que mon appui a été pris en compte ? » — une
seconde de latence, c'est le délai qui a fait douter le testeur en M8.

**Alternative écartée : un rappel poussé par le contrôleur.** Il serait plus immédiat,
mais le contrôleur appellerait alors le tray depuis son fil de worker ou depuis le fil
du raccourci, et toute mise à jour d'interface AppKit doit se faire sur le fil principal
(donc `AppHelper.callAfter`, donc une dépendance supplémentaire du contrôleur vers
l'interface). Le sondage d'une chaîne quatre fois par seconde ne coûte rien et ne peut
pas interbloquer.

**Le minuteur** demande une petite addition au contrôleur :

```python
@property
def recording_seconds(self) -> float | None:
    """Depuis quand le micro est ouvert, ou None si on n'enregistre pas."""
```

C'est la « surface d'état riche » que M5 avait explicitement reportée en M6, réduite au
strict besoin (je ne propose pas d'exposer `truncated` / `overflowed` / la dernière
erreur : personne ne les affiche).

### 3.5 L'article « Mettre à jour », en deux temps

`update.py` existe déjà et sert l'interface web sous Linux. Sur Darwin, la route
`/api/update/apply` est **404 par invariant** — le tray est donc le seul chemin de mise
à jour sur Mac.

Déroulé proposé, sans fenêtre modale (une `NSAlert` depuis un fil de worker est
interdite, et la faire remonter sur le fil principal ajoute de la machinerie native
non testable) :

| Clic | Action | Retour |
|---|---|---|
| 1er | `check_update(fetch=True)` sur un fil | notification, et le libellé du menu change |
| — | état `current` | « Aparté 1.1.1 est à jour », libellé inchangé |
| — | état `available` | libellé → « Installer la version 1.2.0 » |
| — | `manual` / `no_upstream` / `offline` / `error` / `dirty` | notification qui dit pourquoi |
| 2e | `apply_update()` puis `restart()` | journal en notification, libellé « Mise à jour en cours… », article désactivé |

Deux temps plutôt qu'un seul clic : une mise à jour réinstalle des paquets et **relance
l'application**. Un clic malencontreux ne doit pas déclencher ça, et l'interface web fait
déjà pareil (vérifier, puis appliquer).

**Refus si une dictée est en cours** : si `controller.state != "idle"`, l'article
refuse et le dit. Redémarrer pendant un enregistrement le perdrait.

**Une correction indispensable** : `_installed_extras()` (dans `update.py`) ne connaît
que `whisper`, `recording` et `cuda`. Sur Mac, une mise à jour lancée depuis ce menu
réinstallerait donc **sans l'extra `[macos]`** — donc sans garantir PyObjC ni `rumps` si
une version future en ajoute un. Deux lignes à ajouter. Le plan initial rangeait ça dans
M7 ; je le remonte en M6 parce que sans lui, l'article de menu que M6 livre est
subtilement faux le jour où il sert.

### 3.6 Ce qui **ne** change **pas**

- `session.py`, `tray.py`, tout le chemin Linux : **aucune ligne**.
- Les routes HTTP : aucune ajoutée, aucune modifiée. `GET /api/recording-state` existe
  déjà (lecture seule, autorisée sur Darwin) et reste la voie d'observation externe.
- L'invariant Darwin : le tray ne déclenche aucun effet système en M6 (décision 1
  d'Alexandre). Il ouvre le navigateur, copie du texte, met à jour, quitte.

## 4. Découpage

- **M6a — le socle testable, zéro natif.** `src/aparte/macos_tray.py` : `LABELS` fr/en,
  vue pure `tray_view(state, elapsed, hotkey_spec, labels)` → (icône, titre, ligne
  d'état), `format_elapsed`. Plus `RecordingController.recording_seconds`.
  Tests : la vue pour chacun des quatre états, dans les deux langues ; le formatage du
  minuteur (0 s, 7 s, 59 s, 60 s, 3 599 s, ≥ 1 h) ; `recording_seconds` avec une horloge
  injectée (le contrôleur en accepte déjà une).
- **M6b — la cohabitation des boucles.** `MacTray` (liaison rumps mince) +
  `build_tray()` qui rend `None` si rumps manque ; `serve_macos` reçoit `url=` et une
  fabrique injectable ; démontage idempotent ; `run_loop(on_ready, on_quit)`.
  Tests avec un faux `rumps` injecté dans `sys.modules` (patron du faux `sounddevice`
  de `test_macos_recording.py`) : le raccourci s'inscrit toujours par `on_ready` ; le
  démontage passe par « Quitter » **dans l'ordre** ; il ne s'exécute **qu'une fois**
  même si le `finally` le rappelle ; sans rumps, on retombe sur le chemin M5 inchangé.
- **M6c — les deux icônes.** Sources SVG monochromes + PNG 40 px commités, commande de
  régénération documentée (`inkscape` est présent sur la machine de développement, mais
  n'est **pas** une dépendance du projet). Tests : PNG valide, dimensions justes, aucun
  pixel coloré (une image template n'est que du noir et de l'alpha). Passage par le
  skill `/impeccable` (règle du projet pour tout élément visible).
- **M6d — « Mettre à jour ».** Décision pure et testée pour chaque état de
  `check_update` ; refus si une dictée est en cours ; `_installed_extras()` apprend
  `macos`.
- **M6e — la doc.** `CLAUDE.md` (invariants), `DESIGN.md` (§ icône de barre de menus),
  `CHANGELOG.md`, `tasks/todo.md`. Et la dette M8 : retirer `quickmachotkey` de l'extra
  `macos`, jamais importé (le pont Carbon est écrit en `ctypes` à la main).

## 5. Points sensibles — ce que je sais ne pas savoir

Je les liste sans les minimiser : ce plan repose sur des affirmations à propos de
`rumps` que **je ne peux pas vérifier sur cette machine** (pas de PyObjC sous Linux,
donc pas de `rumps` installable, donc pas même la lecture du source de la version qui
sera réellement installée).

1. **`rumps.App.run()` appelle bien `AppHelper.runEventLoop()`** — c'est le socle de
   tout le plan. Si c'était faux (par exemple s'il lançait sa propre boucle autrement),
   la jointure change.
2. **`rumps.quit_application()` ne revient jamais.** Si en réalité `run()` rendait la
   main, le `finally` suffirait et l'ajout de `on_quit` serait de la machinerie inutile
   — mais elle resterait inoffensive (idempotence).
3. **Un `rumps.Timer` planifié avant `run()` se déclenche bien une fois la boucle
   vivante.** Si non, il faut un autre point d'accroche (délégué d'application, ou
   `AppHelper.callLater`).
4. **Le rendu « template » et la taille.** rumps redimensionne l'image à 20×20 points ;
   je propose des PNG de 40 px pour tomber juste sur un écran Retina et faire une
   réduction propre 2:1 sinon. À vérifier de l'œil sur la machine.
5. **`restart()` fait `os.execv` depuis un fil de worker** pendant qu'une run loop
   AppKit et un élément de barre de menus sont vivants sur le fil principal. `execv`
   remplace l'image du processus (ce n'est pas `fork`, qui serait le vrai danger avec le
   runtime Objective-C), donc je le crois sûr — mais ce n'est pas prouvé, et ça n'a
   jamais été exercé sur Mac.
6. **Le `dispatcher.close()` joint le worker jusqu'à 5 s.** Appelé depuis l'article
   « Quitter », donc **sur le fil principal**, il peut geler le menu jusqu'à 5 secondes
   si une dictée est en cours de transcription. Acceptable à la fermeture, mais c'est un
   gel visible et je préfère l'écrire que le découvrir.
7. **Les tests avec un faux `rumps` ne prouvent que notre orchestration**, jamais le
   comportement réel de rumps. C'est exactement la situation de M0–M7, et M8 a montré
   ce que ça laisse passer (un `Segmentation fault` à la première exécution native).
   Une reprise courte sur le Mac est donc prévue, avec l'outillage déjà documenté dans
   `.claude/mac-validation/README.md`.
8. **La langue du menu vient de l'environnement** (`LANG`), comme le tray GTK. Sur macOS
   lancé depuis le Finder plus tard (M7, bundle), `LANG` peut être absent — le menu
   tomberait en anglais. Je le note ; le corriger supposerait de lire
   `NSUserDefaults AppleLanguages`, ce qui est du natif non testable, et le sujet
   appartient plutôt à M7.

## 6. Alternatives écartées

- **Construire l'élément de barre de menus à la main** (`NSStatusBar` / `NSStatusItem`
  en PyObjC, sans rumps) : plus de code natif non testable, et `rumps` est déjà déclaré
  dans l'extra `[macos]` depuis M0. Écarté, mais c'est le repli si rumps déçoit.
- **Garder notre boucle et n'emprunter à rumps que son élément de barre** (en appelant
  `_nsapp.initializeStatusBar()` nous-mêmes) : ça marcherait peut-être, mais c'est
  fouiller dans les internes non publiques d'une bibliothèque, donc casser au premier
  changement de version. Écarté.
- **Faire tourner rumps sur un fil secondaire** : impossible, AppKit exige le fil
  principal.
- **Icône carmin plutôt que template** : voir § 1, décision 2 — la barre de menus est
  translucide, aucune couleur fixe n'y est vérifiable par calcul.
- **Article « Démarrer / Arrêter la dictée »** : décision 1 d'Alexandre, observation
  seule en M6. Réversible plus tard ; techniquement il passerait par
  `dispatcher.trigger()` (rapide, non bloquant, déjà anti-répétition) et **jamais** par
  `controller.toggle()` en direct, qui garde son verrou pendant l'I/O de démarrage et
  gèlerait la run loop.
- **Notifications natives via `rumps.notification()`** : elles exigent un bundle
  `.app` avec un identifiant, ce qui n'arrive qu'en M7. On garde `notify()` (osascript),
  déjà en place et déjà testé.
- **Un seul clic pour mettre à jour** : trop expéditif pour une action qui réinstalle et
  relance.

## 7. Ce que je demande à Codex de challenger en priorité

1. **La cohabitation des deux boucles** — la jointure `run_loop` est-elle la bonne, ou
   y a-t-il un montage plus sûr ? Mes hypothèses sur rumps tiennent-elles ?
2. **La propriété du contrôleur** — `run_desktop()` le possède, le tray l'observe. Est-ce
   que le sondage à 0,25 s est le bon compromis, ou est-ce que je passe à côté d'un
   problème (course, fil, cohérence de l'affichage) ?
3. **Le démontage** — le `teardown` idempotent passé à la boucle et appelé par
   « Quitter » : est-ce que ça couvre tous les chemins de sortie ? Que faire d'un
   « Quitter » cliqué pendant `recording` ou pendant `processing` — abandonner (ce que
   fait `controller.shutdown()` aujourd'hui) ou attendre ?
4. **Le gel possible de 5 s** au démontage, sur le fil principal.
5. **`os.execv` depuis un worker** avec une run loop AppKit vivante.
