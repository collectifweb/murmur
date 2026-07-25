# Round 2 — Confirmation de consensus (Claude)

Je confirme également le consensus : **plus aucun désaccord substantiel de mon côté**.

Codex a émis `CONSENSUS_ATTEINT` avec une **précision d'implémentation** que j'adopte,
plus deux notes de vigilance que je fais miennes. Aucune ne rouvre le plan — elles le
resserrent.

## La précision de Codex, adoptée

- **`dispatcher.close()` fait un `join()` borné du worker actif avant de rendre la
  main.** Sinon un `toggle()` déjà accepté (donc en train de manipuler le stream/timer)
  pourrait tourner **pendant** `controller.shutdown()` — course résiduelle réelle.
  Ordre de fermeture verrouillé : (1) désinscrire le hotkey (plus de callback) →
  (2) `dispatcher.close()` = `closing=True` **puis `join()` borné du worker** →
  (3) `controller.shutdown()` → (4) `server.shutdown()` + `server.server_close()`.
  Un test couvre : un `toggle()` en cours est bien terminé (ou joint dans la borne)
  avant que `shutdown()` du contrôleur ne commence.

## Deux notes de vigilance de Codex, adoptées

- **`doctor` servi par le serveur résident ne fait pas d'auto-requête HTTP.** Quand
  `/api/doctor` est traité **dans** le serveur résident, le handler passe l'état hotkey
  **qu'il possède déjà** à `collect_diagnostics()`, au lieu d'une auto-requête vers
  `/api/hotkey-state`. L'auto-requête (bornée, court timeout) ne sert qu'au cas
  `aparte doctor` **en process CLI séparé** interrogeant un serveur qui tourne ; absence
  de réponse → repli statique propre.
- **Dispatcher : horodatage sous le verrou interne, décision avant de réveiller le
  worker.** `trigger()` prend le temps monotone sous le lock du dispatcher, tranche
  accepte/rejette **là**, et ne réveille le worker que si accepté. Le worker ne
  recalcule jamais le debounce sur son heure d'exécution. (C'était déjà mon intention ;
  je le verrouille comme contrat de test.)
- **Importabilité Linux stricte.** `handler_factory(settings)` reste compatible ;
  `handler_factory(settings, return_controller=True)` rend `(HandlerClass, None)` sur
  Linux **sans importer** de pièces natives. Parsing, dispatcher et types d'erreur sont
  testés sous Linux ; les imports PyObjC/AppKit/Carbon réels restent **paresseux**,
  confinés au runner natif.

## Ma revue du plan finalisé

Le plan M5 est **prêt** : dispatcher borné et debouncé à l'arrivée (correction d'un vrai
bug), ownership explicite du contrôleur, surface `doctor` lecture-seule utile, backend
Carbon interne exposant l'`OSStatus`, teardown ordonné avec join borné, options CLI
définies (`--remove`, rejet `--target≠paste`), réglage `hotkey` propre, run loop AppKit
dédiée et injectable. Les points ouverts sont des **reports datés** (M6 : fermeture
pendant `PROCESSING`, ré-enregistrement à chaud, état riche ; M8 : validation native,
confirmation `⌃⌥D`, duplication d'événements, TCC, PortAudio), pas des trous.

Je produis le plan consolidé dans `docs/plan-portage-macos-m5.md`.
