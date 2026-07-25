# M8 — Validation native macOS (smoke suite manuelle)

Tout le portage macOS (M0–M7) est **prouvé sous Linux par tests mockés** : PyObjC,
Carbon et PortAudio n'y existent pas. M8 est la seule étape qui prouve le
comportement **réel**, et elle est **manuelle** — un humain devant un vrai Mac.

Un runner CI macOS ne suffit pas : il ne peut ni accorder une permission TCC, ni
capter un raccourci clavier global, ni donner le focus à une autre application.
Ces trois choses exigent une session interactive.

## Prérequis

- Un Mac (noter la version : **Sequoia 15** a changé des réservations de
  raccourcis — vérifier ⌃⌥D en priorité ; **Sonoma 14** ou avant : réservations
  différentes).
- Clone du dépôt, puis `pip install -e ".[macos]"`.
- Quitter toute instance d'Aparté déjà lancée avant les tests de raccourci (le
  serveur résident détiendrait déjà la combinaison — un second inscripteur
  échouerait, ce qui fausserait la lecture).

## Les deux mesures ouvertes (elles décident du code)

Le plan M5 a laissé deux points à trancher **par observation**, pas par
raisonnement :

1. **Un appui physique = un ou plusieurs événements « pressé » ?** Décide s'il faut
   restreindre la portée du debounce. La façade s'abonne au seul `kEventHotKeyPressed` ;
   si un appui unique en produit plusieurs, on le saura ici.
2. **⌃⌥D est-elle libre sur cette machine/version ?** `OSStatus` réel de
   `RegisterEventHotKey`.

L'outil qui répond aux deux, sans deviner :

```
aparte install-hotkey --diagnostic          # combi configurée, sinon ⌃⌥D
aparte install-hotkey --diagnostic --key cmd+shift+space
```

Il inscrit la combinaison **en direct** (hors serveur, hors répartiteur — donc
événements **bruts**), imprime l'`OSStatus`, puis journalise chaque événement reçu
avec l'écart depuis le précédent. Appuyer une fois → doit afficher **une** ligne
`press #1`. Appuyer vite deux fois → deux lignes, avec l'écart en secondes à
comparer aux 250 ms du debounce. `Ctrl-C` pour arrêter. **À rapporter : le nombre
de lignes par appui unique, et l'écart d'un double-tap.**

## Checklist (dans l'ordre des dépendances)

Chaque étape : geste → attendu → signature d'échec → invariant prouvé.

### 1. Démarrage
- **Geste** : `aparte desktop`.
- **Attendu** : l'app démarre, une seule run loop AppKit, le serveur répond sur
  `http://127.0.0.1:8765`.
- **Échec** : plantage à l'import PyObjC/AppKit ; ou l'UI web ne répond pas (run
  loop qui monopolise, serveur pas passé sur son fil daemon).
- **Invariant** : run loop unique sur le fil principal, serveur sur fil daemon.

### 2. Permissions TCC, à travers une relance
- **Geste** : première dictée navigateur → accorder Micro ; tenter une insertion →
  accorder Accessibilité ; **quitter et relancer** Aparté.
- **Attendu** : après relance, `aparte doctor` montre Micro ✓ et Accessibilité ✓
  sans redemander.
- **Échec** : permission redemandée à chaque lancement (identité de l'app/signature
  instable) ; ou `doctor` affiche ✓ alors que l'action échoue.
- **Invariant** : lecture TCC via `macos_permissions` (AVFoundation / `AXIsProcessTrusted`).

### 3. Inscription du raccourci
- **Geste** : `aparte install-hotkey` (persiste ⌃⌥D), puis **redémarrer** l'app ;
  ouvrir `http://127.0.0.1:8765/api/hotkey-state`.
- **Attendu** : `{"registered": true, "configured_key": "ctrl+opt+d", "status": null,
  "error": null}` ; `doctor` affiche « Raccourci de dictée ⌃⌥D » coché.
- **Échec** : `registered:false` + un `status` (OSStatus) → combinaison réservée/prise
  (voir table plus bas) ; passer à une autre combi via `--key`.
- **Invariant** : `Settings.hotkey` réglage de fichier lu au démarrage ; `serve_macos`
  publie l'état ; route lecture seule.

### 4. Bascule + insertion
- **Geste** : dans une app tierce (TextEdit, Slack), appuyer ⌃⌥D, parler, ré-appuyer.
- **Attendu** : premier appui = enregistre ; second = transcrit **et insère le texte
  dans l'app au premier plan**, typographie française correcte (`’ « » U+00A0`).
- **Échec** : rien ne s'insère (le texte reste au presse-papier = repli Accessibilité
  refusée) ; ou caractères français cassés (chemin de frappe directe fautif) ; ou
  aucune réaction (raccourci non livré → revoir étape 3 et le `--diagnostic`).
- **Invariant** : raccourci in-process qui déclenche `toggle()` ; livraison `paste` ;
  polissage français dans le worker.

### 5. Double-appui rapide (le vrai test du répartiteur)
- **Geste** : appuyer ⌃⌥D **deux fois très vite** (< 250 ms) pour démarrer.
- **Attendu** : l'enregistrement **démarre et reste actif** — le second appui est
  absorbé, il n'arrête pas ce que le premier vient de lancer.
- **Échec** : l'enregistrement démarre puis s'arrête aussitôt (le bug que le
  répartiteur ferme serait revenu).
- **Invariant** : debounce **à l'arrivée**, worker unique, jamais un fil par appui.

### 6. Combinaison réservée → observable, serveur vivant
- **Geste** : `aparte install-hotkey --key cmd+space` (Spotlight), redémarrer.
- **Attendu** : notification `critical` au démarrage ; `doctor` et `/api/hotkey-state`
  montrent l'échec avec l'`OSStatus` ; **l'UI web et la dictée navigateur marchent
  toujours**.
- **Échec** : l'app plante ; ou l'échec est silencieux (pas de notification, pas
  d'état).
- **Invariant** : échec d'inscription → notification `critical`, serveur survit.

### 7. Fermeture propre
- **Geste** : `Ctrl-C` (ou quitter) pendant l'inactivité, puis pendant un
  enregistrement.
- **Attendu** : arrêt sans micro laissé ouvert ; teardown ordonné (raccourci
  désinscrit → répartiteur fermé → contrôleur arrêté → serveur fermé).
- **Échec** : processus `arecord`/PortAudio orphelin ; interblocage à la sortie.
- **Invariant** : `finally` ordonné ; `server.shutdown()` sûr (fil daemon).

## Table des OSStatus utiles

| Valeur | Nom | Sens |
|--------|-----|------|
| `0` | `noErr` | inscription réussie |
| `-9868` | `eventHotKeyExistsErr` | combinaison déjà prise par un autre client |
| `-9878` | `eventHotKeyInvalidErr` | combinaison invalide/refusée |

(La liste fait foi côté Apple ; noter la valeur réelle observée, elle peut varier
selon la version.)

## Ce qu'il faut me rapporter

- Version de macOS.
- Étape 3 : contenu exact de `/api/hotkey-state` (surtout `status` si échec).
- `--diagnostic` : lignes par **appui unique** (1 attendu) et écart d'un
  **double-tap**.
- Toute étape en « échec » avec sa signature observée.

À partir de là, je corrige le code ; le reste des invariants est déjà tenu par la
suite mockée (**368 tests verts** sous Linux).
