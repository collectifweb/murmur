# Valider Aparté sur un vrai Mac, sans SSH

Montage utilisé pour M8 le 25/07/2026, à reprendre tel quel pour M6 et M7.

## Le problème qu'il résout

Le Mac de test est derrière un second routeur et le poste Linux derrière un VPN :
**aucune connexion entrante n'est possible**, ni SSH, ni partage de fichiers. Et
même avec SSH, les essais ne pourraient pas s'y faire — une session distante n'est
pas rattachée à la session graphique, donc aucune fenêtre d'autorisation
n'apparaît, le raccourci global ne reçoit rien, et il n'y a pas d'application au
premier plan où insérer du texte.

**On inverse le sens** : le Mac vient chercher chaque étape sur le poste Linux et
lui renvoie son journal. Une seule commande tapée à la main sur le Mac, pour toute
la session. Ensuite, tout se fait par double-clic.

## Mise en route

1. **Adapter l'adresse.** `RELAY=http://<ip-du-poste-linux>:8010` dans
   `amorce.sh` et `aparte-etape.command`, et la même dans chaque `step.sh`.
2. **Ouvrir le port**, réseau local seulement :
   `sudo ufw allow from 192.168.0.0/16 to any port 8010 proto tcp`
   (à retirer à la fin : même ligne avec `delete` devant `allow`).
3. **Si le poste est derrière un VPN**, autoriser le partage réseau local
   (Mullvad le bloque par défaut, sans quoi le Mac n'atteint rien).
4. **Lancer le relais** dans un terminal, et le laisser ouvert :
   `python3 relay.py`. Il sert les fichiers de `serve/` et reçoit les journaux
   dans `logs/`.
5. **Sur le Mac**, une seule fois :
   `curl -m10 <ip>:8010/amorce.sh | sh` — ça dépose `aparte-etape.command` sur le
   Bureau.

## Le cycle de travail

- On écrit l'étape courante dans `serve/step.sh` côté Linux.
- L'humain double-clique l'icône du Bureau : elle télécharge `step.sh`,
  l'exécute dans une **vraie fenêtre Terminal** (donc autorisations et raccourci
  fonctionnent), et renvoie tout le journal.
- On lit `logs/step.log`, on écrit l'étape suivante, on recommence.

Pour livrer du code corrigé au Mac : `tar czf serve/src.tar.gz -C src aparte`,
puis dans l'étape `curl … -o src.tar.gz`, **vérifier la somme de contrôle** et
seulement ensuite `tar xzf src.tar.gz -C src`. Le relais parle en clair sur le
réseau local et ce qu'il sert devient le code exécuté : la somme est ce qui
distingue notre archive de celle d'un autre. Les étapes de M6 montrent le patron
(`m6/etape1.sh`, fonction `recuperer_le_code`), et la somme s'injecte au moment
de servir, comme l'adresse.
L'installation est en mode éditable, la correction prend effet au redémarrage du
serveur.

## Pièges appris à la dure

- **Toujours `export PYTHONUNBUFFERED=1`** dans `step.sh` : sans ça, un processus
  tué emporte sa sortie encore en tampon et le journal arrive vide.
- **Jamais demander un `Ctrl-C`** à l'humain : il tue tout le groupe de processus,
  `tee` compris, et l'envoi du journal n'a jamais lieu. Utiliser un minuteur puis
  `kill` sur le processus visé.
- **Un serveur qui doit survivre à l'étape** se lance en tâche de fond avec sa
  sortie redirigée (`nohup … > desktop.log 2>&1 < /dev/null &`), sinon le tuyau
  reste ouvert et la fenêtre ne se termine jamais.
- **Dire à l'humain d'attendre la ligne « Journal envoyé »** avant de fermer la
  fenêtre, et de ne pas relancer entre-temps : `tee` vide `step.log` au démarrage,
  donc un second clic efface le journal du premier.
- **Demander explicitement ce qui ne laisse pas de trace** : un son entendu ou
  non, une fenêtre apparue ou non. Le journal ne le sait pas.

## Journaux de M8

`journaux/` garde les onze étapes du 25/07, dans l'ordre. `etape2-segfault.log`
est le plantage du pont Carbon, `etape3-diagnostic-ok.log` la preuve chiffrée de
sa cause et les deux mesures ouvertes du plan. Le compte rendu complet est dans
`docs/plan-portage-macos-m8.md`.
