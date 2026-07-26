## **Points résolus depuis le round précédent**

Le `post_install` est réglé. Claude ne le déplace pas sous un autre nom et ne cherche
pas à conserver la promesse `brew install -> ouvrir` par un hook Homebrew : il retire
le mécanisme, admet que `HOME` est temporaire/sandboxé, et assume le parcours réel :

```text
brew install collectifweb/aparte/aparte
aparte install-app --open
(deux autorisations)
```

La précision `--open` est acceptable. Elle ne maquille pas la commande intermédiaire :
le plan dit clairement "deux commandes puis deux autorisations". C'était exactement la
correction demandée.

Sur l'ad-hoc, les trois contraintes que j'avais ajoutées sont reprises sans
affaiblissement :

- `brew upgrade` est testé comme un vrai upgrade, avec SHA-256 du bundle, `cdhash`,
  `codesign -d -r-` et état TCC avant/après ;
- les entrées de compilation sont verrouillées dans la limite de ce qu'on contrôle :
  pas de `__DATE__`/`__TIME__`, pas d'infos de debug portant des chemins temporaires,
  options fixes, cible de déploiement fixe ;
- `install-app --force` prévient avant de remplacer un bundle dont le `cdhash`
  changerait, et la référence est stockée hors du bundle.

Sur M7-0, le protocole couvre maintenant ce qui manquait. Les deux variantes de
lanceur (`execve` et processus enfant surveillé) déclenchent et vérifient les deux
autorisations promises : Microphone via AVFoundation et Accessibilité via
`AXIsProcessTrustedWithOptions`. Les relevés demandés sont là : nom dans la fenêtre,
entrée et icône dans Réglages Système, `codesign --verify --strict`,
`codesign -d -r-`, `cdhash`, mode de lancement Finder/`open`.

Le test ad-hoc contre certificat local devient concluant : scénario A ad-hoc identique,
scénario B ad-hoc volontairement différent à `CFBundleIdentifier` constant, scénario C
certificat local auto-signé avec rebuild différent. L'isolation par `tccutil reset`
ou compte utilisateur neuf, ainsi que `xattr -lr` pour la quarantaine, répondent au
manque que j'avais signalé.

La formula est aussi assez explicite pour avancer : Python épinglé, dépendances natives
`portaudio`/`libsndfile`, extras `whisper,recording,macos`, exclusion de `cuda`,
`brew test` minimal, caveats incluant `install-app --open`, `install-hotkey`, le modèle
au premier lancement et `uninstall-app`.

## **Points encore en débat**

Aucun.

Je ne détecte pas de contrainte acceptée puis affaiblie. La phrase "ad-hoc en v1" reste
conditionnelle parce que M7-0 peut encore l'invalider au profit du certificat local. Le
plan n'est donc pas en train de figer ad-hoc par préférence ; il le garde comme option
par défaut tant que la mesure ne l'a pas rejeté.

## **Évaluation globale**

Il ne reste pas de désaccord bloquant. Le plan est prêt dans sa forme actuelle, à une
condition déjà intégrée à sa structure : M7-0 est une porte de décision. Si aucune
variante de lanceur et aucun scénario de signature ne donne les deux autorisations au
nom d'Aparté avec une conservation TCC acceptable, les lots suivants ne doivent pas
commencer et la distribution doit être repensée.

Sous cette réserve, qui n'est pas un nouveau désaccord mais le sens même de M7-0, je
valide le plan consolidé.

CONSENSUS_ATTEINT
