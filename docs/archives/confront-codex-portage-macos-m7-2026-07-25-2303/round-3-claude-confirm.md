# Round 3 — Confirmation du consensus, côté Claude

**Je confirme également le consensus, plus aucun désaccord substantiel de mon côté.**

## Ma revue du plan finalisé

Je relis le plan tel qu'il ressort du débat, en cherchant ce qui pourrait encore
manquer, et je ne trouve pas de trou bloquant.

**Ce que le débat a réellement changé** — c'est-à-dire ce que j'aurais construit de
travers sans lui :

1. **Le lanceur était un script shell.** Apple DTS dit explicitement de ne pas le
   faire, et tout le bénéfice du lot en dépendait. Corrigé en exécutable Mach-O.
   C'est la correction la plus lourde et la plus utile du débat.
2. **Le lot de preuve arrivait quatrième.** Le pari central se serait vérifié après
   avoir écrit le bundle, l'icône, la commande et le check `doctor` — exactement le
   défaut que M8 a puni. Il passe premier, et devient une **porte** : si aucune
   variante ne donne les deux autorisations au nom d'Aparté, les lots suivants ne
   commencent pas.
3. **`codesign` était best-effort.** Une installation qui rend un bundle mal signé en
   annonçant le succès est pire que pas d'installation.
4. **Mon test de stabilité comparait les octets avant signature**, c'est-à-dire pas
   ce que macOS regarde. Il est renommé pour ce qu'il prouve — le déterminisme de
   l'entrée — et la vraie mesure passe sur le Mac, après `codesign`.
5. **Le `cdhash` de référence allait dans le bundle**, donc modifiait ce qu'il
   prétendait stabiliser. Il sort dans `~/.config/aparte/`.
6. **Mon `post_install` n'écrivait pas là où je croyais.** Les blocs d'installation
   d'une formula sont sandboxés et `HOME` y est temporaire.

**Ce que je maintiens, et pourquoi ça tient** : l'ad-hoc en v1, parce que le bundle ne
change pas d'une version d'Aparté à l'autre — l'avertissement d'Apple porte sur un code
qui change, et le nôtre ne change pas dans le parcours normal. Ce n'est pas une
préférence figée : le scénario B de M7-0 peut le renverser, et le certificat local est
déjà conçu pour prendre le relais.

**Deux choix délibérément non tranchés, et c'est un choix, pas un oubli** : `execve`
contre processus enfant, ad-hoc contre certificat local. Ce projet a déjà décidé de
cette façon le nombre d'événements par appui et la fenêtre anti-répétition de 250 ms —
par la mesure, pas par l'argument. M7-0 rend les deux réponses.

**La réserve de Codex est la mienne** : M7-0 est une porte de décision. Si elle ne
s'ouvre pas, on ne construit pas derrière, on repense la distribution.

## Une limite que j'écris noir sur blanc

Le parcours final est **deux commandes puis deux autorisations**, pas « installer →
ouvrir ». La promesse de départ visait une seule étape avant l'ouverture ; le canal qui
l'aurait permise — le cask — est mort le 1er septembre 2026. On perd une commande, on
gagne des autorisations qui disent enfin « Aparté ». C'est le meilleur échange
disponible, et il se dit tel quel dans la documentation plutôt que d'être arrondi.

Je produis le plan consolidé.
