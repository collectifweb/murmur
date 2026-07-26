# M6 sur un vrai Mac — les cinq étapes

Montage inchangé : `.claude/mac-validation/README.md`. Ici, seulement le contenu
des étapes.

Côté Linux, pour chaque étape :

```bash
cd .claude/mac-validation
tar czf serve/src.tar.gz -C ../../src aparte   # avant l'étape 1 seulement
cp m6/etape1.sh serve/step.sh                  # puis etape2.sh, etc.
```

L'humain double-clique l'icône du Bureau, attend « Journal envoyé », et on lit
`logs/step.log`. Ranger ensuite chaque journal dans `../journaux/` sous son nom
d'étape, comme pour M8.

**Adapter `RELAY=` en tête de `etape1.sh`, `etape4.sh` et `etape5.sh`** (l'IP du poste
Linux), comme dans `amorce.sh` — ce sont les trois qui téléchargent du code.
L'étape 4 recharge `src.tar.gz` avant sa relance, pour vérifier au passage ce que
l'étape 1 a fait corriger.

## Ce que chaque étape prouve

| Étape | Points de la checklist du plan | Ce que l'humain doit regarder |
|-------|-------------------------------|-------------------------------|
| 1 | 1, 2 | l'icône apparaît, ne vole pas le focus, lisible en barre claire **et** sombre |
| 2 | 3, 4 | l'icône change en moins d'une demi-seconde, le minuteur défile, `…` pendant la transcription |
| 3 | 5, 8 | les lignes du menu disent l'état réel ; la mise à jour refuse pendant une dictée |
| 4 | 6, 7 | « Quitter » démonte tout ; le Ctrl-C (envoyé par le script, jamais tapé) est **observé**, pas supposé |
| 5 | 9, puis 6 à nouveau | sans `rumps`, le serveur et le raccourci marchent, `doctor` le dit ; puis « Quitter » laisse enfin sa trace |

## Deux règles du montage qui comptent particulièrement ici

- **Jamais demander un Ctrl-C à l'humain** : il tue le groupe de processus, `tee`
  compris, et le journal n'est jamais envoyé. L'étape 4 envoie donc le `SIGINT`
  elle-même, à un PID précis.
- **Ce qui ne laisse pas de trace se demande** : une icône vue ou non, un son
  entendu ou non. Les étapes posent la question et répètent la réponse dans le
  journal.

## Ce que ces étapes ne prouveront pas

L'installation d'une mise à jour de bout en bout : elle demande une release
taguée plus récente que celle installée, et le Mac de test reçoit son code par
`src.tar.gz`, pas par `git pull`. L'étape 3 vérifie le refus pendant une dictée et
la vérification elle-même ; le reste attend un vrai tag, donc M7.
