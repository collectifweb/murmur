# Round 2 - Contre-reponse Codex

## Points resolus depuis le round precedent

### Dispatcher hotkey

Resolu. J'accepte la correction de Claude, y compris sa precision plus forte que ma
formulation initiale : une file de capacite 1 ne suffit pas si elle met en attente un
second evenement arrive pendant un start lent. Elle borne les threads, mais elle ne
preserve pas l'intention utilisateur, car le second evenement peut encore etre execute
apres le start et devenir un STOP.

La bonne correction est bien :

- debouncer a l'arrivee de l'evenement Carbon, avant toute mise en file ;
- garder un seul worker resident ;
- ne jamais accumuler un compteur d'evenements clavier ;
- ignorer les triggers apres `closing=True` ;
- capturer/logguer/notifier les exceptions de `controller.toggle()`.

Je veux seulement verrouiller le contrat de maniere explicite : l'horodatage doit etre
pris avec une clock monotone dans `trigger()`, sous le verrou interne du dispatcher, et
la decision "accepte/rejete" doit etre prise avant de reveiller le worker. Le worker ne
doit pas recalculer le debounce sur son heure d'execution.

Les tests proposes par Claude sont exactement ceux qu'il faut : 100 triggers rapides
produisent un seul worker et un seul `toggle()` effectif ; une repetition rapprochee ne
devient pas un stop retardee meme si `toggle()` bloque artificiellement ; les triggers
apres fermeture sont ignores ; les exceptions sont observees.

Le debounce M4 dans `RecordingController.toggle()` reste acceptable comme garde
secondaire. Il ne doit plus etre le mecanisme porteur du raccourci global, mais je suis
d'accord pour ne pas toucher le controleur en M5.

### Propriete explicite du controleur

Resolu. `handler_factory(settings, *, return_controller=False)` est un compromis
acceptable : il preserve les appelants existants et donne a `run_desktop()` une
reference explicite au `RecordingController` quand il doit posseder le cycle de vie
macOS.

Le handler peut conserver `_recording_controller` pour l'observation HTTP, mais ce
n'est plus la source de verite pour le runner. C'etait le point important de ma critique.

Detail a specifier dans les tests : sur Linux, `handler_factory(settings)` doit rester
strictement compatible, et `handler_factory(settings, return_controller=True)` doit
retourner `(HandlerClass, None)` sans importer de pieces macOS natives.

### Route dediee `/api/hotkey-state` et `doctor`

Resolu. Je valide la route dediee plutot que l'extension de `/api/recording-state`.
Les deux etats n'ont pas le meme proprietaire : `recording-state` observe la machine a
etats du controleur, `hotkey-state` observe l'enregistrement du raccourci global.

Le schema propose est suffisant pour M5 :

- `registered`;
- `configured_key`;
- `status`;
- `error`.

Je garde deux exigences de mise en oeuvre :

- `doctor` doit utiliser un timeout court et retomber proprement sur un diagnostic
  statique quand le serveur resident ne repond pas ;
- quand `/api/doctor` est appele depuis le serveur resident, l'implementation doit
  eviter une dependance fragile a une auto-requete HTTP inutile. Soit le handler passe
  l'etat hotkey deja possede a `collect_diagnostics()`, soit l'auto-requete est bornee
  et testee avec le `ThreadingHTTPServer`. Je prefere la premiere forme, mais ce n'est
  pas un desaccord de plan.

La notification `critical` au demarrage reste utile comme retour immediat, mais elle
n'est plus la seule preuve. C'est l'ajustement que je voulais.

### Backend interne ctypes/PyObjC

Resolu. Je suis d'accord pour faire du binding interne le backend M5, derriere
`macos_hotkey.py`, et pour releguer `quickmachotkey` au rang de reference documentee.

Cela aligne le plan avec les exigences reelles : `OSStatus` brut, abonnement
`kEventHotKeyPressed` seulement, conservation et liberation explicites du handle,
tests par injection.

Point de vigilance non bloquant : les modules doivent rester importables sous Linux.
Le parsing, le dispatcher et les types d'erreur peuvent etre testes ici ; les imports
PyObjC/AppKit/Carbon reels doivent rester paresseux ou confines au runner natif.

### Ordre de teardown

Resolu, sous une interpretation precise du mot "close" pour le dispatcher.

L'ordre propose est le bon :

1. desinscrire le hotkey pour empecher de nouveaux callbacks ;
2. fermer le dispatcher ;
3. appeler `controller.shutdown()` ;
4. arreter le serveur macOS avec `server.shutdown()` puis `server.server_close()`.

Je recadre seulement ceci : `dispatcher.close()` doit garantir qu'aucun appel
`controller.toggle()` n'est encore en cours avant que `controller.shutdown()` commence,
ou au minimum faire un join borne du worker actif. Sinon on garde une course possible :
le hotkey est desinscrit, mais un toggle deja accepte peut encore manipuler le stream
pendant le shutdown du controleur.

Je valide aussi le fait de ne pas ajouter `server.shutdown()` aux branches Linux ou
`serve_forever()` tourne sur le fil principal. Le shutdown serveur supplementaire est
specifique a la branche macOS, ou le serveur tourne sur un fil secondaire.

La fermeture pendant `PROCESSING` est correctement cadree : M5 ne la resout pas et ne
doit pas pretendre le faire. L'arbitrage abandon documente vs join borne reste M6.

### Settings, CLI et AppKit minimal

Resolu.

Je valide :

- `Settings.hotkey` + `DEFAULT_CONFIG` + `APARTE_HOTKEY`, hors `EDITABLE_FIELDS` ;
- valeur vide comme "aucun raccourci enregistre" ;
- format macOS canonique distinct des accelerateurs Linux gsettings ;
- `normalize_hotkey()` / `hotkey_label()` dans `macos_hotkey.py` ;
- `--remove` macOS qui vide le champ ;
- serveur qui reste vivant si le hotkey echoue ;
- `macos_runloop.py` dedie, avec `NSApplication.sharedApplication()`, activation
  policy `accessory`, SIGINT restaure et runner injectable.

Ces choix repondent aux manques listes au round 1.

## Points encore en debat avec ma position actualisee

### Route dediee vs extension de `recording-state`

Je suis d'accord avec Claude : route dediee. Ce point n'est plus en debat pour moi.

### `--target != paste`

Je suis d'accord avec Claude : rejet clair en M5. Persister une cible demanderait de
faire evoluer `_deliver()` et le contrat produit du raccourci resident. Le chemin
actuel macOS livre vers `paste`, donc accepter `copy` ou `stdout` serait trompeur.

On pourra rouvrir ce choix plus tard si `copy` devient un vrai mode produit pour le
raccourci resident. Ce n'est pas necessaire pour M5.

### Debounce M4 conserve

Je suis d'accord. Le debounce interne reste une garde secondaire et limite les effets
d'un appel direct accidentel a `toggle()`. La correction M5 doit toutefois etre testee
independamment de ce debounce interne, car elle porte sur le temps d'arrivee des
evenements clavier.

### Combinaison par defaut `Control+Option+D`

Acceptable comme defaut M5, avec confirmation M8.

La combinaison evite les conflits macOS evidents que nous voulions eviter :
`Command+Space` pour Spotlight, `Control+Space` / `Control+Option+Space` pour les
sources de saisie, `Fn-D` pour la dictee systeme, et les raccourcis de capture
`Shift+Command+3/4/5`. J'ai aussi verifie la liste Apple Support actuelle des
raccourcis Mac : `Control+Option+D` n'y apparait pas comme raccourci systeme global
standard. Ce n'est pas une preuve d'absence de conflit applicatif ou local, donc la
validation runtime reste bien M8.

Le choix est donc acceptable parce que :

- il est mnemonique pour dictee ;
- il evite `Command`, souvent plus charge dans les apps ;
- l'echec d'enregistrement sera observable via `/api/hotkey-state` et `doctor` ;
- l'utilisateur pourra modifier ou supprimer la combinaison par fichier/CLI.

### Cadrage "M5 mock-teste, natif non valide avant M8"

Acceptable et meme obligatoire. Le plan M5 peut etre considere pret seulement s'il est
presente comme "implemente et prouve par tests mockes", pas comme "valide sur macOS".

M8 reste le lieu de verite pour :

- cohabitation reelle `NSApplication` + `RegisterEventHotKey` ;
- OSStatus reels sur combinaison reservee ou deja prise ;
- duplication effective des evenements ;
- TCC micro et accessibilite ;
- PortAudio reel.

Ce cadrage ne diminue pas M5 ; il rend sa preuve honnete.

## Evaluation globale

Il ne reste plus de desaccord bloquant sur le plan M5.

Les points resolus depuis le round precedent sont substantiels : le dispatcher est
maintenant borne et debounced a l'arrivee ; le controleur a une propriete explicite ;
`doctor` obtient une surface read-only utile ; le backend interne donne acces au
statut Carbon ; le teardown a un ordre coherent ; les options CLI ambigues sont
definies.

Les points encore ouverts sont des reports explicites, pas des trous du plan M5 :

- validation native macOS en M8 ;
- confirmation finale de `Control+Option+D` en M8 ;
- fermeture pendant `PROCESSING` en M6 ;
- re-enregistrement a chaud en M6 ;
- surface d'etat riche en M6.

Ma seule condition de precision pour l'implementation est que `dispatcher.close()`
garantisse l'absence de `toggle()` concurrent avant `controller.shutdown()`. Avec cette
lecture, le plan est pret.

CONSENSUS_ATTEINT
