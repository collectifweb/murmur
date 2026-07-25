# M8 — Validation native macOS : résultats

**Exécuté le 25/07/2026 sur macOS 11.7.11 (Big Sur), Intel x86_64, Python 3.11.9.**

Tout le portage macOS (M0–M7) était **prouvé sous Linux par tests mockés** : PyObjC,
Carbon et PortAudio n'y existent pas. M8 était la seule étape à prouver le
comportement **réel**, et elle est manuelle — un humain devant un vrai Mac.

Elle a trouvé **un plantage**, **trois défauts**, et **invalidé une hypothèse du
plan lui-même**. Aucun ne pouvait être vu sous Linux.

---

## Ce que la machine a exigé (à savoir avant de recommencer)

Big Sur est plus vieux que ce que le plan visait (Sequoia/Sonoma). Conséquences :

- **Python 3.10+ doit être installé** : Big Sur livre 3.8. L'installateur
  universal2 de python.org (`python-3.11.9-macos11.pkg`) s'installe sans Xcode
  ni compte Apple, en ligne de commande (`sudo installer -pkg … -target /`).
- **Python 3.11, pas plus récent, sur un Mac Intel.** C'est la dernière version
  pour laquelle toute la chaîne existe en paquet précompilé : `av` n'en a plus
  pour 3.12 sur Intel, et il faudrait compiler.
- **`pip install --prefer-binary`** est obligatoire. Sans lui, pip prend la
  dernière version de chaque paquet, tombe sur celles qui ne visent plus les Mac
  Intel ou exigent macOS 13, et tente de recompiler. Versions retenues :
  `av 18.0.0`, `ctranslate2 4.8.1`, `onnxruntime 1.19.2` (la dernière avec une
  roue pour macOS 11), `numpy 2.4.6`, PyObjC 12.2.1.
- **La ligne d'installation du plan initial était fausse** : `pip install -e
  ".[macos]"` n'installe pas `sounddevice`, qui vit dans l'extra `recording`. La
  bonne ligne est `pip install --prefer-binary -e ".[whisper,recording,macos]"`.
- **`quickmachotkey` est dans l'extra `macos` mais n'est jamais utilisé** : le
  pont Carbon est écrit en `ctypes` à la main. Dépendance morte, à retirer.

---

## Résultats de la checklist

| # | Point | Verdict |
|---|-------|---------|
| 1 | Démarrage : run loop AppKit + serveur | ✅ |
| 2 | Autorisations TCC à travers une relance | ✅ (après correction, voir A) |
| 3 | Inscription du raccourci ⌃⌥D | ✅ `registered: true`, aucun OSStatus |
| 4 | Bascule + insertion + typographie française | ✅ |
| 5 | Double-appui rapide absorbé | ✅ mesuré à 200 ms → `IGNORE` |
| 6 | Combinaison réservée → échec observable | ❌ **inatteignable** (voir C) |
| 7 | Fermeture propre | ⚠️ partiel (voir D et E) |

### Les deux mesures que le plan laissait ouvertes

1. **Un appui physique = un événement, exactement.** Quatre appuis espacés ont
   produit quatre lignes, jamais de doublon ni de répétition automatique. La
   portée du filtre anti-répétition n'a pas besoin d'être restreinte.
2. **⌃⌥D est libre sur Big Sur** : `RegisterEventHotKey` rend `noErr`.

Mesures complémentaires, qui ont tranché la valeur du filtre :

- Double-appui **volontairement rapide** : 200 à 216 ms.
- Double-appui **à vitesse naturelle** : 512 à 800 ms (cinq mesures).

La fenêtre de 250 ms est donc **au bon endroit** et reste inchangée : elle avale
le geste réflexe et laisse passer une intention. Un geste à 700 ms est un arrêt
délibéré, pas un accident.

### Typographie française, vérifiée caractère par caractère

Dicté dans TextEdit et dans LibreOffice, relu dans le presse-papier :

> `Il m’a dit que c’est vraiment l’été, n’est-ce pas ?`

Quatre apostrophes courbes U+2019, aucune U+0027, une espace insécable U+00A0
devant le point d'interrogation — et **pas** la fine U+202F. La promesse centrale
du projet tient sur le chemin macOS.

---

## A. Le plantage : signatures ctypes absentes (corrigé)

**Symptôme** : `Segmentation fault: 11` à la toute première exécution native, avant
même la ligne `registered`.

**Cause, prouvée** : `_CarbonBackend` ne déclarait ni `restype` ni `argtypes`, donc
ctypes supposait des entiers 32 bits. Mesuré sur la machine :

```
pointeur réel      : 0x00007ffc9f816590
supposé par ctypes : -0x0000000607e9a70   ← la moitié haute a disparu
```

Carbon recevait une adresse inventée et plantait en la déréférençant.

**Corrigé** (`fb23b1a`) : toutes les signatures déclarées ; `ItemCount` et
`ByteCount` passés en `unsigned long` 64 bits ; classes de structures construites
une seule fois (ctypes rapproche un argument de son `argtype` par identité de
classe) ; un `InstallEventHandler` refusé lève désormais au lieu de laisser un
raccourci inscrit qui ne se déclenche jamais.

## B. Le micro n'était jamais demandé (corrigé)

**Symptôme** : sur un Mac neuf, la première dictée enregistre **du silence**. Pas
de message, pas de fenêtre, pas d'erreur.

**Cause** : ouvrir un flux PortAudio **ne déclenche aucune demande TCC**. Le flux
s'ouvre « sans erreur » pendant que le statut reste `not_determined`. Le plan
supposait qu'une dictée dans le navigateur suffirait à accorder le micro — c'est
faux : ça n'autorise que Safari, pas Aparté.

**Corrigé** (`d801456`) : `request_microphone_access()` (AVFoundation) ouvre la
fenêtre et **attend** la réponse ; `ensure_microphone_access()` garde les deux
seuls chemins de capture et refuse d'enregistrer plutôt que de livrer du silence.

**Validé sur la machine**, autorisation remise à zéro par
`tccutil reset Microphone com.apple.Terminal` : refus → état `error` + statut
`denied`, aucun enregistrement ; acceptation → `authorized` + dictée livrée.

## C. Aucun refus d'inscription n'est observable sur macOS

Deux cas testés, **les deux acceptés** par `RegisterEventHotKey` :

- **⌘Espace**, que Spotlight détient : `registered: true`, aucun OSStatus.
- **Un second Aparté** réclamant ⌃⌥D pendant que le premier le détient :
  `registered: true` lui aussi.

**Conséquence à connaître** : `registered: true` signifie **« macOS a accepté
l'inscription »**, jamais **« le raccourci fonctionne »**. Un raccourci capté par
un autre client est indistinguable d'un raccourci vivant. Toute la mécanique
« échec d'inscription → notification `critical` → OSStatus dans `doctor` » garde
donc une porte que macOS n'ouvre pas — elle reste correcte, mais inatteignable en
pratique. Le point 6 de la checklist est **non testable** tel qu'il était écrit.

Vérifier vraiment supposerait d'observer un appui réel, ce qu'aucun sondage
passif ne peut faire. Décision : **documenter la limite, ne pas coder contre**.

## D. `Ctrl-C` ne fait aucun démontage ordonné

`_appkit_run_loop` remet SIGINT à `SIG_DFL` avant de lancer la boucle, donc un
Ctrl-C **tue le processus net** : pas de `KeyboardInterrupt`, pas de `finally`,
pas de « Stopping desktop server ». Vérifié : la ligne n'apparaît jamais.

Sans conséquence pratique — tout est en mémoire, et le test « tuer en plein
enregistrement » n'a laissé **aucun processus survivant, aucun lecteur audio
orphelin, port libéré**. Mais l'invariant écrit décrivait quelque chose qui
n'arrive pas. Le démontage ordonné vaut pour la sortie *normale* de la boucle
(le futur « Quitter » du tray, M6), pas pour Ctrl-C.

## E. Captures audio abandonnées (corrigé)

Un processus tué **entre l'écriture du `.wav` et la fin de la transcription**
laisse la voix de l'utilisateur dans le dossier temporaire — le `finally` qui
supprime n'a jamais lieu. Deux fichiers retrouvés après les essais.

**Corrigé** (`6d0c012`) : `sweep_orphan_recordings()` au démarrage du serveur,
sur les fichiers de plus d'une heure — jamais la capture vivante d'une autre
instance — et sur un motif qui épargne les bips mis en cache.

## F. `doctor` donnait un conseil Linux sur Mac (corrigé)

`hotkey  bind manually: python -m aparte toggle --target paste`, affiché juste
sous un « Dictation shortcut » coché. `hotkey_info()` interrogeait gsettings et la
détection d'environnement de bureau, absents sur Mac. Le panneau web aurait de
même averti qu'un raccourci vivant n'était pas lié.

**Corrigé** (`b40ed80`) : même forme, contenu macOS. `doctor` affiche désormais
`hotkey  bound to ⌃⌥D`.

## G. Le silence, seul vrai problème d'usage rencontré

Le mécanisme du double-appui est correct, et l'utilisateur s'est quand même
trompé : n'ayant **aucun retour**, il a cru que son appui n'avait rien fait, a
réappuyé, et a arrêté l'enregistrement que le premier venait de lancer.

Sur macOS il n'y a ni icône de barre de menus (M6), ni fenêtre — une application
« accessory » n'affiche rien. **Le bip est le seul signal existant**, et il était
désactivé par défaut. Il est désormais actif par défaut sur macOS seulement
(`6d0c012`) ; sous Linux l'icône du panneau fait déjà le travail.

Ça reste un pansement : 90 ms de tonalité se manquent facilement quand on est en
train de parler. **Le vrai correctif est M6.**

---

## Reste ouvert

- **M6 (barre de menus)** devient prioritaire : c'est le seul retour visuel
  possible, et M8 a montré que son absence induit l'utilisateur en erreur.
- **`quickmachotkey`** à retirer de l'extra `macos` (jamais importé).
- **Hallucination `Thank you.`** insérée sur du silence : `hallucinations.py`
  connaît « Thanks for watching » mais pas « Thank you » seul. **Décidé : ne rien
  ajouter** — deux mots parfaitement dictables, et le module dit « dans le doute,
  ne rien toucher ».
- **Qualité de transcription** sur Mac Intel : `small` sur processeur, comptez 10
  à 40 s pour quelques secondes de parole.

## Méthode, si c'est à refaire

Le Mac était derrière un second routeur et le poste Linux derrière un VPN : aucune
connexion entrante possible. Le montage qui a marché inverse le sens — le Mac va
chercher chaque étape sur un petit serveur du poste Linux et lui renvoie son
journal, déclenché par une icône unique à double-cliquer sur le Bureau. Une seule
commande tapée à la main sur le Mac, pour toute la session.
